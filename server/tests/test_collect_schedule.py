import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.adapters.tsugaet.parse import RouteInfo
from app.adapters.tsugaet.schedule import (
    ScheduleBudget,
    ScheduleGroup,
    ScheduleSourceError,
    planned_requests,
)
from app.domain.gtfs import ServiceWindow
from app.domain.models import Direction, TransportType
from tools.build_gtfs import SAMPLES
from tools.collect_schedule import GroupKey, prepare_snapshot

GROUPS: tuple[GroupKey, ...] = (
    ("bus-8", Direction.A, "23"),
    ("minibus-35", Direction.A, "23"),
    ("tram-0013", Direction.A, "11"),
)
WINDOW = ServiceWindow(date(2026, 11, 23), date(2026, 12, 6))
BUDGET = ScheduleBudget(14, 600_000)


def test_plan_reuses_directions_day_metadata_and_geometry() -> None:
    route = RouteInfo(TransportType.BUS, "8", "8", "A", "B")
    groups = (
        ScheduleGroup(route, Direction.A, "5"),
        ScheduleGroup(route, Direction.A, "11"),
        ScheduleGroup(route, Direction.B, "11"),
    )
    assert planned_requests(groups) == 11


async def test_three_groups_produce_one_reproducible_archive_snapshot(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    assert await prepare_snapshot(SAMPLES, first, GROUPS, WINDOW, BUDGET)
    assert await prepare_snapshot(SAMPLES, second, GROUPS[::-1], WINDOW, BUDGET)
    for file in ("schedule.gtfs.zip", "coverage.json"):
        assert (first / file).read_bytes() == (second / file).read_bytes()

    report = json.loads((first / "coverage.json").read_bytes())
    assert report["collection"] == {
        "catalog_routes": 104,
        "mode": "archive",
        "payload_bytes": 493_267,
        "planned_requests": 14,
        "requests": 14,
        "selected_groups": 3,
    }
    assert len(report["sources"]) == 14
    assert [group["trip_count"] for group in report["coverage"]] == [55, 0, 0]
    assert report["coverage"][1]["binding_issues"]
    assert report["coverage"][2]["binding_issues"]


async def test_missing_last_group_leaves_previous_snapshot_and_no_partial_output(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "previous"
    assert await prepare_snapshot(SAMPLES, previous, GROUPS, WINDOW, BUDGET)
    before = (previous / "coverage.json").read_bytes()
    missing = (*GROUPS[:2], ("tram-0013", Direction.A, "5"))
    candidate = tmp_path / "candidate"
    with pytest.raises(ValueError, match="В архиве отсутствует ответ"):
        await prepare_snapshot(SAMPLES, candidate, missing, WINDOW, BUDGET)
    assert not candidate.exists()
    assert (previous / "coverage.json").read_bytes() == before


async def test_corrupted_geometry_and_insufficient_request_budget_stop_before_writing(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive"
    shutil.copytree(SAMPLES, archive)
    (archive / "trasses-A.json").write_bytes(b'{"trasses":[]}')
    candidate = tmp_path / "candidate"
    with pytest.raises(ScheduleSourceError, match=r"меньше плана \(14\)"):
        await prepare_snapshot(archive, candidate, GROUPS, WINDOW, ScheduleBudget(13, 600_000))
    assert not candidate.exists()
    with pytest.raises(ValueError, match=r"целостность архивного ответа trasses-A\.json"):
        await prepare_snapshot(archive, candidate, GROUPS, WINDOW, BUDGET)
    assert not candidate.exists()
