from datetime import UTC, datetime, timedelta

from app.domain.live import is_fresh, usable_vehicles
from app.domain.models import (
    Accessibility,
    Bounds,
    Direction,
    LatLon,
    LiveVehicle,
    TransportType,
    Vehicle,
    VehicleState,
)

NOW = datetime(2026, 11, 4, 5, 30, tzinfo=UTC)


def make(
    vid: str,
    low_floor: Accessibility = Accessibility.YES,
    age_s: int = 10,
    on_line: bool = True,
    point: LatLon | None = None,
) -> LiveVehicle:
    return LiveVehicle(
        vehicle=Vehicle(
            id=vid,
            line_id="bus-3",
            type=TransportType.BUS,
            number="3",
            direction=Direction.A,
            point=point or LatLon(lat=55.03, lon=82.92),
            low_floor=low_floor,
            position_observed_at=NOW - timedelta(seconds=age_s),
        ),
        state=VehicleState.ON_ROUTE if on_line else VehicleState.PARKED,
        on_line=on_line,
    )


def ids(vehicles: list[Vehicle]) -> list[str]:
    return [v.id for v in vehicles]


def test_fresh_threshold_inclusive() -> None:
    assert is_fresh(NOW - timedelta(seconds=300), NOW, 300)
    assert not is_fresh(NOW - timedelta(seconds=301), NOW, 300)


def test_far_future_position_is_not_fresh() -> None:
    assert is_fresh(NOW + timedelta(seconds=60), NOW, 300)
    assert not is_fresh(NOW + timedelta(minutes=10), NOW, 300)


def test_low_floor_only_keeps_only_yes() -> None:
    fleet = [
        make("yes", Accessibility.YES),
        make("no", Accessibility.NO),
        make("unknown", Accessibility.UNKNOWN),
    ]
    assert ids(usable_vehicles(fleet, NOW, 300, low_floor_only=True)) == ["yes"]
    assert ids(usable_vehicles(fleet, NOW, 300, low_floor_only=False)) == ["yes", "no", "unknown"]


def test_stale_and_off_line_are_hidden_in_both_modes() -> None:
    fleet = [make("ok"), make("old", age_s=600), make("parked", on_line=False)]
    for mode in (True, False):
        assert ids(usable_vehicles(fleet, NOW, 300, low_floor_only=mode)) == ["ok"]


def test_bounds_filter() -> None:
    fleet = [make("center"), make("far", point=LatLon(lat=56.5, lon=84.9))]
    box = Bounds(south_west=LatLon(lat=54.9, lon=82.8), north_east=LatLon(lat=55.1, lon=83.0))
    assert ids(usable_vehicles(fleet, NOW, 300, low_floor_only=True, bounds=box)) == ["center"]
