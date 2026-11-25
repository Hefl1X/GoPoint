from dataclasses import replace

import pytest

from app.domain.models import Direction, TransportType
from app.domain.schedule import (
    RouteSchedule,
    ScheduleDay,
    ScheduleDayKind,
    ScheduleIssueKind,
    ScheduleRoute,
    ScheduleStop,
    StopSchedule,
    reconstruct_trips,
    reconstruct_variant_trips,
)


def _schedule(*departures: tuple[int, ...], sequences: tuple[int, ...] = ()) -> RouteSchedule:
    positions = sequences or tuple(range(1, len(departures) + 1))
    return RouteSchedule(
        ScheduleRoute(TransportType.BUS, "8", "8", Direction.A),
        ScheduleDay("23", "ЕЖЕДНЕВНО", ScheduleDayKind.DAILY),
        tuple(
            StopSchedule(ScheduleStop("49", sequence, "Площадка"), times)
            for sequence, times in zip(positions, departures, strict=True)
        ),
    )


def test_trip_without_departures_is_an_empty_success() -> None:
    result = reconstruct_trips(_schedule((), ()))
    assert result.trips == ()
    assert result.issues == ()


@pytest.mark.parametrize(
    ("departures", "sequences", "kind", "sequence", "index"),
    [
        (((600, 1200), (660,)), (), ScheduleIssueKind.DEPARTURE_COUNT, 2, None),
        (((), (660,)), (), ScheduleIssueKind.DEPARTURE_COUNT, 2, None),
        (((600,), (660,)), (1, 3), ScheduleIssueKind.STOP_SEQUENCE, 3, None),
        (((600,), (660,)), (1, 1), ScheduleIssueKind.STOP_SEQUENCE, 1, None),
        (((600,), (540,)), (), ScheduleIssueKind.TRIP_ORDER, 2, 0),
        (((600, 1200), (1260, 660)), (), ScheduleIssueKind.DEPARTURE_ORDER, 2, 1),
        (((600,),), (), ScheduleIssueKind.TOO_FEW_STOPS, 1, None),
    ],
)
def test_invalid_group_does_not_produce_partial_trips(
    departures: tuple[tuple[int, ...], ...],
    sequences: tuple[int, ...],
    kind: ScheduleIssueKind,
    sequence: int,
    index: int | None,
) -> None:
    result = reconstruct_trips(_schedule(*departures, sequences=sequences))
    assert not result.trips
    (issue,) = result.issues
    assert (issue.kind, issue.stop.sequence, issue.departure_index) == (kind, sequence, index)


def test_equal_times_at_consecutive_stops_are_preserved() -> None:
    result = reconstruct_trips(_schedule((600,), (600,)))
    assert not result.issues
    (trip,) = result.trips
    assert [(call.stop.sequence, call.time) for call in trip.calls] == [(1, 600), (2, 600)]


def test_unscheduled_prefix_is_omitted_only_from_the_uniquely_short_first_trip() -> None:
    schedule = _schedule((1200, 1800), (1260, 1860), (600, 1320, 1920), (720, 1440, 2040))
    trips = reconstruct_variant_trips(schedule)
    assert [[(call.stop.sequence, call.time) for call in trip.calls] for trip in trips] == [
        [(3, 600), (4, 720)],
        [(1, 1200), (2, 1260), (3, 1320), (4, 1440)],
        [(1, 1800), (2, 1860), (3, 1920), (4, 2040)],
    ]
    assert not reconstruct_trips(schedule).trips


def test_ragged_prefix_is_rejected_when_first_departure_may_serve_it() -> None:
    schedule = _schedule((540, 1800), (600, 1320, 1920), (720, 1440, 2040))
    assert not reconstruct_variant_trips(schedule)


@pytest.mark.parametrize("first_alternative", [660, 900])
def test_two_stops_for_one_position_require_a_unique_call_per_trip(
    first_alternative: int,
) -> None:
    schedule = _schedule((600, 840), (first_alternative,), (900,), (720, 960))
    schedule = replace(
        schedule,
        stops=tuple(
            replace(row, stop=replace(row.stop, source_sequence=source_position))
            for row, source_position in zip(schedule.stops, (1, 2, 2, 3), strict=True)
        ),
    )
    trips = reconstruct_variant_trips(schedule)
    if first_alternative == 660:
        assert [[(call.stop.sequence, call.time) for call in trip.calls] for trip in trips] == [
            [(1, 600), (2, 660), (4, 720)],
            [(1, 840), (3, 900), (4, 960)],
        ]
    else:
        assert not trips
