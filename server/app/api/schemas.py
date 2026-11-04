"""Формы запросов и ответов API /api/v1. Источник правды для сайта: OpenAPI."""

from __future__ import annotations

from pydantic import Field

from app.domain.models import (
    Bounds,
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


class VehiclesResponse(DomainModel):
    vehicles: list[Vehicle]


class LineSummary(DomainModel):
    line: Line
    vehicles_on_line: int = Field(ge=0)


class LinesResponse(DomainModel):
    lines: list[LineSummary]


class LineDirection(DomainModel):
    direction: str
    stops: list[Stop]
    vehicles: list[Vehicle]


class LineDetails(DomainModel):
    line: Line
    directions: list[LineDirection]


class Arrival(DomainModel):
    vehicle: Vehicle
    eta: Eta


class ArrivalsResponse(DomainModel):
    stop: Stop
    arrivals: list[Arrival]


class VehicleDetails(DomainModel):
    vehicle: Vehicle
    next_stops: list[Eta]
