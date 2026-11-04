"""Заглушка TransitFeed на сохранённых ответах ЦУГАЭТ (data/tsugaet/samples).

Для тестов и для работы без интернета. Время в образцах: 2026-11-04 около 12:27
по Новосибирску, поэтому в тестах часы ставятся на этот момент.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.adapters.tsugaet.feed import MARKERS_MAX_ROUTES
from app.adapters.tsugaet.parse import parse_routes, parse_trace, parse_traces, parse_vehicles
from app.domain.models import Direction, Line, LinePath, LiveVehicle
from app.ports import TransitFeedError, UnknownLineError

# Какие линии есть в образцах: (маршрут, направление) -> файл.
_TRACE_FILES = {("bus-3", Direction.A): "trasses_bus3_A.json"}
# Пакетные образцы: автобус 3, трамвай 13, маршрутка 24, в порядке ключей запроса.
_BATCH_FILES = {Direction.A: "trasses_batch_A.json", Direction.B: "trasses_batch_B.json"}
_BATCH_LINES = ["bus-3", "tram-0013", "minibus-24"]


class FakeTransitFeed:
    def __init__(self, samples_dir: Path) -> None:
        self._dir = samples_dir
        self._routes = {r.line_id: r for r in parse_routes(self._load("listmarsh.json"))}
        self._vehicles = parse_vehicles(self._load("markers.json")).vehicles
        self.fail = False  # включается в тестах: «источник не отвечает»
        self.vehicle_requests = 0

    @property
    def max_lines_per_request(self) -> int:
        return MARKERS_MAX_ROUTES

    def _load(self, name: str) -> Any:
        return json.loads((self._dir / name).read_text(encoding="utf-8"))

    def _check(self) -> None:
        if self.fail:
            raise TransitFeedError("заглушка: источник недоступен")

    async def lines(self) -> list[Line]:
        self._check()
        return [r.line for r in self._routes.values()]

    async def line_path(self, line_id: str, direction: Direction) -> LinePath:
        self._check()
        if line_id not in self._routes:
            raise UnknownLineError(line_id)
        name = _TRACE_FILES.get((line_id, direction))
        if name is None:
            raise TransitFeedError(f"заглушка: нет образца линии {line_id} {direction}")
        return parse_trace(self._load(name), line_id, direction)

    async def line_paths(
        self, line_ids: Sequence[str], direction: Direction
    ) -> dict[str, LinePath]:
        self._check()
        wanted = [(i, self._routes[i].marsh) for i in _BATCH_LINES]
        paths = parse_traces(self._load(_BATCH_FILES[direction]), wanted, direction)
        return {i: p for i, p in paths.items() if i in set(line_ids)}

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        self._check()
        if len(line_ids) > MARKERS_MAX_ROUTES:
            raise ValueError(f"не больше {MARKERS_MAX_ROUTES} маршрутов за запрос")
        self.vehicle_requests += 1
        wanted = set(line_ids)
        return [v for v in self._vehicles if v.vehicle.line_id in wanted]
