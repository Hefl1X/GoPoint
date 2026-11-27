"""HTTP-загрузка выбранных расписаний ЦУГАЭТ, отдельная от GPS-опроса."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from app.adapters.tsugaet.feed import DEFAULT_BASE_URL, TRASSES_BATCH
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
CATALOG_URL = f"{DEFAULT_BASE_URL}/listmarsh.php"
_TRACES = "https://map.nskgortrans.ru/trasses.php"
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_PAUSE = 1.5
_MAX_ATTEMPTS = 3
_MAX_RETRY_AFTER = 30


class ScheduleSourceError(RuntimeError):
    """Сбой HTTP или исчерпанный бюджет загрузки."""


class ScheduleBudgetError(ScheduleSourceError):
    """Общий лимит не позволяет продолжить запуск."""


@dataclass(frozen=True)
class MetadataReply:
    url: str
    body: bytes


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


@dataclass(frozen=True)
class ScheduleGroup:
    route: RouteInfo
    direction: Direction
    day_id: str

    @property
    def key(self) -> tuple[str, Direction, str]:
        return self.route.line_id, self.direction, self.day_id


@dataclass(frozen=True)
class ScheduleRequest:
    kind: Literal["stops", "table", "geometry"]
    url: str
    params: dict[str, str]


def group_content_requests(group: ScheduleGroup) -> tuple[ScheduleRequest, ScheduleRequest]:
    params = {
        "m": group.route.marsh,
        "t": str(group.route.type_code),
        "r": group.direction.value,
        "sch": group.day_id,
    }
    return (
        ScheduleRequest("stops", _GRASP, params),
        ScheduleRequest("table", _GRASP, params | {"tv": "mr", "s": "0", "v": "0"}),
    )


def schedule_geometry_requests(
    groups: Sequence[ScheduleGroup],
) -> list[tuple[Direction, list[RouteInfo], ScheduleRequest]]:
    return [
        (
            direction,
            routes,
            ScheduleRequest(
                "geometry", _TRACES, {"r": "".join(route.key(direction.value) for route in routes)}
            ),
        )
        for direction, routes in _geometry_batches(groups)
    ]


def content_requests(groups: Sequence[ScheduleGroup]) -> tuple[ScheduleRequest, ...]:
    selected = sorted(groups, key=lambda group: group.key)
    requests = [request for group in selected for request in group_content_requests(group)]
    requests.extend(request for _, _, request in schedule_geometry_requests(selected))
    return tuple(requests)


def _geometry_batches(
    groups: Sequence[ScheduleGroup],
) -> list[tuple[Direction, list[RouteInfo]]]:
    batches = []
    for direction in Direction:
        routes_by_id = {
            group.route.line_id: group.route for group in groups if group.direction == direction
        }
        routes = [routes_by_id[line_id] for line_id in sorted(routes_by_id)]
        for start in range(0, len(routes), TRASSES_BATCH):
            batches.append((direction, routes[start : start + TRASSES_BATCH]))
    return batches


def planned_requests(groups: Sequence[ScheduleGroup]) -> int:
    """Число запросов без повторов и отдельного запроса каталога."""
    routes = {group.route.line_id for group in groups}
    directions = {(group.route.line_id, group.direction) for group in groups}
    return len(routes) + len(directions) + 2 * len(groups) + len(_geometry_batches(groups))


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
                raise ScheduleBudgetError("Превышен бюджет байтов расписания")
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
                raise ScheduleBudgetError("Исчерпан бюджет запросов расписания")
            if self.payload_bytes >= self._budget.payload_bytes:
                raise ScheduleBudgetError("Исчерпан бюджет байтов расписания")
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

    async def _metadata(self, url: str, params: dict[str, str]) -> MetadataReply:
        body = await self._get(url, params)
        return MetadataReply(str(httpx.URL(url, params=params)), bytes(body))

    async def catalog_metadata(self) -> MetadataReply:
        return await self._metadata(CATALOG_URL, {"r": "true"})

    async def directions_metadata(self, route: RouteInfo) -> MetadataReply:
        return await self._metadata(_GRASP, {"m": route.marsh, "t": str(route.type_code)})

    async def days_metadata(self, route: RouteInfo, direction: Direction) -> MetadataReply:
        return await self._metadata(
            _GRASP, {"m": route.marsh, "t": str(route.type_code), "r": direction.value}
        )

    async def capture_content(self, request: ScheduleRequest) -> MetadataReply:
        return await self._metadata(request.url, request.params)

    async def load(self, route: RouteInfo, direction: Direction, day_id: str) -> ScheduleLoad:
        """Возвращает одну согласованную таблицу и геометрию после приёма всех ответов."""
        (result,) = await self.load_many((ScheduleGroup(route, direction, day_id),))
        return result

    async def load_many(self, groups: Sequence[ScheduleGroup]) -> tuple[ScheduleLoad, ...]:
        """Справочники и геометрия общие для типов дня одного направления."""
        requested = sorted(groups, key=lambda group: group.key)
        if len({group.key for group in requested}) != len(requested):
            raise ValueError("Группа расписания указана дважды")
        metadata: dict[tuple[tuple[str, str], ...], str] = {}
        schedules = [await self._schedule(group, metadata) for group in requested]
        paths: dict[tuple[str, Direction], LinePath] = {}
        for direction, batch in _geometry_batches(requested):
            for line_id, path in (await self._geometry(direction, batch)).items():
                paths[line_id, direction] = path
        return tuple(
            ScheduleLoad(schedule, paths[schedule.route.line_id, schedule.route.direction])
            for schedule in schedules
        )

    async def _cached_grasp(
        self, params: dict[str, str], metadata: dict[tuple[tuple[str, str], ...], str]
    ) -> str:
        key = tuple(sorted(params.items()))
        if key not in metadata:
            metadata[key] = await self._grasp(params)
        return metadata[key]

    async def _schedule(
        self, group: ScheduleGroup, metadata: dict[tuple[tuple[str, str], ...], str]
    ) -> RouteSchedule:
        route, direction = group.route, group.direction
        query = {"m": route.marsh, "t": str(route.type_code)}
        directions = parse_schedule_directions(await self._cached_grasp(query, metadata))
        if direction not in directions:
            raise TsugaetFormatError(f"У {route.line_id} нет направления {direction.value}")

        query["r"] = direction.value
        day = parse_schedule_day(await self._cached_grasp(query, metadata), group.day_id)
        stops_request, table_request = group_content_requests(group)
        stops = parse_schedule_stops(
            await self._grasp(stops_request.params), allow_repeated_positions=True
        )
        html = await self._grasp(table_request.params)
        tables = parse_schedule_tables(html, stops)
        identity = ScheduleRoute(route.type, route.marsh, route.name, direction)
        return RouteSchedule(identity, day, tables)

    async def _geometry(self, direction: Direction, routes: list[RouteInfo]) -> dict[str, LinePath]:
        wanted = [(route.line_id, route.marsh) for route in routes]
        geometry = await self._get(
            _TRACES, {"r": "".join(route.key(direction.value) for route in routes)}
        )
        try:
            data: object = json.loads(geometry)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TsugaetFormatError("trasses: ответ не JSON") from exc
        paths = parse_traces(data, wanted, direction)
        missing = sorted({line_id for line_id, _ in wanted} - paths.keys())
        if missing:
            raise TsugaetFormatError(f"trasses: нет геометрии для {', '.join(missing)}")
        return paths
