"""TransitFeed на данных сайта ЦУГАЭТ (map.nskgortrans.ru).

Бережём их сервер: пауза между любыми двумя запросами, не больше 6 маршрутов
в запросе машин, понятный User-Agent без личных данных. Как часто опрашивать,
решает сервис снимка (app/services/live_snapshot.py), а не адаптер.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx

from app.adapters.tsugaet.parse import (
    RouteInfo,
    TsugaetFormatError,
    parse_routes,
    parse_trace,
    parse_vehicles,
)
from app.domain.models import Direction, Line, LinePath, LiveVehicle, TransportType
from app.ports import TransitFeedError, UnknownLineError

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://map.nskgortrans.ru"
# markers.php отдаёт машины не больше чем по 6 маршрутам за запрос (проверено 2026-11-04).
MARKERS_MAX_ROUTES = 6


class TsugaetFeed:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str,
        timeout_s: float = 10.0,
        pause_s: float = 0.5,
        types: frozenset[TransportType] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,
            follow_redirects=False,
        )
        self._pause_s = pause_s
        self._types = types
        self._lock = asyncio.Lock()
        self._last_request = -1e9
        self._routes: dict[str, RouteInfo] = {}
        self.requests_made = 0  # для проверки нагрузки на их сервер

    @property
    def max_lines_per_request(self) -> int:
        return MARKERS_MAX_ROUTES

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get_json(self, path: str, params: dict[str, str]) -> Any:
        # Один запрос за раз и пауза между ними, сколько бы задач ни спрашивало.
        async with self._lock:
            wait = self._last_request + self._pause_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                self.requests_made += 1
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise TransitFeedError(f"{path}: нет ответа ({type(exc).__name__})") from exc
            finally:
                self._last_request = time.monotonic()
        if response.status_code != httpx.codes.OK:
            raise TransitFeedError(f"{path}: HTTP {response.status_code}")
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TransitFeedError(f"{path}: ответ не JSON") from exc

    async def _route_infos(self) -> dict[str, RouteInfo]:
        data = await self._get_json("/listmarsh.php", {"r": "true"})
        try:
            routes = parse_routes(data)
        except TsugaetFormatError as exc:
            raise TransitFeedError(str(exc)) from exc
        if self._types is not None:
            routes = [r for r in routes if r.type in self._types]
        self._routes = {r.line_id: r for r in routes}
        return self._routes

    async def _route(self, line_id: str) -> RouteInfo:
        route = self._routes.get(line_id) or (await self._route_infos()).get(line_id)
        if route is None:
            raise UnknownLineError(line_id)
        return route

    async def lines(self) -> list[Line]:
        return [r.line for r in (await self._route_infos()).values()]

    async def line_path(self, line_id: str, direction: Direction) -> LinePath:
        route = await self._route(line_id)
        data = await self._get_json("/trasses.php", {"r": route.key(direction.value)})
        try:
            return parse_trace(data, line_id, direction)
        except TsugaetFormatError as exc:
            raise TransitFeedError(str(exc)) from exc

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        if len(line_ids) > MARKERS_MAX_ROUTES:
            raise ValueError(f"не больше {MARKERS_MAX_ROUTES} маршрутов за запрос")
        routes = [await self._route(i) for i in line_ids]
        if not routes:
            return []
        data = await self._get_json("/markers.php", {"r": "".join(r.key() for r in routes)})
        try:
            parsed = parse_vehicles(data)
        except TsugaetFormatError as exc:
            raise TransitFeedError(str(exc)) from exc
        if parsed.skipped:
            log.warning("markers: пропущено машин с повреждёнными данными: %d", parsed.skipped)
        return parsed.vehicles
