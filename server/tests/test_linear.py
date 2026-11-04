"""Положение машины на линии и время прихода на остановки (без сети)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.tsugaet.parse import parse_trace, parse_vehicles
from app.domain.linear import (
    EtaParams,
    build_geometry,
    locate,
    normalize_stop_name,
    stop_calls,
    stops_passed,
)
from app.domain.models import (
    Accessibility,
    Direction,
    EtaMethod,
    LatLon,
    LinePath,
    LiveVehicle,
    PlannedStop,
    RouteStop,
    Stop,
    TransportType,
    Vehicle,
    VehicleState,
)
from tests.conftest import SAMPLES

NOW = datetime(2026, 11, 4, 5, 28, tzinfo=UTC)
PARAMS = EtaParams(min_speed_mps=15 / 3.6, max_speed_mps=40 / 3.6, dwell_s=20)

# Прямая линия на север: 4 остановки через ~556 м (0,005° широты).
LAT0, LON0 = 55.0, 82.9


def straight_path(n_stops: int = 4, step: float = 0.005, line_id: str = "bus-1") -> LinePath:
    points = [LatLon(lat=LAT0 + i * step, lon=LON0) for i in range(n_stops)]
    stops = [
        RouteStop(order=i, stop=Stop(id=f"s{i}", name=f"Остановка {i}", point=p), point_index=i)
        for i, p in enumerate(points)
    ]
    return LinePath(line_id=line_id, direction=Direction.A, points=points, stops=stops)


def live(
    lat: float,
    lon: float = LON0,
    *,
    speed: float | None = 0,
    observed: datetime = NOW,
    plan: list[PlannedStop] | None = None,
    segment_order: int | None = None,
) -> LiveVehicle:
    return LiveVehicle(
        vehicle=Vehicle(
            id="bus-1-1",
            line_id="bus-1",
            type=TransportType.BUS,
            number="1",
            direction=Direction.A,
            point=LatLon(lat=lat, lon=lon),
            speed_kmh=speed,
            low_floor=Accessibility.YES,
            position_observed_at=observed,
        ),
        state=VehicleState.ON_ROUTE,
        on_line=True,
        stops_passed=segment_order,
        plan=plan or [],
    )


# --- геометрия и проекция ---


def test_geometry_lengths() -> None:
    geom = build_geometry(straight_path())
    assert geom.length_m == pytest.approx(3 * 556, rel=0.01)
    assert geom.stop_along_m == sorted(geom.stop_along_m)


def test_locate_between_stops_with_small_offset() -> None:
    geom = build_geometry(straight_path())
    # Между остановками 1 и 2, в 50 м к востоку от линии.
    proj = locate(geom, LatLon(lat=55.0075, lon=82.9008), max_offset_m=200, segment_order=None)
    assert proj is not None
    assert proj.offset_m == pytest.approx(51, abs=3)
    assert stops_passed(geom, proj.along_m) == 2


def test_far_from_line_is_not_used() -> None:
    geom = build_geometry(straight_path())
    assert (
        locate(geom, LatLon(lat=55.0075, lon=82.92), max_offset_m=200, segment_order=None) is None
    )


def test_loop_is_resolved_by_segment_order() -> None:
    # Линия туда и обратно по одной улице: точка в середине подходит дважды.
    out = [LatLon(lat=LAT0 + i * 0.005, lon=LON0) for i in range(4)]
    back = list(reversed(out[:-1]))
    points = out + back
    stops = [
        RouteStop(order=i, stop=Stop(id=f"s{i}", name=f"О{i}", point=p), point_index=i)
        for i, p in enumerate(points)
    ]
    geom = build_geometry(LinePath(line_id="x", direction=Direction.A, points=points, stops=stops))
    middle = LatLon(lat=55.0075, lon=82.9)
    there = locate(geom, middle, max_offset_m=100, segment_order=2)
    back_again = locate(geom, middle, max_offset_m=100, segment_order=5)
    assert there is not None and back_again is not None
    assert stops_passed(geom, there.along_m) == 2
    assert stops_passed(geom, back_again.along_m) == 5


def test_sample_bus3_vehicles_agree_with_segment_order() -> None:
    path = parse_trace(
        json.loads((SAMPLES / "trasses_bus3_A.json").read_text(encoding="utf-8")),
        "bus-3",
        Direction.A,
    )
    geom = build_geometry(path)
    vehicles = parse_vehicles(
        json.loads((SAMPLES / "markers.json").read_text(encoding="utf-8"))
    ).vehicles
    bus3_a = [
        v
        for v in vehicles
        if v.vehicle.line_id == "bus-3" and v.vehicle.direction is Direction.A and v.stops_passed
    ]
    assert bus3_a
    for v in bus3_a:
        proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=v.stops_passed)
        if proj is None:
            continue  # машина в стороне от линии: так и должно быть
        assert v.stops_passed is not None
        assert abs(stops_passed(geom, proj.along_m) - v.stops_passed) <= 1


# --- время прихода ---


def test_eta_by_distance_uses_min_speed_and_dwell() -> None:
    geom = build_geometry(straight_path())
    v = live(55.0, speed=0)  # стоит на первой остановке
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    assert [c.stop.id for c in calls] == ["s1", "s2", "s3"]
    first = (calls[0].arrive_at - NOW).total_seconds()
    assert first == pytest.approx(556 / (15 / 3.6), rel=0.02)
    second = (calls[1].arrive_at - NOW).total_seconds()
    assert second == pytest.approx(2 * 556 / (15 / 3.6) + 20, rel=0.02)
    assert {c.method for c in calls} == {EtaMethod.DISTANCE}


def test_eta_speed_is_capped() -> None:
    geom = build_geometry(straight_path())
    v = live(55.0, speed=120)
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    assert (calls[0].arrive_at - NOW).total_seconds() == pytest.approx(556 / (40 / 3.6), rel=0.02)


def test_planned_time_is_used_when_in_future() -> None:
    geom = build_geometry(straight_path())
    plan = [
        PlannedStop(stop_name="Остановка 1", at=NOW - timedelta(minutes=1)),  # уже прошло
        PlannedStop(stop_name="«Остановка» 2", at=NOW + timedelta(minutes=7)),
    ]
    v = live(55.0, plan=plan)
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    by_id = {c.stop.id: c for c in calls}
    assert by_id["s1"].method is EtaMethod.DISTANCE
    assert by_id["s2"].method is EtaMethod.PLANNED
    assert by_id["s2"].arrive_at == NOW + timedelta(minutes=7)


def test_times_never_go_backwards() -> None:
    geom = build_geometry(straight_path())
    plan = [PlannedStop(stop_name="Остановка 2", at=NOW + timedelta(seconds=30))]
    v = live(55.0, plan=plan)
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    times = [c.arrive_at for c in calls]
    assert times == sorted(times)


def test_vehicle_already_passed_stop() -> None:
    geom = build_geometry(straight_path())
    # Машина за остановкой 1: остановок 0 и 1 впереди нет.
    v = live(55.0055)
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    assert [c.stop.id for c in calls] == ["s2", "s3"]


def test_old_position_means_close_stop_already_passed() -> None:
    geom = build_geometry(straight_path())
    # Отметка 3 минуты назад в 100 м до остановки 1: машина уже проехала её.
    v = live(55.0041, speed=30, observed=NOW - timedelta(minutes=3))
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    assert "s1" not in [c.stop.id for c in calls]


def test_horizon_cuts_far_stops() -> None:
    geom = build_geometry(straight_path(n_stops=4))
    v = live(55.0)
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(minutes=3), params=PARAMS)
    assert [c.stop.id for c in calls] == ["s1"]


def test_ring_route_continues_from_start() -> None:
    # Кольцо: последняя остановка совпадает с первой.
    base = straight_path(n_stops=3)
    first = base.stops[0]
    ring_points = [*base.points, LatLon(lat=LAT0 + 0.005, lon=LON0 + 0.008), base.points[0]]
    ring_stops = [
        *base.stops,
        RouteStop(order=3, stop=first.stop, point_index=len(ring_points) - 1),
    ]
    geom = build_geometry(
        LinePath(line_id="bus-1", direction=Direction.A, points=ring_points, stops=ring_stops)
    )
    v = live(55.0099)  # почти у остановки 2
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(
        geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS, ring=True
    )
    assert [c.stop.id for c in calls] == ["s2", "s0", "s1"]


def test_plan_after_midnight() -> None:
    # Отметка 23:58 по Новосибирску, в плане 00:07: это уже следующие сутки (UTC 17:07).
    observed = datetime(2026, 11, 4, 16, 58, tzinfo=UTC)
    raw = {
        "markers": [
            {
                "title": "1",
                "id_typetr": "1",
                "marsh": "1",
                "graph": "1",
                "direction": "A",
                "lat": "55.0",
                "lng": "82.9",
                "time_nav": "04.11.26 23:58:00",
                "azimuth": "0",
                "speed": "0",
                "segment_order": "1",
                "ramp": "1",
                "rasp": "00:07+Остановка 2|",
            }
        ]
    }
    [vehicle] = parse_vehicles(raw).vehicles
    assert vehicle.vehicle.position_observed_at == observed
    geom = build_geometry(straight_path())
    proj = locate(geom, vehicle.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(
        geom, proj, vehicle, now=observed, horizon=observed + timedelta(hours=1), params=PARAMS
    )
    by_id = {c.stop.id: c for c in calls}
    assert by_id["s2"].arrive_at == datetime(2026, 11, 4, 17, 7, tzinfo=UTC)
    assert by_id["s2"].method is EtaMethod.PLANNED


def test_normalize_stop_name() -> None:
    assert normalize_stop_name("М. «Гагаринская»") == normalize_stop_name('м. "Гагаринская"')
    assert normalize_stop_name("Ул.  Учительская (Учительская)") == "ул учительская учительская"


def test_plan_time_of_next_lap_is_ignored() -> None:
    geom = build_geometry(straight_path())
    # «Остановка 1» в плане через 45 мин: это следующий круг, до неё сейчас ~2 мин.
    plan = [PlannedStop(stop_name="Остановка 1", at=NOW + timedelta(minutes=45))]
    v = live(55.0, plan=plan)
    proj = locate(geom, v.vehicle.point, max_offset_m=200, segment_order=None)
    assert proj is not None
    calls = stop_calls(geom, proj, v, now=NOW, horizon=NOW + timedelta(hours=1), params=PARAMS)
    assert calls[0].method is EtaMethod.DISTANCE
    assert calls[0].arrive_at < NOW + timedelta(minutes=5)
