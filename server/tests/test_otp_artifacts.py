import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.adapters.otp.release import ArtifactError, verify_release
from app.adapters.otp.schedule import load_release_schedule
from app.domain.gtfs import ServiceWindow, build_gtfs, service_id_for
from app.domain.models import Direction, LatLon, LinePath, RouteStop, Stop, TransportType
from app.domain.schedule import (
    RouteSchedule,
    ScheduleDay,
    ScheduleDayKind,
    ScheduleRoute,
    ScheduleStop,
    StopSchedule,
)
from app.domain.stop_binding import ReviewedAlignment, alignment_signature
from tools.build_gtfs import SAMPLES, build_pilot, write_snapshot
from tools.build_otp_artifacts import STREET_FILE, prepare_release

STREET = ("--buildStreet",)
TRANSIT = ("--loadStreet", "--save")
IMAGE = "sha256:otp"
WINDOW = ServiceWindow(date(2026, 11, 23), date(2026, 12, 6))


class _Builder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, directory: Path, command: tuple[str, ...]) -> None:
        self.calls.append(command)
        if command == STREET:
            assert (directory / "novosibirsk.osm.pbf").is_file()
            (directory / STREET_FILE).write_bytes(b"prepared streets")
        else:
            config = json.loads((directory / "build-config.json").read_bytes())
            assert command == TRANSIT and config["osm"] == []
            assert not (directory / "novosibirsk.osm.pbf").exists()
            assert (directory / STREET_FILE).read_bytes() == b"prepared streets"
            (directory / "graph.obj").write_bytes(b"transport graph")


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path]:
    osm = tmp_path / "city.pbf"
    osm.write_bytes(b"street source")
    schedule = tmp_path / "schedule"
    build_pilot(SAMPLES, schedule, WINDOW)
    return osm, schedule


def _change_gtfs(schedule: Path, target: Path, change: Callable[[str, bytes], bytes]) -> None:
    target.mkdir()
    shutil.copyfile(schedule / "coverage.json", target / "coverage.json")
    with (
        ZipFile(schedule / "schedule.gtfs.zip") as source,
        ZipFile(target / "schedule.gtfs.zip", "w") as result,
    ):
        for name in reversed(source.namelist()):
            result.writestr(name, change(name, source.read(name)))


def test_repacked_schedule_and_fresher_report_skip_both_builds(
    tmp_path: Path, inputs: tuple[Path, Path]
) -> None:
    osm, schedule = inputs
    builder = _Builder()
    store = tmp_path / "store"
    options: dict[str, object] = {"areaVisibility": True}
    release = prepare_release(store, osm, schedule, options, IMAGE, builder)
    repack = tmp_path / "repack"
    _change_gtfs(schedule, repack, lambda _name, data: data)
    report = repack / "coverage.json"
    report.write_text(report.read_text() + "\n", encoding="utf-8")
    assert prepare_release(store, osm, repack, options, IMAGE, builder) == release
    assert builder.calls == [STREET, TRANSIT]
    manifest = verify_release(release, otp_image=IMAGE)
    assert (manifest.service_start, manifest.service_end) == (WINDOW.start, WINDOW.end)
    assert (release / "all.gtfs.zip").read_bytes() == (release / "low.gtfs.zip").read_bytes()
    with ZipFile(release / "all.gtfs.zip") as feed:
        assert release.name.encode() in feed.read("feed_info.txt")

    snapshot = load_release_schedule(release, otp_image=IMAGE)
    assert snapshot.version == manifest.version
    assert snapshot.window == WINDOW
    (service,) = snapshot.services
    assert (service.line_id, service.direction) == ("bus-8", Direction.A)
    assert len(service.trips) == 55
    assert len(service.bindings) == 38
    assert service.operates_on(WINDOW.start) and service.operates_on(WINDOW.end)
    assert not service.operates_on(date(2026, 12, 7))
    first = service.trips[0]
    assert first.trip_id == "bus-8-A-23-021660"
    assert first.stop_times[1].arrival == first.stop_times[1].departure == 21780
    platform = service.bindings[1].platform
    assert platform.stop.id == "645"
    assert platform.stop.point == service.shape[platform.point_index]


