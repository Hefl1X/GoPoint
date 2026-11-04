"""Порты: интерфейсы внешних сервисов. Реализации лежат в app/adapters/."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import Line, Place, Stop, Vehicle, WalkLeg


class TransitFeed(Protocol):
    """Маршруты, линии, остановки и машины на линии (источник: ЦУГАЭТ)."""

    async def lines(self) -> list[Line]: ...

    async def stops(self, line_id: str, direction: str) -> list[Stop]: ...

    async def vehicles(self) -> list[Vehicle]: ...


class WalkPlanner(Protocol):
    """Пеший участок между двумя точками по профилю коляски."""

    async def walk(self, origin: Place, destination: Place) -> WalkLeg: ...


class Geocoder(Protocol):
    """Поиск адресов и мест."""

    async def search(self, query: str, limit: int) -> list[Place]: ...
