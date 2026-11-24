from collections.abc import Callable
from pathlib import Path

import pytest

from app.adapters.tsugaet.parse import TsugaetFormatError
from app.adapters.tsugaet.schedule_parse import (
    UnsupportedScheduleDayError,
    parse_route_schedule,
    parse_schedule_day,
    parse_schedule_stops,
    parse_schedule_tables,
)
from app.domain.models import Direction, TransportType
from app.domain.schedule import (
    RouteSchedule,
    ScheduleDayKind,
    ScheduleIssueKind,
    ScheduleRoute,
    ScheduleStop,
    reconstruct_trips,
)

SAMPLES = Path(__file__).resolve().parents[3] / "data/tsugaet/samples/audit-2026-11-21"


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def _schedule(
    fixture: str, marsh: str, number: str, type_: TransportType, day_id: str
) -> RouteSchedule:
    return parse_route_schedule(
        _sample(f"{fixture}-A-day{day_id}-all.html"),
        _sample(f"{fixture}-A-stops.xml"),
        _sample(f"{fixture}-A-days.xml"),
        route=ScheduleRoute(type_, marsh, number, Direction.A),
        day_id=day_id,
    )


@pytest.mark.parametrize(
    ("fixture", "marsh", "number", "type_", "day_id", "stop_count", "trip_count", "singles"),
    [
        ("bus8", "8", "8", TransportType.BUS, "23", 38, 55, (1, 2, 3, 4, 38)),
        ("minibus35", "35", "35", TransportType.MINIBUS, "23", 32, 97, (1, 32)),
        ("tram13", "0013", "13", TransportType.TRAM, "11", 25, 184, (1, 25)),
    ],
)
def test_audit_tables(
    fixture: str,
    marsh: str,
    number: str,
    type_: TransportType,
    day_id: str,
    stop_count: int,
    trip_count: int,
    singles: tuple[int, ...],
) -> None:
    schedule = _schedule(fixture, marsh, number, type_, day_id)
    assert schedule.route.marsh == marsh
    assert schedule.day.source_id == day_id
    assert len(schedule.stops) == stop_count
    assert {len(table.departures) for table in schedule.stops} == {trip_count}
    for sequence in singles:
        table = schedule.stops[sequence - 1]
        html = _sample(f"{fixture}-A-day{day_id}-s{sequence:02}.html")
        assert parse_schedule_tables(html, (table.stop,)) == (table,)

    result = reconstruct_trips(schedule)
    assert not result.issues
    assert len(result.trips) == trip_count
    assert {len(trip.calls) for trip in result.trips} == {stop_count}
    assert tuple(tuple(call.time for call in trip.calls) for trip in result.trips) == tuple(
        zip(*(table.departures for table in schedule.stops), strict=True)
    )


def test_tram_13_preserves_trip_specific_running_times() -> None:
    schedule = _schedule("tram13", "0013", "13", TransportType.TRAM, "11")
    trips = reconstruct_trips(schedule).trips
    assert schedule.day.kind is ScheduleDayKind.WEEKDAYS
    assert trips[0].calls[0].time == (5 * 60 + 40) * 60
    assert {trip.calls[-1].time - trip.calls[0].time for trip in trips} == {
        46 * 60,
        47 * 60,
        48 * 60,
        49 * 60,
    }


def _table(name: str, hours: dict[int, tuple[int, ...]]) -> str:
    cells = []
    for index in range(24):
        hour = (index + 5) % 24
        minutes = hours.get(hour, ())
        kind = "td_plan_h" if minutes else "td_plan_n"
        values = "".join(f"<div>{minute:02}</div>" for minute in minutes) or "<span></span>"
        cells.append(f'<td class="{kind}"><span>{hour}</span></td>')
        cells.append(f'<td class="td_plan_m">{values}</td>')
    return (
        f'<h2>остановка {name}</h2><table class="tbl_plan_rasp"><tr>{"".join(cells)}</tr></table>'
    )


def _page(*tables: str) -> str:
    return f"<html><body>{''.join(tables)}</body></html>"


def test_midnight_and_same_name_stops_keep_source_identity() -> None:
    xml = '<stops><stop id="49|1" title="Конечная"/><stop id="50|2" title="Конечная"/></stops>'
    schedule = parse_route_schedule(
        _page(_table("Конечная", {23: (58,), 0: (12,)}), _table("Конечная", {0: (3, 16)})),
        xml,
        _sample("bus8-A-days.xml"),
        route=ScheduleRoute(TransportType.BUS, "8", "8", Direction.A),
        day_id="23",
    )
    assert schedule.day.kind is ScheduleDayKind.DAILY
    result = reconstruct_trips(schedule)
    assert not result.issues
    first, second = result.trips
    assert [(call.stop.source_id, call.stop.sequence, call.time) for call in first.calls] == [
        ("49", 1, 23 * 3600 + 58 * 60),
        ("50", 2, 24 * 3600 + 3 * 60),
    ]
    assert [call.time for call in second.calls] == [24 * 3600 + 12 * 60, 24 * 3600 + 16 * 60]


