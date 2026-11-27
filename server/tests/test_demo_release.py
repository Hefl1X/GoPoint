import json
from datetime import date
from pathlib import Path

import pytest

from app.domain.gtfs import ServiceWindow
from tools.build_gtfs import SAMPLES, build_pilot
from tools.build_otp_artifacts import prepare_release
from tools.demo_release import configure_demo


@pytest.fixture
def demo(tmp_path: Path) -> tuple[Path, str]:
    osm = tmp_path / "city.pbf"
    osm.write_bytes(b"streets")
    schedule = tmp_path / "schedule"
    build_pilot(SAMPLES, schedule, ServiceWindow(date(2026, 11, 27), date(2026, 12, 20)))

    def build(directory: Path, switches: tuple[str, ...]) -> None:
        name = "streetGraph.obj" if switches == ("--buildStreet",) else "graph.obj"
        (directory / name).write_bytes(b"graph")

    store = tmp_path / "demo"
    release = prepare_release(store, osm, schedule, {}, "sha256:otp", build)
    return store, release.name


def test_demo_connects_both_realtime_feeds_to_the_selected_graph(demo: tuple[Path, str]) -> None:
    store, version = demo
    target = configure_demo(store, version, date(2026, 12, 11))
    config = json.loads(target.read_text())
    assert [(item["feedId"], item["url"]) for item in config["updaters"]] == [
        ("gopoint-all", f"http://server:8000/internal/gtfs-rt/all?version={version}"),
        ("gopoint-low", f"http://server:8000/internal/gtfs-rt/low-floor?version={version}"),
    ]


def test_expired_demo_does_not_start_as_a_healthy_but_unusable_site(demo: tuple[Path, str]) -> None:
    store, version = demo
    with pytest.raises(ValueError, match="Расписание действует"):
        configure_demo(store, version, date(2026, 12, 21))
    assert not (store / "runtime").exists()


def test_missing_transport_graph_does_not_fall_back_to_street_only(demo: tuple[Path, str]) -> None:
    store, version = demo
    (store / "releases" / version / "graph.obj").unlink()
    with pytest.raises(ValueError, match="Нет результата OTP"):
        configure_demo(store, version, date(2026, 12, 11))
    assert not (store / "runtime").exists()
