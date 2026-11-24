"""Формы запросов и ответов API /api/v1. Источник правды для сайта: OpenAPI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from app.domain.low_floor import TripOccurrence
from app.domain.models import (
    Bounds,
    Direction,
    DomainModel,
    JourneySummary,
    LatLon,
    Line,
    NextStop,
    PlaceSuggestion,
    Stop,
    StopArrival,
    TransitLeg,
    Vehicle,
    WalkLeg,
)
from app.domain.trip_plan import JourneySelection, SelectedRide, TimeSource, TripSegment


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


class ScheduledTransitLeg(TransitLeg):
    trip_id: str
    service_date: date
    board_sequence: int = Field(ge=1)
    alight_sequence: int = Field(ge=2)
    time_source: TimeSource


ScheduledLeg = Annotated[WalkLeg | ScheduledTransitLeg, Field(discriminator="kind")]


class ScheduledJourney(JourneySummary):
    legs: list[ScheduledLeg]


class RouteResponse(DomainModel):
    journeys: list[ScheduledJourney] = Field(max_length=3)
    graph_version: str | None
    status: Literal["ok", "no_transit", "walk_better", "transit_unavailable"] = Field(
        description=(
            "no_transit: в проверенном расписании нет подходящих рейсов; "
            "walk_better: предложенный путь пешком быстрее транспортных вариантов; "
            "transit_unavailable: данных для проверки транспорта недостаточно"
        )
    )
    message: str | None = Field(default=None, description="Что сказать человеку, по-русски")
    walk: WalkLeg | None = Field(
        default=None,
        description=(
            "Путь пешком от А до Б: отдельный выбор рядом с транспортом "
            "(если он не намного дольше транспорта); null — не показывать"
        ),
    )
    diagnostics: SnapshotDiagnostics | None


class RideReference(DomainModel):
    trip_id: str = Field(min_length=1, max_length=128)
    service_date: date
    board_sequence: int = Field(ge=1)
    alight_sequence: int = Field(ge=2)

    @model_validator(mode="after")
    def ordered_stops(self) -> RideReference:
        if self.alight_sequence <= self.board_sequence:
            raise ValueError("Высадка должна следовать за посадкой")
        return self

    def segment(self) -> TripSegment:
        return TripSegment(
            TripOccurrence(self.trip_id, self.service_date),
            self.board_sequence,
            self.alight_sequence,
        )


class CheckedLeg(RideReference):
    depart_at: AwareDatetime
    arrive_at: AwareDatetime
    time_source: TimeSource


class SelectedLeg(RideReference):
    walk_before_s: int = Field(ge=0, le=86_400)


class RouteCheckRequest(DomainModel):
    graph_version: str = Field(min_length=1, max_length=128)
    low_floor_only: bool = True
    ready_at: AwareDatetime = Field(description="Время, с которого можно начинать путь от точки А")
    rides: list[SelectedLeg] = Field(min_length=1, max_length=3)

    def selection(self) -> JourneySelection:
        return JourneySelection(
            self.graph_version,
            tuple(SelectedRide(ride.segment(), ride.walk_before_s) for ride in self.rides),
        )


class RouteCheckResponse(DomainModel):
    status: Literal["ok", "changed", "transit_unavailable"]
    rides: list[CheckedLeg] = Field(max_length=3, description="Новые времена выбранной цепочки")


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


class ArrivalsResponse(DomainModel):
    stop: Stop
    arrivals: list[StopArrival] = Field(description="Что подъезжает, по времени прихода")
    diagnostics: SnapshotDiagnostics


class StopsResponse(DomainModel):
    stops: list[Stop] = Field(description="Остановки в области карты, без повторов")


class VehicleDetails(DomainModel):
    vehicle: Vehicle
    toward: str | None = Field(
        default=None, description="Конечная, куда едет машина; null у кольцевых"
    )
    next_stops: list[NextStop] = Field(
        description="Остановки впереди по порядку; пусто, если машина в стороне от линии"
    )
    diagnostics: SnapshotDiagnostics
