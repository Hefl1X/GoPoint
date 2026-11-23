import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.domain.gtfs import ServiceWindow
from tools.build_gtfs import SAMPLES, build_pilot
from tools.build_otp_artifacts import STREET_FILE, ArtifactError, prepare_release, verify_release

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