def test_short_origin_and_alternative_stop_survive_the_gtfs_release(tmp_path: Path) -> None:
    osm = tmp_path / "city.pbf"
    osm.write_bytes(b"street source")
    day = ScheduleDay("23", "ЕЖЕДНЕВНО", ScheduleDayKind.DAILY)
    sources: list[tuple[RouteSchedule, LinePath | None]] = []
    reviews: dict[str, ReviewedAlignment] = {}
    cases = (
        ("64", (1, 2, 3), ((1200,), (600, 1260), (720, 1380))),
        ("29", (1, 2, 2, 3), ((600, 1200), (660,), (1260,), (720, 1380))),
    )
    for number, source_positions, departures in cases:
        route = ScheduleRoute(TransportType.BUS, number, number, Direction.A)
        points = [LatLon(lat=55.0 + i * 0.001, lon=82.9) for i in range(len(departures))]
        schedule = RouteSchedule(
            route,
            day,
            tuple(
                StopSchedule(ScheduleStop(f"s{pos}", pos, str(pos), raw), times)
                for pos, (raw, times) in enumerate(
                    zip(source_positions, departures, strict=True), 1
                )
            ),
        )
        path = LinePath(
            line_id=route.line_id,
            direction=route.direction,
            points=points,
            stops=[
                RouteStop(
                    order=i,
                    stop=Stop(id=f"{number}-{i + 1}", name=str(i + 1), point=point),
                    point_index=i,
                )
                for i, point in enumerate(points)
            ],
        )
        sources.append((schedule, path))
        reviews[service_id_for(schedule)] = ReviewedAlignment(
            alignment_signature(schedule, path, include_departures=True),
            tuple(range(len(path.stops))),
            "Сверены схемы поездок",
            allow_trip_variants=True,
        )

    assert not build_gtfs(sources, WINDOW).tables
    build = build_gtfs(sources, WINDOW, reviews=reviews)
    assert [row.trip_count for row in build.coverage] == [2, 2]
    assert [len(row.variants) for row in build.coverage] == [2, 2]
    directory = tmp_path / "schedule"
    write_snapshot(
        directory,
        WINDOW,
        build,
        {
            "audit": {
                "http_complete": True,
                "requested_groups": 2,
                "parsed_groups": 2,
                "exported_groups": 2,
            }
        },
    )
    release = prepare_release(tmp_path / "store", osm, directory, {}, IMAGE, _Builder())
    snapshot = load_release_schedule(release)
    assert snapshot.complete_coverage
    assert {
        tuple(binding.platform.stop.id for binding in service.bindings): tuple(
            time.arrival for time in service.trips[0].stop_times
        )
        for service in snapshot.services
    } == {
        ("29-1", "29-2", "29-4"): (600, 660, 720),
        ("29-1", "29-3", "29-4"): (1200, 1260, 1380),
        ("64-1", "64-2", "64-3"): (1200, 1260, 1380),
        ("64-2", "64-3"): (600, 720),
    }


def test_changed_bindings_create_version_and_inconsistent_bindings_block_publication(
    tmp_path: Path, inputs: tuple[Path, Path]
) -> None:
    osm, schedule = inputs
    builder = _Builder()
    store = tmp_path / "store"
    first = prepare_release(store, osm, schedule, {}, IMAGE, builder)
    changed = tmp_path / "new-bindings"
    shutil.copytree(schedule, changed)
    report = changed / "coverage.json"
    data = json.loads(report.read_bytes())
    row = next(row for row in data["coverage"] if row["trip_count"])
    binding = row["bindings"][0]
    binding["scheduled"]["source_id"] = "new-source-id"
    report.write_text(json.dumps(data), encoding="utf-8")

    rebuilt = prepare_release(store, osm, changed, {}, IMAGE, builder)
    assert rebuilt != first
    assert builder.calls == [STREET, TRANSIT, TRANSIT]
    loaded = load_release_schedule(rebuilt)
    assert loaded.services[0].bindings[0].scheduled.source_id == "new-source-id"

    binding["platform"]["stop"]["id"] = "wrong-stop-id"
    report.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ArtifactError, match="расходятся с привязками"):
        prepare_release(store, osm, changed, {}, IMAGE, builder)
    assert set((store / "releases").iterdir()) == {first, rebuilt}
    assert builder.calls == [STREET, TRANSIT, TRANSIT]


