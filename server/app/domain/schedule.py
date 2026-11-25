"""Плановые времена в секундах от полуночи дня обслуживания в Новосибирске."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby, pairwise

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


def reconstruct_trips(
    schedule: RouteSchedule, *, allow_variants: bool = False
) -> TripReconstruction:
    """Кандидаты по порядку отправлений после проверок, без гарантии отсутствия обгонов."""
    stops = schedule.stops
    if not stops:
        return TripReconstruction()
    issues = _table_issues(stops)
    if issues:
        variants = reconstruct_variant_trips(schedule) if allow_variants else ()
        return TripReconstruction(trips=variants) if variants else TripReconstruction(issues=issues)
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


def _short_origin(
    stops: tuple[StopSchedule, ...], trip_count: int
) -> tuple[tuple[ScheduledCall, ...], ...]:
    first_full = next(i for i, row in enumerate(stops) if len(row.departures) == trip_count)
    short_start = stops[first_full:]
    if not first_full or len(short_start) < 2:
        return ()
    first_departure = short_start[0].departures[0]
    if any(
        len(row.departures) != trip_count - 1 or row.departures[0] <= first_departure
        for row in stops[:first_full]
    ) or any(len(row.departures) != trip_count for row in short_start):
        return ()
    # Ни одно опубликованное время в начале не может относиться к первому рейсу.
    return (
        tuple(ScheduledCall(row.stop, row.departures[0]) for row in short_start),
        *(
            tuple(
                ScheduledCall(row.stop, row.departures[i - int(j < first_full)])
                for j, row in enumerate(stops)
            )
            for i in range(1, trip_count)
        ),
    )


def _alternative_position(
    positions: tuple[tuple[StopSchedule, ...], ...], position: int, trip_count: int
) -> tuple[tuple[ScheduledCall, ...], ...]:
    if not 0 < position < len(positions) - 1:
        return ()
    fixed = tuple(rows[0] for rows in positions if len(rows) == 1)
    alternatives = sorted(
        (ScheduledCall(row.stop, time) for row in positions[position] for time in row.departures),
        key=lambda call: call.time,
    )
    if len(alternatives) != trip_count or any(len(row.departures) != trip_count for row in fixed):
        return ()
    times = tuple(call.time for call in alternatives)
    trips: list[tuple[ScheduledCall, ...]] = []
    for i in range(trip_count):
        lower, upper = fixed[position - 1].departures[i], fixed[position].departures[i]
        if (bisect_left(times, lower), bisect_right(times, upper)) != (i, i + 1):
            return ()
        calls = tuple(ScheduledCall(row.stop, row.departures[i]) for row in fixed)
        trips.append((*calls[:position], alternatives[i], *calls[position:]))
    return tuple(trips)


def reconstruct_variant_trips(schedule: RouteSchedule) -> tuple[ScheduledTrip, ...]:
    """Однозначные варианты по исходным временам для сверки перед привязкой площадок."""
    stops = schedule.stops
    if not stops or any(
        issue.kind is not ScheduleIssueKind.DEPARTURE_COUNT for issue in _table_issues(stops)
    ):
        return ()
    trip_count = max(len(row.departures) for row in stops)
    if trip_count < 2:
        return ()
    positions = tuple(
        tuple(rows)
        for _, rows in groupby(stops, key=lambda row: row.stop.source_sequence or row.stop.sequence)
    )
    alternatives = [i for i, rows in enumerate(positions) if len(rows) > 1]
    match alternatives:
        case []:
            calls = _short_origin(stops, trip_count)
        case [position]:
            calls = _alternative_position(positions, position, trip_count)
        case _:
            return ()
    if any(last.time < first.time for trip in calls for first, last in pairwise(trip)):
        return ()
    return tuple(ScheduledTrip(trip) for trip in calls)
