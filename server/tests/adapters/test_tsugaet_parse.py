"""Разбор ответов ЦУГАЭТ на настоящих образцах (data/tsugaet/samples). Без сети."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.adapters.tsugaet.parse import (
    TsugaetFormatError,
    is_on_line,
    nearest_moment,
    parse_rasp,
    parse_routes,
    parse_time_nav,
    parse_trace,
    parse_vehicles,
    ramp_to_accessibility,
)
from app.domain.models import Accessibility, Direction, TransportType, VehicleState

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "tsugaet" / "samples"


def load(name: str) -> Any:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- ramp


@pytest.mark.parametrize(
    ("ramp", "expected"),
    [
        ("1", Accessibility.YES),
        ("0", Accessibility.NO),
        ("", Accessibility.UNKNOWN),
        (None, Accessibility.UNKNOWN),
        ("2", Accessibility.UNKNOWN),
        ("yes", Accessibility.UNKNOWN),
        (1, Accessibility.UNKNOWN),  # число вместо строки: формат поменялся, не доверяем
        (True, Accessibility.UNKNOWN),
        (" 1", Accessibility.UNKNOWN),
    ],
)
def test_ramp_strict(ramp: object, expected: Accessibility) -> None:
    assert ramp_to_accessibility(ramp) is expected


def test_missing_ramp_field_gives_unknown() -> None:
    data = load("markers.json")
    for item in data["markers"]:
        item.pop("ramp")
    parsed = parse_vehicles(data)
    assert parsed.vehicles
    assert {v.vehicle.low_floor for v in parsed.vehicles} == {Accessibility.UNKNOWN}


# ---------------------------------------------------------------- время


def test_time_nav_is_novosibirsk_local_converted_to_utc() -> None:
    assert parse_time_nav("04.11.26 12:27:31") == datetime(2026, 11, 4, 5, 27, 31, tzinfo=UTC)


def test_time_nav_just_after_local_midnight_is_previous_utc_day() -> None:
    assert parse_time_nav("01.01.27 03:15:00") == datetime(2026, 12, 31, 20, 15, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["", "2026-11-04 12:00:00", "04.11.26", "32.13.26 25:61:61"])
def test_time_nav_bad_format(bad: str) -> None:
    with pytest.raises(ValueError, match="time_nav"):
        parse_time_nav(bad)


def test_rasp_after_midnight_goes_to_next_day() -> None:
    reference = parse_time_nav("04.11.26 23:55:00")
    state, plan = parse_rasp("23:58+Цирк (Челюскинцев)|00:07+М. «Гагаринская»|", reference)
    assert state is VehicleState.ON_ROUTE
    assert [p.at for p in plan] == [
        datetime(2026, 11, 4, 16, 58, tzinfo=UTC),
        datetime(2026, 11, 4, 17, 7, tzinfo=UTC),  # 00:07 местного 5 ноября
    ]
    assert plan[1].stop_name == "М. «Гагаринская»"


def test_rasp_before_midnight_with_reference_after_midnight_goes_to_previous_day() -> None:
    reference = parse_time_nav("05.11.26 00:05:00")
    moment = nearest_moment(23, 58, reference)
    assert moment == datetime(2026, 11, 4, 16, 58, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ("-", VehicleState.NO_PLAN),
        ("", VehicleState.NO_PLAN),
        ("Отстой", VehicleState.PARKED),
        ("Идет на обед", VehicleState.LUNCH),
        ("Обеденный+перерыв|", VehicleState.LUNCH),
        ("мусор без времени|", VehicleState.NO_PLAN),
    ],
)
def test_rasp_special_values(text: str, state: VehicleState) -> None:
    reference = parse_time_nav("04.11.26 12:00:00")
    assert parse_rasp(text, reference) == (state, [])


# ---------------------------------------------------------------- машины на линии


def test_is_on_line_rules() -> None:
    assert is_on_line(1, "3", VehicleState.ON_ROUTE)
    assert not is_on_line(1, "3", VehicleState.PARKED)
    assert not is_on_line(1, "3", VehicleState.LUNCH)
    assert not is_on_line(1, "3", VehicleState.NO_PLAN)
    assert is_on_line(1, "24", VehicleState.NO_PLAN)  # автобус 24 без плана виден
    assert is_on_line(8, "24", VehicleState.NO_PLAN)  # маршрутки без плана видны
    assert not is_on_line(8, "24", VehicleState.LUNCH)


def test_parse_vehicles_sample() -> None:
    parsed = parse_vehicles(load("markers.json"))
    assert parsed.skipped == 0
    assert len(parsed.vehicles) == 36
    counts = {a: 0 for a in Accessibility}
    for v in parsed.vehicles:
        counts[v.vehicle.low_floor] += 1
    assert counts == {Accessibility.YES: 24, Accessibility.NO: 12, Accessibility.UNKNOWN: 0}
    assert sum(v.on_line for v in parsed.vehicles) == 32  # как в NSKGORTRANS.md


def test_parsed_vehicle_fields() -> None:
    parsed = parse_vehicles(load("markers.json"))
    first = parsed.vehicles[0]
    v = first.vehicle
    assert v.id == "bus-3-1"
    assert v.line_id == "bus-3"
    assert v.type is TransportType.BUS
    assert v.number == "3"
    assert v.direction is Direction.A
    assert v.point.lat == pytest.approx(55.095985412598)
    assert v.point.lon == pytest.approx(82.961730957031)
    assert v.position_observed_at == datetime(2026, 11, 4, 5, 27, 31, tzinfo=UTC)
    assert v.azimuth == 197
    assert v.speed_kmh == 8
    assert v.low_floor is Accessibility.YES
    assert first.stops_passed == 25
    assert first.state is VehicleState.ON_ROUTE
    assert first.plan[0].stop_name == 'ЖК "Северная корона" (Красный пр-кт)'


def test_tram_13_and_bus_13_have_different_ids() -> None:
    parsed = parse_vehicles(load("markers.json"))
    trams = [v for v in parsed.vehicles if v.vehicle.type is TransportType.TRAM]
    assert trams
    assert all(v.vehicle.line_id == "tram-0013" for v in trams)
    assert all(v.vehicle.number == "13" for v in trams)


def test_parked_and_lunch_vehicles_are_not_on_line() -> None:
    parsed = parse_vehicles(load("markers.json"))
    lunch = [v for v in parsed.vehicles if v.state is VehicleState.LUNCH]
    assert lunch
    assert not any(v.on_line for v in lunch)


@pytest.mark.parametrize(
    "damage",
    [
        {"lat": "abc"},
        {"lat": "0", "lng": "0"},
        {"lat": "95"},
        {"time_nav": "вчера"},
        {"direction": "C"},
        {"id_typetr": "5"},
        {"graph": None},
        {"speed": "-"},
    ],
)
def test_one_broken_vehicle_does_not_break_others(damage: dict[str, object]) -> None:
    data = load("markers.json")
    data["markers"][0].update(damage)
    parsed = parse_vehicles(data)
    assert parsed.skipped == 1
    assert len(parsed.vehicles) == 35


def test_not_a_dict_record_is_skipped() -> None:
    data = load("markers.json")
    data["markers"].insert(0, "мусор")
    parsed = parse_vehicles(data)
    assert parsed.skipped == 1
    assert len(parsed.vehicles) == 36


def test_odd_azimuth_becomes_none_instead_of_dropping_vehicle() -> None:
    data = load("markers.json")
    data["markers"][0]["azimuth"] = "999"
    parsed = parse_vehicles(data)
    assert parsed.skipped == 0
    assert parsed.vehicles[0].vehicle.azimuth is None


@pytest.mark.parametrize("data", [None, [], {"markers": None}, {"nope": []}, "html"])
def test_whole_markers_response_broken_is_error(data: object) -> None:
    with pytest.raises(TsugaetFormatError):
        parse_vehicles(data)


def test_empty_markers_is_fine() -> None:
    assert parse_vehicles({"markers": []}).vehicles == []


# ---------------------------------------------------------------- маршруты


def test_parse_routes_sample() -> None:
    routes = parse_routes(load("listmarsh.json"))
    assert len(routes) == 104
    by_type = {t: sum(r.type is t for r in routes) for t in TransportType}
    assert by_type == {
        TransportType.BUS: 55,
        TransportType.TROLLEYBUS: 14,
        TransportType.TRAM: 10,
        TransportType.MINIBUS: 25,
    }
    bus5 = next(r for r in routes if r.type is TransportType.BUS and r.name == "5")
    assert bus5.marsh == "005"
    assert bus5.line_id == "bus-005"
    assert bus5.key("A") == "1-005-A-5|"
    assert bus5.line.title == "Ул. Дюканова — Пос. Северный"


def test_ring_route_title_has_no_dash() -> None:
    data = [{"type": 0, "ways": [{"marsh": "1", "name": "1", "stopb": "Кольцо", "stope": ""}]}]
    (route,) = parse_routes(data)
    assert route.line.title == "Кольцо"


def test_unknown_transport_type_is_skipped() -> None:
    data = copy.deepcopy(load("listmarsh.json"))
    data.append({"type": 42, "ways": [{"marsh": "1", "name": "1", "stopb": "", "stope": ""}]})
    assert len(parse_routes(data)) == 104


@pytest.mark.parametrize("data", [None, {}, [{"ways": []}], [{"type": "0", "ways": []}]])
def test_broken_listmarsh_is_error(data: object) -> None:
    with pytest.raises(TsugaetFormatError):
        parse_routes(data)


# ---------------------------------------------------------------- линии и остановки


def test_parse_trace_sample() -> None:
    path = parse_trace(load("trasses_bus3_A.json"), "bus-3", Direction.A)
    assert path.line_id == "bus-3"
    assert path.direction is Direction.A
    assert len(path.points) == 335
    assert len(path.stops) == 35
    first = path.stops[0]
    assert first.order == 0
    assert first.stop.id == "76"
    assert first.stop.name == 'Вокзал "Новосибирск-Главный"'
    assert first.point_index == 0
    indexes = [s.point_index for s in path.stops]
    assert indexes == sorted(indexes)
    assert all(path.points[s.point_index] == s.stop.point for s in path.stops)


def test_trace_points_named_dash_are_not_stops() -> None:
    data = {
        "trasses": [
            {
                "r": [
                    {
                        "marsh": "3",
                        "u": [
                            {"id": "1", "n": "Остановка", "lat": "55.0", "lng": "82.9"},
                            {"id": "2", "n": "-", "lat": "55.1", "lng": "82.9"},
                            {"lat": "55.2", "lng": "82.9"},
                        ],
                    }
                ]
            }
        ]
    }
    path = parse_trace(data, "bus-3", Direction.B)
    assert [s.stop.id for s in path.stops] == ["1"]
    assert len(path.points) == 3


@pytest.mark.parametrize("data", [None, {"trasses": []}, {"trasses": [{"r": []}]}])
def test_broken_or_empty_trace_is_error(data: object) -> None:
    with pytest.raises(TsugaetFormatError):
        parse_trace(data, "bus-3", Direction.A)


def test_stop_names_have_single_spaces() -> None:
    data = {
        "trasses": [
            {
                "r": [
                    {
                        "marsh": "0013",
                        "u": [
                            {
                                "id": "1",
                                "n": "Гусинобродское  шоссе (т)",
                                "lat": "55.0",
                                "lng": "83.0",
                            },
                            {"lat": "55.1", "lng": "83.0"},
                        ],
                    }
                ]
            }
        ]
    }
    path = parse_trace(data, "tram-0013", Direction.A)
    assert path.stops[0].stop.name == "Гусинобродское шоссе (т)"
