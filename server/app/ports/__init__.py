"""Порты: интерфейсы внешних сервисов. Реализации лежат в app/adapters/."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.low_floor import TripOccurrence
from app.domain.models import (
    Bounds,
    Direction,
    LatLon,
    Line,
    LinePath,
    LiveVehicle,
    Place,
    PlaceSuggestion,
    WalkLeg,
)
from app.domain.realtime import TripDelay
from app.domain.trip_plan import TripLookup, TripPlan


class TransitPlannerUnavailableError(Exception):
    """Планировщик поездок не ответил или вернул непригодный ответ."""


class TransitPlanner(Protocol):
    async def plan(
        self, origin: Place, destination: Place, *, at: datetime, low_floor_only: bool
    ) -> TripPlan: ...

    async def timetable(
        self, occurrence: TripOccurrence, *, low_floor_only: bool
    ) -> TripLookup: ...


class RealtimeEncoder(Protocol):
    def encode(
        self,
        delays: Sequence[TripDelay],
        cancellations: Sequence[TripOccurrence],
        *,
        generated_at: datetime,
    ) -> bytes: ...


class TransitFeedError(Exception):
    """Источник данных о транспорте не ответил или ответил не в том формате."""


class UnknownLineError(LookupError):
    """Такого маршрута в источнике нет."""


class TransitFeed(Protocol):
    """Маршруты, линии, остановки и машины на линии (источник: ЦУГАЭТ)."""

    @property
    def max_lines_per_request(self) -> int:
        """Сколько маршрутов источник отдаёт за один запрос машин."""
        ...

    async def lines(self) -> list[Line]: ...

    async def line_path(self, line_id: str, direction: Direction) -> LinePath: ...

    async def line_paths(
        self, line_ids: Sequence[str], direction: Direction
    ) -> dict[str, LinePath]:
        """Линии нескольких маршрутов одним заходом (адаптер сам делит на запросы).

        Маршруты без линии в этом направлении в ответ не попадают.
        """
        ...

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        """Все машины указанных маршрутов (не больше max_lines_per_request), без фильтров."""
        ...


class WalkPlannerError(Exception):
    """Пеший участок не удалось построить. Подклассы говорят почему."""


class PointNotOnStreetError(WalkPlannerError):
    """Точку не удалось привязать к улице (рядом нет дорог и тротуаров)."""


class NoWalkRouteError(WalkPlannerError):
    """Между точками нет пути по улицам."""


class WalkPlannerUnavailableError(WalkPlannerError):
    """Сервис пеших маршрутов не ответил вовремя или ответил ошибкой."""


class WalkPlanner(Protocol):
    """Пеший участок между двумя точками по улицам и тротуарам (обычный пешеход)."""

    async def walk(self, origin: Place, destination: Place) -> WalkLeg: ...


class GeocoderError(Exception):
    """Сервис поиска адресов не ответил или ответил не в том формате."""


class Geocoder(Protocol):
    """Поиск адресов и мест (источник: OpenStreetMap через Photon)."""

    async def search(
        self, query: str, *, limit: int, bounds: Bounds, near: LatLon
    ) -> list[PlaceSuggestion]:
        """Подсказки по тексту в пределах bounds; ближе к near выше. Порядок: лучшие первыми."""
        ...

    async def reverse(self, point: LatLon) -> PlaceSuggestion | None:
        """Ближайший адрес или место у точки; None, если рядом ничего нет."""
        ...
