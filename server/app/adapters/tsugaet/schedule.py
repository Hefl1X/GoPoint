"""HTTP-загрузка выбранных расписаний ЦУГАЭТ, отдельная от GPS-опроса."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.adapters.tsugaet.parse import RouteInfo, TsugaetFormatError, parse_traces
from app.adapters.tsugaet.schedule_parse import (
    parse_schedule_day,
    parse_schedule_directions,
    parse_schedule_stops,
    parse_schedule_tables,
)
from app.domain.models import Direction, LinePath
from app.domain.schedule import RouteSchedule, ScheduleRoute

_GRASP = "https://nskgortrans.ru/components/com_planrasp/helpers/grasp.php"
_TRACES = "https://map.nskgortrans.ru/trasses.php"
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_PAUSE = 1.5
_MAX_ATTEMPTS = 3
_MAX_RETRY_AFTER = 30


class ScheduleSourceError(RuntimeError):
    """Сбой HTTP или исчерпанный бюджет загрузки."""


@dataclass(frozen=True)
class ScheduleBudget:
    requests: int
    payload_bytes: int

    def __post_init__(self) -> None:
        if self.requests <= 0 or self.payload_bytes <= 0:
            raise ValueError("Бюджет запросов и байтов должен быть положительным")


@dataclass(frozen=True)
class ScheduleLoad:
    schedule: RouteSchedule
    path: LinePath


class TsugaetScheduleSource:
    """Один последовательный поток запросов с общим бюджетом на один запуск."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        budget: ScheduleBudget,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._budget = budget
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_finished: float | None = None
        self.requests_made = 0
        self.payload_bytes = 0

    async def _payload(self, response: httpx.Response) -> bytearray:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            self.payload_bytes += len(chunk)
            if self.payload_bytes > self._budget.payload_bytes:
                raise ScheduleSourceError("Превышен бюджет байтов расписания")
            body.extend(chunk)
        return body

    async def _get(self, url: str, params: dict[str, str]) -> bytearray:
        async with self._lock:
            return await self._request(url, params)

    async def _grasp(self, params: dict[str, str]) -> str:
        data = await self._get(_GRASP, params)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TsugaetFormatError("grasp: ответ не в UTF-8") from exc

    async def _request(self, url: str, params: dict[str, str]) -> bytearray:
        pause = _PAUSE
        failure = ""
        for attempt in range(_MAX_ATTEMPTS):
            if self.requests_made >= self._budget.requests:
                raise ScheduleSourceError("Исчерпан бюджет запросов расписания")
            if self.payload_bytes >= self._budget.payload_bytes:
                raise ScheduleSourceError("Исчерпан бюджет байтов расписания")
            if self._last_finished is not None:
                wait = self._last_finished + pause - self._clock()
                if wait > 0:
                    await self._sleep(wait)
            pause = 2.0 ** (attempt + 1)
            try:
                self.requests_made += 1
                async with self._client.stream(
                    "GET", url, params=params, follow_redirects=False
                ) as response:
                    if response.status_code == httpx.codes.OK:
                        return await self._payload(response)
                    failure = f"HTTP {response.status_code}"
                    if response.status_code not in _TRANSIENT_STATUS:
                        break
                    retry_after = response.headers.get("Retry-After")
                    if retry_after is not None:
                        if not retry_after.isascii() or not retry_after.isdecimal():
                            break
                        wait_seconds = int(retry_after[:3])
                        if len(retry_after) > 3 or wait_seconds > _MAX_RETRY_AFTER:
                            break
                        pause = max(pause, wait_seconds)
            except httpx.TransportError as exc:
                failure = type(exc).__name__
            finally:
                self._last_finished = self._clock()
        raise ScheduleSourceError(f"ЦУГАЭТ расписание: {failure}")

    async def load(self, route: RouteInfo, direction: Direction, day_id: str) -> ScheduleLoad:
        """Возвращает одну согласованную таблицу и геометрию после приёма всех ответов."""
        query = {"m": route.marsh, "t": str(route.type_code)}
        directions = parse_schedule_directions(await self._grasp(query))
        if direction not in directions:
            raise TsugaetFormatError(f"У {route.line_id} нет направления {direction.value}")

        query["r"] = direction.value
        day = parse_schedule_day(await self._grasp(query), day_id)
        query["sch"] = day.source_id
        stops = parse_schedule_stops(await self._grasp(query))
        html = await self._grasp(query | {"tv": "mr", "s": "0", "v": "0"})
        tables = parse_schedule_tables(html, stops)
        identity = ScheduleRoute(route.type, route.marsh, route.name, direction)
        geometry = await self._get(_TRACES, {"r": route.key(direction.value)})
        try:
            data: object = json.loads(geometry)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TsugaetFormatError("trasses: ответ не JSON") from exc
        paths = parse_traces(data, [(route.line_id, route.marsh)], direction)
        path = paths.get(route.line_id)
        if path is None:
            raise TsugaetFormatError(f"trasses: линия {route.line_id} отсутствует в ответе")
        return ScheduleLoad(RouteSchedule(identity, day, tables), path)
