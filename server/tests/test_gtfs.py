import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.domain.gtfs import GtfsBuildError, ServiceWindow, build_gtfs
from app.domain.models import Direction, LatLon, LinePath, RouteStop, Stop, TransportType
from app.domain.schedule import (
    RouteSchedule,
    ScheduleDay,
    ScheduleDayKind,
    ScheduleIssueKind,
    ScheduleRoute,
    ScheduleStop,
    StopSchedule,
)
from app.domain.stop_binding import (
    BindingIssueKind,
    ReviewedAlignment,
    ReviewedPlatformInsertion,
    alignment_signature,
    bind_stops,
)
from tools.build_gtfs import SAMPLES, build_pilot

WINDOW = ServiceWindow(date(2026, 11, 23), date(2026, 12, 6))


def _source() -> tuple[RouteSchedule, LinePath]:
    route = ScheduleRoute(TransportType.BUS, "8", "8", Direction.A)
    day = ScheduleDay("11", "БУДНИ", ScheduleDayKind.WEEKDAYS)
    schedule = RouteSchedule(
        route,
        day,
        (
            StopSchedule(ScheduleStop("101", 1, "Первый"), (86383,)),
            StopSchedule(ScheduleStop("102", 2, "Второй"), (86541,)),
        ),
    )
    points = [LatLon(lat=55, lon=82.9), LatLon(lat=55.01, lon=82.9)]
    path = LinePath(
        line_id=route.line_id,
        direction=route.direction,
        points=points,
        stops=[
            RouteStop(order=0, stop=Stop(id="201", name="Первый", point=points[0]), point_index=0),
            RouteStop(order=1, stop=Stop(id="202", name="Второй", point=points[1]), point_index=1),
        ],
    )
    return schedule, path


def test_gtfs_uses_source_stop_times_platform_ids_and_explicit_calendar() -> None:
    build = build_gtfs([_source()], WINDOW)
    tables = {table.name: table for table in build.tables}
    trip_id = "bus-8-A-11-086383"
    assert tables["trips.txt"].rows == (("bus-8", "bus-8-A-11", trip_id, "0", "bus-8-A"),)
    assert tables["stop_times.txt"].rows == (
        (trip_id, "23:59:43", "23:59:43", "201", "1"),
        (trip_id, "24:02:21", "24:02:21", "202", "2"),
    )
    assert tables["calendar.txt"].rows == (
        ("bus-8-A-11", "1", "1", "1", "1", "1", "0", "0", "20261123", "20261206"),
    )
    assert "wheelchair_accessible" not in tables["trips.txt"].header
    assert "block_id" not in tables["trips.txt"].header


def test_reviewed_alignment_preserves_original_calls_and_platforms() -> None:
    schedule, path = _source()
    first, last = path.stops
    middle = LatLon(lat=55.005, lon=82.9)
    path = path.model_copy(
        update={
            "points": [first.stop.point, middle, last.stop.point],
            "stops": [
                first,
                RouteStop(
                    order=1, point_index=1, stop=Stop(id="999", name="Техническая", point=middle)
                ),
                RouteStop(
                    order=2, point_index=2, stop=last.stop.model_copy(update={"name": "Вторая"})
                ),
            ],
        }
    )
    assert not build_gtfs([(schedule, path)], WINDOW).tables
    review = ReviewedAlignment(alignment_signature(schedule, path), (0, 2), "Сверена схема")
    result = build_gtfs([(schedule, path)], WINDOW, reviews={"bus-8-A-11": review})
    times = next(table.rows for table in result.tables if table.name == "stop_times.txt")
    assert [row[1:] for row in times] == [
        ("23:59:43", "23:59:43", "201", "1"),
        ("24:02:21", "24:02:21", "202", "2"),
    ]
    approved = result.coverage[0].bindings[-1]
    assert approved.scheduled.name == "Второй" and approved.platform.stop.name == "Вторая"


@pytest.mark.parametrize("orders", [(0, 0), (1, 0), (0, 2), (0,)])
def test_review_rejects_invalid_platform_order(orders: tuple[int, ...]) -> None:
    schedule, path = _source()
    review = ReviewedAlignment(alignment_signature(schedule, path), orders, "Сверена схема")
    result = bind_stops(schedule, path, review)
    assert not result.stops and result.issues[0].kind is BindingIssueKind.INVALID_REVIEW


def test_review_becomes_stale_when_source_stop_changes() -> None:
    schedule, path = _source()
    review = ReviewedAlignment(alignment_signature(schedule, path), (0, 1), "Сверена схема")
    first, last = schedule.stops
    changed = replace(
        schedule, stops=(first, replace(last, stop=replace(last.stop, source_id="changed")))
    )
    result = bind_stops(changed, path, review)
    assert not result.stops and result.issues[0].kind is BindingIssueKind.INVALID_REVIEW


def test_review_with_trip_variants_also_expires_when_departures_change() -> None:
    schedule, path = _source()
    review = ReviewedAlignment(
        alignment_signature(schedule, path, include_departures=True),
        (0, 1),
        "Сверены площадки и времена",
        allow_trip_variants=True,
    )
    first, last = schedule.stops
    changed = replace(schedule, stops=(first, replace(last, departures=(86601,))))
    assert not bind_stops(schedule, path, review).issues
    assert bind_stops(changed, path, review).issues[0].kind is BindingIssueKind.INVALID_REVIEW


