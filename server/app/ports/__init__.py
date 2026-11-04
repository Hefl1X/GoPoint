"""Порты: интерфейсы внешних сервисов. Реализации лежат в app/adapters/."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

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

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        """Все машины указанных маршрутов (не больше max_lines_per_request), без фильтров."""
        ...


class WalkPlanner(Protocol):
    """Пеший участок между двумя точками по профилю коляски."""

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
