from datetime import date, datetime, time, timedelta

import pytest

from app.adapters.tsugaet.parse import NOVOSIBIRSK
from app.domain.gtfs import ServiceWindow
from app.domain.models import Direction, LiveVehicle, PlannedStop
from app.domain.schedule import ScheduleStop
from app.domain.schedule_snapshot import CallTime, PublishedTrip, ScheduledService, ScheduleSnapshot
from app.domain.stop_binding import StopBinding
from tests.test_linear import LAT0, live, straight_path
from tools.check_gps_passages import check_passages
from tools.replay_gps_series import GpsFrame

DAY = date(2026, 11, 24)
WINDOW = ServiceWindow(DAY, DAY)
MIDNIGHT = datetime.combine(DAY, time(), NOVOSIBIRSK)


def _snapshot(first_s: int) -> ScheduleSnapshot:
    path = straight_path()
    service = ScheduledService(
        "bus-1-A-23",
        path.line_id,
        Direction.A,
        frozenset({DAY.weekday()}),
        WINDOW,
        tuple(
            StopBinding(ScheduleStop(platform.stop.id, index, platform.stop.name), platform)
            for index, platform in enumerate(path.stops, start=1)
        ),
        tuple(path.points),
        tuple(
            PublishedTrip(
                f"trip-{shift}",
                tuple(
                    CallTime(first_s + shift + n * 120, first_s + shift + n * 120) for n in range(4)
                ),
            )
            for shift in (0, 600)
        ),
    )
    return ScheduleSnapshot("fixture", WINDOW, (service,))


def _frame(sequence: int, observation: LiveVehicle) -> GpsFrame:
    return GpsFrame(
        sequence,
        observation.vehicle.position_observed_at + timedelta(seconds=60),
        {observation.vehicle.id: observation},
    )


@pytest.mark.parametrize("next_stop,forward", [("Остановка 2", True), ("Остановка 0", False)])
def test_passage_compares_an_interval_and_checks_rasp_order(next_stop: str, forward: bool) -> None:
    first_s = 6 * 3600
    planned = MIDNIGHT + timedelta(seconds=first_s + 120)
    before = live(
        LAT0 + 0.0025,
        observed=planned - timedelta(seconds=20),
        plan=[
            PlannedStop(stop_name="Остановка 1", at=planned),
            PlannedStop(stop_name=next_stop, at=planned + timedelta(seconds=120)),
        ],
    )
    after = live(LAT0 + 0.0075, observed=planned + timedelta(seconds=30))
    report = check_passages(_snapshot(first_s), "bus-1-A-23", [_frame(1, before), _frame(2, after)])
    rows = report["passages"]
    assert isinstance(rows, list)
    (row,) = rows
    assert row["stop_id"] == "s1"
    assert row["before"] == "2026-11-24T06:01:40+07:00"
    assert row["after"] == "2026-11-24T06:02:30+07:00"
    (planned_trip,) = row["schedule"]
    assert planned_trip["trip_id"] == "trip-0"
    assert planned_trip["inside_interval"] is True
    assert planned_trip["offset_s"] == [-20, 30]
    (rasp,) = row["rasp"]
    assert rasp["forward_order"] is forward
    assert rasp["inside_interval"] is True


def test_conflicting_repeated_time_nav_blocks_adjacent_evidence() -> None:
    start = 6 * 3600
    planned = MIDNIGHT + timedelta(seconds=start + 120)
    at = planned - timedelta(seconds=20)
    first = live(
        LAT0 + 0.0025, observed=at, plan=[PlannedStop(stop_name="Остановка 1", at=planned)]
    )
    conflict = live(LAT0 + 0.007, observed=at)
    after = live(LAT0 + 0.0075, observed=planned + timedelta(seconds=30), plan=first.plan)
    frames = [_frame(1, first), _frame(2, conflict), _frame(3, after)]
    assert check_passages(_snapshot(start), "bus-1-A-23", frames[::2])["passages"]
    assert check_passages(_snapshot(start), "bus-1-A-23", frames)["passages"] == []


def test_passage_after_midnight_uses_the_previous_service_date() -> None:
    first_s = 24 * 3600 - 60
    planned = MIDNIGHT + timedelta(seconds=first_s + 120)
    before = live(
        LAT0 + 0.0025,
        observed=planned - timedelta(seconds=30),
        plan=[
            PlannedStop(stop_name="Остановка 1", at=planned),
        ],
    )
    after = live(LAT0 + 0.0075, observed=planned + timedelta(seconds=30))
    report = check_passages(_snapshot(first_s), "bus-1-A-23", [_frame(1, before), _frame(2, after)])
    rows = report["passages"]
    assert isinstance(rows, list)
    (row,) = rows
    (planned_trip,) = row["schedule"]
    assert planned_trip["planned_at"] == "2026-11-25T00:01:00+07:00"
    assert planned_trip["service_date"] == "2026-11-24"