def test_review_inserts_verified_platform_without_changing_original_geometry_or_times() -> None:
    schedule, path = _source()
    first, last = schedule.stops
    scheduled = replace(
        schedule,
        stops=(
            first,
            StopSchedule(ScheduleStop("103", 2, "Средняя"), (86400,)),
            replace(last, stop=replace(last.stop, sequence=3)),
        ),
    )
    vertex = LatLon(lat=55.005, lon=82.9)
    path = path.model_copy(
        update={
            "points": [path.points[0], vertex, path.points[1]],
            "stops": [path.stops[0], path.stops[1].model_copy(update={"point_index": 2})],
        }
    )
    point = LatLon(lat=55.0051, lon=82.9)
    insertion = ReviewedPlatformInsertion(2, Stop(id="203", name="Средняя", point=point))
    review = ReviewedAlignment(
        alignment_signature(scheduled, path, include_shape=True), (0, 1, 2), "Проверено", insertion
    )
    weekend = replace(schedule, day=ScheduleDay("5", "ВЫХОДНОЕ", ScheduleDayKind.WEEKENDS))
    build = build_gtfs([(scheduled, path), (weekend, path)], WINDOW, reviews={"bus-8-A-11": review})
    tables = {table.name: table.rows for table in build.tables}
    assert {row[-1] for row in tables["trips.txt"]} == {"bus-8-A-11-reviewed", "bus-8-A"}
    assert [row[1:] for row in tables["stop_times.txt"] if "-11-" in row[0]] == [
        ("23:59:43", "23:59:43", "201", "1"),
        ("24:00:00", "24:00:00", "203", "2"),
        ("24:02:21", "24:02:21", "202", "3"),
    ]
    assert [(b.platform.point_index, b.platform.stop.id) for b in build.coverage[0].bindings] == [
        (0, "201"),
        (2, "203"),
        (3, "202"),
    ]
    assert path.points[1] == vertex and len(path.points) == 3

    changed = path.model_copy(update={"points": [path.points[0], point, path.points[2]]})
    assert bind_stops(scheduled, changed, review).issues[0].kind is BindingIssueKind.INVALID_REVIEW


def test_invalid_calendar_or_no_applicable_service_date() -> None:
    saturday = date(2026, 11, 28)
    with pytest.raises(GtfsBuildError, match="Конец календаря"):
        ServiceWindow(saturday, WINDOW.start)
    with pytest.raises(GtfsBuildError, match="Нет действующих дат"):
        build_gtfs([_source()], ServiceWindow(saturday, saturday))


def test_duplicate_service_id_is_rejected() -> None:
    with pytest.raises(GtfsBuildError, match="Повторная группа"):
        build_gtfs([_source(), _source()], WINDOW)


def test_conflicting_platform_id_is_rejected() -> None:
    schedule, path = _source()
    other = replace(schedule, route=replace(schedule.route, direction=Direction.B))
    points = [*path.points[:1], LatLon(lat=55.02, lon=82.9)]
    platform = path.stops[1].stop.model_copy(update={"point": points[1]})
    stops = [path.stops[0], path.stops[1].model_copy(update={"stop": platform})]
    other_path = path.model_copy(
        update={"direction": Direction.B, "points": points, "stops": stops}
    )
    with pytest.raises(GtfsBuildError, match="одним ID '202'"):
        build_gtfs([(schedule, path), (other, other_path)], WINDOW)


def test_bad_trip_sequence_is_reported_without_writing_invalid_rows() -> None:
    schedule, path = _source()
    backwards = replace(schedule.stops[1], departures=(86300,))
    build = build_gtfs([(replace(schedule, stops=(schedule.stops[0], backwards)), path)], WINDOW)
    assert not build.tables
    (coverage,) = build.coverage
    (issue,) = coverage.schedule_issues
    assert issue.kind is ScheduleIssueKind.TRIP_ORDER


def test_reordered_names_are_not_matched_by_position() -> None:
    schedule, path = _source()
    first, last = (
        replace(table.stop, name=name)
        for table, name in zip(schedule.stops, ("Второй", "Первый"), strict=True)
    )
    swapped = replace(
        schedule,
        stops=(replace(schedule.stops[0], stop=first), replace(schedule.stops[1], stop=last)),
    )
    bindings = bind_stops(swapped, path)
    assert not bindings.stops
    (issue,) = bindings.issues
    assert issue.kind is BindingIssueKind.STOP_ORDER


def test_offline_pilot_is_reproducible_and_reports_geometry_gaps(tmp_path: Path) -> None:
    first_path, second_path = tmp_path / "first", tmp_path / "second"
    build = build_pilot(SAMPLES, first_path, WINDOW)
    build_pilot(SAMPLES, second_path, WINDOW)
    for file in ("schedule.gtfs.zip", "coverage.json"):
        assert (first_path / file).read_bytes() == (second_path / file).read_bytes()
    bus, minibus, tram = build.coverage
    assert (bus.service_id, bus.trip_count, len(bus.bindings)) == ("bus-8-A-23", 55, 38)
    assert bus.bindings[0].scheduled.source_id == "49"
    assert bus.bindings[0].platform.stop.id == "2223"
    assert (minibus.service_id, minibus.trip_count) == ("minibus-35-A-23", 0)
    assert {stop.source_id for issue in minibus.binding_issues for stop in issue.scheduled} == {
        "2087",
        "2016",
    }
    assert {
        platform.stop.id for issue in minibus.binding_issues for platform in issue.platforms
    } == {"514", "2150"}
    assert (tram.service_id, tram.trip_count) == ("tram-0013-A-11", 0)
    (issue,) = tram.binding_issues
    assert issue.kind is BindingIssueKind.AMBIGUOUS_PLATFORM
    assert [platform.stop.id for platform in issue.platforms] == ["1910", "1687"]
    report = json.loads((first_path / "coverage.json").read_bytes())
    assert "trasses-A.json" in report["sources"]
    assert len(report["sources"]) == 11
