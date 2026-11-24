"""Поездки и времена конкретных рейсов на границе сервиса маршрутов."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.low_floor import TripOccurrence
from app.domain.models import LatLon, Line, Stop, WalkLeg

TimeSource = Literal["scheduled", "realtime"]


@dataclass(frozen=True)
class TripSegment:
    occurrence: TripOccurrence
    board_sequence: int
    alight_sequence: int


@dataclass(frozen=True)
class PlannedRide:
    segment: TripSegment
    line: Line
    board_stop: Stop
    alight_stop: Stop
    depart_at: datetime
    arrive_at: datetime
    time_source: TimeSource
    toward: str | None
    geometry: tuple[LatLon, ...]


@dataclass(frozen=True)
class PlannedWalk:
    leg: WalkLeg
    depart_at: datetime
    arrive_at: datetime


@dataclass(frozen=True)
class PlannedJourney:
    legs: tuple[PlannedWalk | PlannedRide, ...]

    @property
    def rides(self) -> tuple[PlannedRide, ...]:
        return tuple(leg for leg in self.legs if isinstance(leg, PlannedRide))

    @property
    def arrive_at(self) -> datetime:
        return self.legs[-1].arrive_at


@dataclass(frozen=True)
class TripPlan:
    graph_version: str | None
    journeys: tuple[PlannedJourney, ...]
    routing_errors: frozenset[str]


@dataclass(frozen=True)
class TimetabledCall:
    stop_id: str
    arrive_at: datetime | None
    depart_at: datetime | None
    time_source: TimeSource


@dataclass(frozen=True)
class TripTimetable:
    occurrence: TripOccurrence
    # Порядок в OTP совпадает с последовательностью stop_sequence нашего GTFS, начиная с 1.
    calls: tuple[TimetabledCall, ...]
    canceled: bool


@dataclass(frozen=True)
class TripLookup:
    graph_version: str | None
    timetable: TripTimetable | None
