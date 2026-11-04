"""Формы запросов и ответов API /api/v1. Источник правды для сайта: OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.domain.models import (
    Bounds,
    Direction,
    DomainModel,
    Eta,
    Journey,
    LatLon,
    Line,
    PlaceSuggestion,
    Stop,
    Vehicle,
)


class Health(DomainModel):
    status: str = "ok"


class Meta(DomainModel):
    app_name: str
    version: str
    city_bounds: Bounds
    refresh_interval_s: int
    low_floor_only_default: bool = True
    stale_seconds: int = Field(description="Служебное: порог свежести. Интерфейс не показывает.")


class SearchResponse(DomainModel):
    places: list[PlaceSuggestion]


class ReverseResponse(DomainModel):
    place: PlaceSuggestion | None = Field(
        description="Адрес или место у точки; null, если рядом ничего не нашлось"
    )


class SnapshotDiagnostics(DomainModel):
    """Служебное: когда получен снимок машин. Интерфейс не показывает."""

    fetched_at: datetime
    complete: bool = Field(description="Источник ответил по всем маршрутам в последний раз")


class WalkRequest(DomainModel):
    origin: LatLon
    destination: LatLon


class RouteRequest(DomainModel):
    origin: LatLon
    destination: LatLon
    low_floor_only: bool = True


class RouteResponse(DomainModel):
    journeys: list[Journey] = Field(max_length=3)
    status: Literal["ok", "no_transit"] = Field(
        description="no_transit: подходящих машин сейчас нет (пешим маршрутом не подменяем)"
    )
    message: str | None = Field(default=None, description="Что сказать человеку, по-русски")
    diagnostics: SnapshotDiagnostics


class RouteCheckRequest(DomainModel):
    origin: LatLon
    destination: LatLon
    low_floor_only: bool = True
    vehicle_id: str = Field(min_length=1, max_length=64, description="Машина первой поездки")
    planned_arrive_at: datetime = Field(description="Когда человек должен был приехать (UTC)")


class RouteCheckResponse(DomainModel):
    status: Literal["ok", "stopped", "late", "gone"] = Field(
        description="ok: всё по плану; stopped: машина стоит; late: опаздывает; gone: пропала"
    )
    stopped_for_s: int | None = None
    current: Journey | None = Field(description="Тот же маршрут с новым временем")
    alternative: Journey | None = Field(description="Предложение: решает человек")
    gain_s: int | None = Field(default=None, description="Насколько раньше по предложению, с")
    diagnostics: SnapshotDiagnostics


class VehiclesResponse(DomainModel):
    vehicles: list[Vehicle]
    diagnostics: SnapshotDiagnostics


class LineSummary(DomainModel):
    line: Line
    vehicles_on_line: int = Field(ge=0)


class LinesResponse(DomainModel):
    lines: list[LineSummary]
    diagnostics: SnapshotDiagnostics


class LineVehicle(DomainModel):
    vehicle: Vehicle
    next_stop_order: int | None = Field(
        description="Номер следующей остановки в списке stops; null, если впереди остановок нет"
    )


class LineDirection(DomainModel):
    direction: Direction
    stops: list[Stop] = Field(description="Остановки по порядку движения")
    path: list[LatLon] = Field(description="Линия маршрута по порядку движения")
    vehicles: list[LineVehicle]


class LineDetails(DomainModel):
    line: Line
    directions: list[LineDirection]
    diagnostics: SnapshotDiagnostics


class Arrival(DomainModel):
    vehicle: Vehicle
    eta: Eta


class ArrivalsResponse(DomainModel):
    stop: Stop
    arrivals: list[Arrival]


class VehicleDetails(DomainModel):
    vehicle: Vehicle
    next_stops: list[Eta]
