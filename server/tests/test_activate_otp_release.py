from datetime import date
from pathlib import Path

import pytest

from app.domain.gtfs import ServiceWindow
from tools.activate_otp_release import ActivationError, ReleaseState, switch_release
from tools.build_gtfs import SAMPLES, build_pilot
from tools.build_otp_artifacts import STREET_FILE, ArtifactError, ArtifactManifest, prepare_release

IMAGE = "fixture-image"


class _Runtime:
    def __init__(self) -> None:
        self.loaded: str | None = None
        self.loads: list[str] = []
        self.refuse: set[str] = set()

    def load(self, directory: Path, manifest: ArtifactManifest) -> None:
        assert directory.name == manifest.version
        self.loaded = manifest.version
        self.loads.append(manifest.version)
        if manifest.version in self.refuse:
            raise ActivationError("Разошлись версии фидов")

    def stop(self) -> None:
        self.loaded = None


@pytest.fixture
def releases(tmp_path: Path) -> tuple[Path, str, str]:
    osm = tmp_path / "city.pbf"
    osm.write_bytes(b"city")
    store = tmp_path / "store"

    def build(directory: Path, flags: tuple[str, ...]) -> None:
        name = STREET_FILE if flags == ("--buildStreet",) else "graph.obj"
        (directory / name).write_bytes(b"test graph")

    versions = []
    for day in (6, 7):
        snapshot = tmp_path / f"snapshot-{day}"
        build_pilot(SAMPLES, snapshot, ServiceWindow(date(2026, 11, 23), date(2026, 12, day)))
        versions.append(prepare_release(store, osm, snapshot, {}, IMAGE, build).name)
    return store, versions[0], versions[1]


def _state(store: Path) -> ReleaseState:
    return ReleaseState.model_validate_json((store / "active.json").read_bytes())


def test_restarts_from_saved_state_and_rolls_back_the_whole_release(
    releases: tuple[Path, str, str],
) -> None:
    store, first, second = releases
    runtime = _Runtime()
    assert switch_release(store, runtime, IMAGE, "activate", first) == ReleaseState(current=first)
    assert switch_release(store, runtime, IMAGE, "activate", second) == ReleaseState(
        current=second, previous=first
    )
    switch_release(store, runtime, IMAGE, "stop")
    assert runtime.loaded is None
    recovered = _Runtime()
    assert switch_release(store, recovered, IMAGE, "restart").current == second
    assert recovered.loaded == second
    state = switch_release(store, recovered, IMAGE, "rollback")
    assert recovered.loaded == first
    assert _state(store) == state == ReleaseState(current=first, previous=second)


def test_bad_checksum_leaves_running_version_untouched(releases: tuple[Path, str, str]) -> None:
    store, first, second = releases
    runtime = _Runtime()
    switch_release(store, runtime, IMAGE, "activate", first)
    (store / "releases" / second / "graph.obj").write_bytes(b"broken")
    with pytest.raises(ArtifactError, match="контрольная сумма"):
        switch_release(store, runtime, IMAGE, "activate", second)
    assert runtime.loads == [first]
    assert _state(store) == ReleaseState(current=first)


def test_runtime_rejection_restores_previous_version(releases: tuple[Path, str, str]) -> None:
    store, first, second = releases
    runtime = _Runtime()
    switch_release(store, runtime, IMAGE, "activate", first)
    runtime.refuse.add(second)
    with pytest.raises(ActivationError, match="Разошлись версии"):
        switch_release(store, runtime, IMAGE, "activate", second)
    assert runtime.loads == [first, second, first]
    assert _state(store) == ReleaseState(current=first)


def test_manual_rollback_can_replace_a_damaged_current_release(
    releases: tuple[Path, str, str],
) -> None:
    store, first, second = releases
    runtime = _Runtime()
    switch_release(store, runtime, IMAGE, "activate", first)
    switch_release(store, runtime, IMAGE, "activate", second)
    (store / "releases" / second / "graph.obj").write_bytes(b"broken")

    assert switch_release(store, runtime, IMAGE, "rollback") == ReleaseState(
        current=first, previous=second
    )
    assert runtime.loaded == first


def test_failed_restore_leaves_journal_for_next_start(releases: tuple[Path, str, str]) -> None:
    store, first, second = releases
    runtime = _Runtime()
    switch_release(store, runtime, IMAGE, "activate", first)
    runtime.refuse.update((first, second))
    with pytest.raises(ActivationError):
        switch_release(store, runtime, IMAGE, "activate", second)
    assert _state(store) == ReleaseState(current=first, pending=second)

    recovered = _Runtime()
    assert switch_release(store, recovered, IMAGE, "restart") == ReleaseState(current=first)
    assert recovered.loads == [first]
    assert _state(store) == ReleaseState(current=first)
