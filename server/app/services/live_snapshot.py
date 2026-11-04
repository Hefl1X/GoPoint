"""Снимок машин на линии: один опрос источника на всех пользователей.

- Машины обновляются не чаще раза в poll_interval_s (30 с), пачками по
  max_lines_per_request маршрутов (у ЦУГАЭТ 6).
- Опрос идёт, только пока кто-то обращался к API за последние active_window_s (2 мин).
- Маршруты и линии хранятся сутки (lines_ttl_s).
- Если источник не ответил, остаётся прошлый снимок; для маршрутов, чья пачка
  не пришла, берутся машины из прошлого снимка. Время снимка лежит в служебном поле.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.models import Direction, Line, LinePath, LiveVehicle
from app.ports import TransitFeed, TransitFeedError

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Snapshot:
    vehicles: list[LiveVehicle]
    fetched_at: datetime  # когда начат опрос, давший этот снимок
    complete: bool  # все пачки пришли в этот раз
    by_line: dict[str, list[LiveVehicle]] = field(default_factory=dict)


@dataclass
class _Cached[T]:
    value: T
    at: datetime


class LiveSnapshotService:
    def __init__(
        self,
        feed: TransitFeed,
        *,
        clock: Clock = utc_now,
        poll_interval_s: int = 30,
        active_window_s: int = 120,
        lines_ttl_s: int = 86_400,
    ) -> None:
        self._feed = feed
        self._clock = clock
        self._interval = timedelta(seconds=poll_interval_s)
        self._active_window = timedelta(seconds=active_window_s)
        self._lines_ttl = timedelta(seconds=lines_ttl_s)
        self._snapshot: Snapshot | None = None
        self._last_attempt: datetime | None = None
        self._last_access: datetime | None = None
        self._lines: _Cached[list[Line]] | None = None
        self._paths: dict[tuple[str, Direction], _Cached[LinePath]] = {}
        self._refresh_lock = asyncio.Lock()
        self._lines_lock = asyncio.Lock()

    # ------------------------------------------------------------ активность

    def touch(self) -> None:
        """Кто-то обратился к API: опрос нужен ещё active_window_s."""
        self._last_access = self._clock()

    def is_active(self) -> bool:
        return (
            self._last_access is not None
            and self._clock() - self._last_access <= self._active_window
        )

    # ------------------------------------------------------------ маршруты и линии

    async def lines(self) -> list[Line]:
        async with self._lines_lock:
            now = self._clock()
            if self._lines and now - self._lines.at < self._lines_ttl:
                return self._lines.value
            try:
                value = await self._feed.lines()
            except TransitFeedError:
                if self._lines:
                    log.warning("Список маршрутов не обновился, используем прошлый")
                    return self._lines.value
                raise
            self._lines = _Cached(value, now)
            return value

    async def line(self, line_id: str) -> Line | None:
        return next((line for line in await self.lines() if line.id == line_id), None)

    async def line_path(self, line_id: str, direction: Direction) -> LinePath:
        key = (line_id, direction)
        now = self._clock()
        cached = self._paths.get(key)
        if cached and now - cached.at < self._lines_ttl:
            return cached.value
        try:
            value = await self._feed.line_path(line_id, direction)
        except TransitFeedError:
            if cached:
                log.warning("Линия %s %s не обновилась, используем прошлую", line_id, direction)
                return cached.value
            raise
        self._paths[key] = _Cached(value, now)
        return value

    # ------------------------------------------------------------ машины

    @property
    def current(self) -> Snapshot | None:
        return self._snapshot

    async def snapshot(self) -> Snapshot:
        """Снимок для ответа пользователю.

        Если снимок свежий (моложе двух интервалов опроса), отдаём сразу.
        Иначе (сервер давно никто не спрашивал) ждём новый опрос. Если источник
        не ответил, отдаём прошлый снимок, а если его нет, ошибку.
        """
        self.touch()
        snap = self._snapshot
        if snap and self._clock() - snap.fetched_at < 2 * self._interval:
            return snap
        try:
            return await self.refresh()
        except TransitFeedError:
            if self._snapshot:
                return self._snapshot
            raise

    async def refresh(self) -> Snapshot:
        """Один опрос всех маршрутов. Одновременно идёт не больше одного опроса."""
        async with self._refresh_lock:
            started = self._clock()
            # Пока ждали замок, снимок мог обновить другой запрос.
            if (
                self._snapshot
                and self._last_attempt
                and started - self._last_attempt < self._interval
            ):
                return self._snapshot
            self._last_attempt = started
            lines = await self.lines()
            previous = self._snapshot.by_line if self._snapshot else {}
            by_line: dict[str, list[LiveVehicle]] = {line.id: [] for line in lines}
            step = self._feed.max_lines_per_request
            ids = [line.id for line in lines]
            failed = 0
            batches = [ids[i : i + step] for i in range(0, len(ids), step)]
            for batch in batches:
                try:
                    for live in await self._feed.vehicles(batch):
                        by_line.setdefault(live.vehicle.line_id, []).append(live)
                except TransitFeedError as exc:
                    failed += 1
                    log.warning("Пачка маршрутов не пришла: %s", exc)
                    for line_id in batch:
                        by_line[line_id] = previous.get(line_id, [])
            if batches and failed == len(batches):
                raise TransitFeedError("Источник не ответил ни на одну пачку")
            vehicles = [v for group in by_line.values() for v in group]
            self._snapshot = Snapshot(
                vehicles=vehicles, fetched_at=started, complete=failed == 0, by_line=by_line
            )
            return self._snapshot

    async def run_poller(self, tick_s: float = 1.0) -> None:
        """Фоновый опрос: пока есть пользователи, раз в poll_interval_s."""
        while True:
            due = self._last_attempt is None or self._clock() - self._last_attempt >= self._interval
            if self.is_active() and due:
                try:
                    await self.refresh()
                except TransitFeedError as exc:
                    log.warning("Опрос источника не удался: %s", exc)
                except Exception:  # фоновый опрос не должен умирать молча
                    log.exception("Неожиданная ошибка опроса источника")
            await asyncio.sleep(tick_s)
