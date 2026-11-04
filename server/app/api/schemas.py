"""Формы запросов и ответов API /api/v1. Источник правды для сайта: OpenAPI."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.domain.models import (
    Bounds,
    Direction,
    DomainModel,
    Eta,
    Journey,
    LatLon,
    Line,
    Place,
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
    places: list[Place]


class RouteRequest(DomainModel):
    origin: LatLon
    destination: LatLon
    low_floor_only: bool = True


class RouteResponse(DomainModel):
    journeys: list[Journey] = Field(max_length=3)


class SnapshotDiagnostics(DomainModel):
    """Служебное: когда получен снимок машин. Интерфейс не показывает."""

    fetched_at: datetime
    complete: bool = Field(description="Источник ответил по всем маршрутам в последний раз")


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
