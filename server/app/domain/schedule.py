"""Плановые времена в секундах от полуночи дня обслуживания в Новосибирске."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from app.domain.models import Direction, TransportType


class ScheduleDayKind(StrEnum):
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"


@dataclass(frozen=True)
class ScheduleDay:
    source_id: str
    title: str
    kind: ScheduleDayKind


@dataclass(frozen=True)
class ScheduleRoute:
    type: TransportType
    marsh: str
    number: str
    direction: Direction

    @property
    def line_id(self) -> str:
        return f"{self.type.value}-{self.marsh}"


@dataclass(frozen=True)
class ScheduleStop:
    """ID расписания и позиция в направлении, независимо от ID площадки на линии."""

    source_id: str
    sequence: int
    name: str
    source_sequence: int | None = None  # номер в XML, если он расходится с порядком таблиц


@dataclass(frozen=True)
class StopSchedule:
    stop: ScheduleStop
    departures: tuple[int, ...]


@dataclass(frozen=True)
class RouteSchedule:
    route: ScheduleRoute
    day: ScheduleDay
    stops: tuple[StopSchedule, ...]


@dataclass(frozen=True)
class ScheduledCall:
    stop: ScheduleStop
    time: int


@dataclass(frozen=True)
class ScheduledTrip:
    calls: tuple[ScheduledCall, ...]


class ScheduleIssueKind(StrEnum):
    STOP_SEQUENCE = "stop_sequence"
    DEPARTURE_COUNT = "departure_count"
    DUPLICATE_DEPARTURE = "duplicate_departure"
    DEPARTURE_ORDER = "departure_order"
    TRIP_ORDER = "trip_order"
    TOO_FEW_STOPS = "too_few_stops"


@dataclass(frozen=True)
class ScheduleIssue:
    kind: ScheduleIssueKind
    stop: ScheduleStop
    departure_index: int | None = None  # позиция в исходной таблице, с нуля


@dataclass(frozen=True)
class TripReconstruction:
    trips: tuple[ScheduledTrip, ...] = ()
    issues: tuple[ScheduleIssue, ...] = ()


def _table_issues(stops: tuple[StopSchedule, ...]) -> tuple[ScheduleIssue, ...]:
    issues: list[ScheduleIssue] = []
    expected_count = len(stops[0].departures)
    for sequence, table in enumerate(stops, start=1):
        if table.stop.sequence != sequence:
            issues.append(ScheduleIssue(ScheduleIssueKind.STOP_SEQUENCE, table.stop))
        if len(table.departures) != expected_count:
            issues.append(ScheduleIssue(ScheduleIssueKind.DEPARTURE_COUNT, table.stop))

        seen: set[int] = set()
        previous = 0
        for index, time in enumerate(table.departures):
            if time in seen:
                issues.append(
                    ScheduleIssue(ScheduleIssueKind.DUPLICATE_DEPARTURE, table.stop, index)
                )
            if time < previous:
                issues.append(ScheduleIssue(ScheduleIssueKind.DEPARTURE_ORDER, table.stop, index))
            seen.add(time)
            previous = time
    return tuple(issues)


def reconstruct_trips(schedule: RouteSchedule) -> TripReconstruction:
    """Кандидаты по порядку отправлений после проверок, без гарантии отсутствия обгонов."""
    stops = schedule.stops
    if not stops:
        return TripReconstruction()
    issues = _table_issues(stops)
    if issues:
        return TripReconstruction(issues=issues)
    if not stops[0].departures:
        return TripReconstruction()
    if len(stops) == 1:
        return TripReconstruction(
            issues=(ScheduleIssue(ScheduleIssueKind.TOO_FEW_STOPS, stops[0].stop),)
        )

    trips: list[ScheduledTrip] = []
    timing_issues: list[ScheduleIssue] = []
    for index, times in enumerate(zip(*(table.departures for table in stops), strict=True)):
        calls = tuple(
            ScheduledCall(table.stop, time) for table, time in zip(stops, times, strict=True)
        )
        for previous, current in pairwise(calls):
            if current.time < previous.time:
                timing_issues.append(
                    ScheduleIssue(ScheduleIssueKind.TRIP_ORDER, current.stop, index)
                )
        trips.append(ScheduledTrip(calls))

    if timing_issues:
        return TripReconstruction(issues=tuple(timing_issues))
    return TripReconstruction(trips=tuple(trips))
