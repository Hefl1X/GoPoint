"""Какие остановки брать у точек А и Б и какие поездки хуже пути пешком (без сети)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.access import choose_access_stops, drop_worse_than_walk
from app.domain.models import (
    Accessibility,
    Direction,
    EtaDiagnostics,
    EtaMethod,
    Journey,
    LatLon,
    Line,
    LinePath,
    Place,
    RouteStop,
    Stop,
    TransitLeg,
    TransportType,
    WalkLeg,
)

HERE = LatLon(lat=55.0, lon=83.0)
NOW = datetime(2026, 11, 14, 5, 0, tzinfo=UTC)


def north(metres: float) -> LatLon:
    return LatLon(lat=HERE.lat + metres / 111_000, lon=HERE.lon)


def path(line_id: str, direction: Direction, *stops: tuple[str, float]) -> LinePath:
    return LinePath(
        line_id=line_id,
        direction=direction,
        points=[north(m) for _, m in stops],
        stops=[
            RouteStop(order=i, stop=Stop(id=sid, name=sid, point=north(m)), point_index=i)
            for i, (sid, m) in enumerate(stops)
        ],
    )


def test_hub_keeps_both_directions_beyond_nearest_count() -> None:
    """На узле много близких остановок одного направления: другое направление не теряется."""
    crowded = [path(f"bus-{i}", Direction.A, (f"a{i}", 10 + i)) for i in range(10)]
    other_side = path("bus-0", Direction.B, ("b0", 400))
    chosen = choose_access_stops(
        [*crowded, other_side], HERE, nearest=5, radius_m=1500, max_total=40
    )
    ids = [s.id for s in chosen]
    assert "b0" in ids
    assert ids[:5] == ["a0", "a1", "a2", "a3", "a4"]  # ближайшие первыми


def test_one_stop_per_line_direction_within_radius() -> None:
    line = path("bus-1", Direction.A, ("near", 300), ("far", 900), ("farther", 1200))
    chosen = choose_access_stops([line], HERE, nearest=0, radius_m=1500, max_total=40)
    assert [s.id for s in chosen] == ["near"]


def test_radius_and_cap() -> None:
    lines = [path(f"bus-{i}", Direction.A, (f"s{i}", 100 * (i + 1))) for i in range(30)]
    chosen = choose_access_stops(lines, HERE, nearest=2, radius_m=1000, max_total=8)
    assert len(chosen) == 8
    assert all(s.id in {f"s{i}" for i in range(10)} for s in chosen)


def test_nearest_even_outside_radius() -> None:
    """Точка далеко от всех остановок: лимита расстояния нет, ближайшие всё равно берутся."""
    line = path("bus-1", Direction.A, ("s1", 3000), ("s2", 3500))
    chosen = choose_access_stops([line], HERE, nearest=2, radius_m=1500, max_total=40)
    assert [s.id for s in chosen] == ["s1", "s2"]


def walk_leg(seconds: int) -> WalkLeg:
    return WalkLeg(
        origin=Place(point=HERE),
        destination=Place(point=north(100)),
        distance_m=round(seconds * 0.8),
        duration_s=seconds,
    )


def ride_journey(arrive_min: float, walk_s: tuple[int, int]) -> Journey:
    stop = Stop(id="s", name="s", point=HERE)
    ride = TransitLeg(
        vehicle_id="bus-3-1",
        line=Line(id="bus-3", type=TransportType.BUS, number="3", title=""),
        low_floor=Accessibility.YES,
        board_stop=stop,
        alight_stop=stop,
        wait_s=60,
        stops_count=3,
        stops_away=1,
        toward=None,
        geometry=[],
        depart_at=NOW + timedelta(minutes=3),
        arrive_at=NOW + timedelta(minutes=arrive_min - 1),
        diagnostics=EtaDiagnostics(method=EtaMethod.DISTANCE, position_observed_at=NOW),
    )
    arrive = NOW + timedelta(minutes=arrive_min)
    return Journey(
        legs=[walk_leg(walk_s[0]), ride, walk_leg(walk_s[1])],
        depart_at=NOW,
        arrive_at=arrive,
        duration_s=round(arrive_min * 60),
        transfers=0,
        low_floor_only=True,
    )


def test_ride_arriving_later_than_walking_is_dropped() -> None:
    """Точки через дорогу: поездка по кольцу приезжает позже, чем пешком."""
    walk = walk_leg(5 * 60)
    kept = drop_worse_than_walk([ride_journey(25, (60, 60))], walk, NOW)
    assert kept == []


def test_ride_with_more_walking_than_whole_walk_is_dropped() -> None:
    walk = walk_leg(20 * 60)
    kept = drop_worse_than_walk([ride_journey(18, (11 * 60, 10 * 60))], walk, NOW)
    assert kept == []


def test_faster_ride_with_less_walking_is_kept() -> None:
    walk = walk_leg(30 * 60)
    journey = ride_journey(15, (120, 120))
    assert drop_worse_than_walk([journey], walk, NOW) == [journey]


def test_no_walk_keeps_everything() -> None:
    journey = ride_journey(15, (120, 120))
    assert drop_worse_than_walk([journey], None, NOW) == [journey]