def test_full_page_confirms_order_of_two_different_stops_with_one_xml_position() -> None:
    xml = (
        "<stops><stop id='49|1' title='Начало'/><stop id='50|2' title='Склады (Первый)'/>"
        "<stop id='51|2' title='Склады (Второй)'/><stop id='52|3' title='Конечная'/></stops>"
    )
    names = ("Начало", "Склады (Первый)", "Склады (Второй)", "Конечная")
    html = _page(*(_table(name, {6: (index,)}) for index, name in enumerate(names)))
    route = ScheduleRoute(TransportType.TROLLEYBUS, "29", "29", Direction.B)
    days = _sample("bus8-A-days.xml")
    with pytest.raises(TsugaetFormatError, match="позиции 3"):
        parse_schedule_stops(xml)

    result = parse_route_schedule(html, xml, days, route=route, day_id="23")
    assert [
        (item.stop.source_id, item.stop.sequence, item.stop.source_sequence)
        for item in result.stops
    ] == [("49", 1, None), ("50", 2, None), ("51", 3, 2), ("52", 4, 3)]
    assert len(reconstruct_trips(result).trips) == 1

    swapped = (names[0], names[2], names[1], names[3])
    invalid = _page(*(_table(name, {6: (index,)}) for index, name in enumerate(swapped)))
    with pytest.raises(TsugaetFormatError, match="название не совпало"):
        parse_route_schedule(invalid, xml, days, route=route, day_id="23")

    with pytest.raises(TsugaetFormatError, match="одноимённые остановки"):
        parse_route_schedule(
            html, xml.replace("Склады (Второй)", "Склады (Первый)"), days, route=route, day_id="23"
        )


def test_empty_table_is_valid_but_an_empty_response_is_an_error() -> None:
    stops = (ScheduleStop("49", 1, "Конечная"),)
    assert parse_schedule_tables(_page(_table("Конечная", {})), stops)[0].departures == ()
    with pytest.raises(TsugaetFormatError, match="отсутствует полное расписание"):
        parse_schedule_tables(_page(), stops)


def test_duplicates_from_source_are_preserved_and_reported() -> None:
    stops = (ScheduleStop("49", 1, "Конечная"),)
    tables = parse_schedule_tables(_page(_table("Конечная", {5: (17, 17)})), stops)
    assert tables[0].departures == (5 * 3600 + 17 * 60,) * 2
    schedule = RouteSchedule(
        ScheduleRoute(TransportType.BUS, "8", "8", Direction.A),
        parse_schedule_day(_sample("bus8-A-days.xml"), "23"),
        tables,
    )
    result = reconstruct_trips(schedule)
    assert not result.trips
    (issue,) = result.issues
    assert issue.kind is ScheduleIssueKind.DUPLICATE_DEPARTURE
    assert issue.departure_index == 1


def test_unknown_day_is_a_coverage_error_and_known_days_are_explicit() -> None:
    assert parse_schedule_day(_sample("tram13-A-days.xml"), "5").kind is ScheduleDayKind.WEEKENDS
    xml = '<schedules><schedule id="23" title="ЛЕТНЕЕ"/></schedules>'
    with pytest.raises(UnsupportedScheduleDayError, match="ЛЕТНЕЕ"):
        parse_schedule_day(xml, "23")
    with pytest.raises(TsugaetFormatError, match="нет типа дня"):
        parse_schedule_day("<schedules/>", "23")


@pytest.mark.parametrize(
    "transform",
    [
        lambda html: html[: len(html) // 2],
        lambda html: html.replace("</div>", "", 1),
        lambda html: html.replace("<div>01</div>", "<span></span>", 1),
        lambda html: html.replace("<div>01</div>", "<div>60</div>", 1),
        lambda html: html.replace("<span>5</span>", "<span>4</span>", 1),
        lambda html: html.replace("остановка Цветной проезд", "остановка Другая", 1),
        lambda html: _page(),
    ],
)
def test_damaged_html_is_not_empty_schedule(transform: Callable[[str], str]) -> None:
    html = transform(_sample("bus8-A-day23-all.html"))
    stops = parse_schedule_stops(_sample("bus8-A-stops.xml"))
    with pytest.raises(TsugaetFormatError):
        parse_schedule_tables(html, stops)


def test_single_stop_page_cannot_be_used_as_complete_schedule() -> None:
    with pytest.raises(TsugaetFormatError, match="число таблиц"):
        parse_schedule_tables(
            _sample("bus8-A-day23-s01.html"), parse_schedule_stops(_sample("bus8-A-stops.xml"))
        )


@pytest.mark.parametrize(
    "xml",
    [
        "<stops><stop",
        "<html/>",
        "<!DOCTYPE stops><stops/>",
        '<stops><stop id="4|2" title="Остановка"/></stops>',
        '<stops><stop id="4|1" title="Остановка"/><stop id="4|1" title="Дубль"/></stops>',
    ],
)
def test_damaged_stop_metadata(xml: str) -> None:
    with pytest.raises(TsugaetFormatError):
        parse_schedule_stops(xml)


def test_same_stop_id_can_recur_at_distinct_positions() -> None:
    stops = parse_schedule_stops(
        '<stops><stop id="49|1" title="Площадка"/><stop id="49|2" title="Площадка"/></stops>'
    )
    assert [(stop.source_id, stop.sequence) for stop in stops] == [("49", 1), ("49", 2)]
