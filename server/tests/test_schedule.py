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