def test_time_and_calendar_changes_reuse_streets(tmp_path: Path, inputs: tuple[Path, Path]) -> None:
    osm, schedule = inputs
    builder = _Builder()
    store = tmp_path / "store"
    base = verify_release(prepare_release(store, osm, schedule, {}, IMAGE, builder))
    changed = tmp_path / "time-change"

    def edit(name: str, data: bytes) -> bytes:
        if name == "stop_times.txt":
            before = b",06:03:00,06:03:00,645,2"
            assert before in data
            return data.replace(before, b",06:02:00,06:02:00,645,2", 1)
        return data

    _change_gtfs(schedule, changed, edit)
    shifted = tmp_path / "new-calendar"
    build_pilot(SAMPLES, shifted, ServiceWindow(WINDOW.start, date(2026, 12, 7)))
    manifests = [
        verify_release(prepare_release(store, osm, candidate, {}, IMAGE, builder))
        for candidate in (changed, shifted)
    ]
    assert builder.calls == [STREET, TRANSIT, TRANSIT, TRANSIT]
    assert {manifest.street_key for manifest in [base, *manifests]} == {base.street_key}
    assert len({manifest.version for manifest in [base, *manifests]}) == 3


def test_osm_options_and_image_each_invalidate_streets(
    tmp_path: Path, inputs: tuple[Path, Path]
) -> None:
    osm, schedule = inputs
    builder = _Builder()
    store = tmp_path / "store"
    versions = [prepare_release(store, osm, schedule, {}, IMAGE, builder)]
    osm.write_bytes(b"updated source")
    versions.append(prepare_release(store, osm, schedule, {}, IMAGE, builder))
    options: dict[str, object] = {"areaVisibility": True}
    versions.append(prepare_release(store, osm, schedule, options, IMAGE, builder))
    versions.append(prepare_release(store, osm, schedule, options, "sha256:other", builder))
    assert builder.calls == [STREET, TRANSIT] * 4
    assert len({verify_release(version).street_key for version in versions}) == 4


def test_failure_keeps_previous_release_and_verification_detects_corruption(
    tmp_path: Path, inputs: tuple[Path, Path]
) -> None:
    osm, schedule = inputs
    store = tmp_path / "store"
    good = prepare_release(store, osm, schedule, {}, IMAGE, _Builder())

    def fail(directory: Path, command: tuple[str, ...]) -> None:
        assert command == TRANSIT
        (directory / "graph.obj").write_bytes(b"incomplete")
        raise RuntimeError("interrupted")

    shifted = tmp_path / "new-calendar"
    build_pilot(SAMPLES, shifted, ServiceWindow(WINDOW.start, date(2026, 12, 7)))
    with pytest.raises(RuntimeError, match="interrupted"):
        prepare_release(store, osm, shifted, {}, IMAGE, fail)
    assert list((store / "releases").iterdir()) == [good]
    verify_release(good, otp_image=IMAGE)
    with pytest.raises(ArtifactError, match="образ OTP"):
        verify_release(good, otp_image="sha256:other")
    (good / "graph.obj").write_bytes(b"corrupted")
    with pytest.raises(ArtifactError, match=r"контрольная сумма: graph\.obj"):
        verify_release(good, otp_image=IMAGE)
