import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.domain.gtfs import ServiceWindow
from app.domain.models import Direction
from tools.audit_city_schedule import audit
from tools.build_gtfs import SAMPLES, build_pilot
from tools.collect_schedule import GroupKey, ScheduleArchive

GROUPS: tuple[GroupKey, ...] = (
    ("bus-8", Direction.A, "23"),
    ("minibus-35", Direction.A, "23"),
    ("tram-0013", Direction.A, "11"),
)
WINDOW = ServiceWindow(date(2026, 11, 23), date(2026, 12, 6))


def test_city_audit_reproduces_pilot_and_preserves_diagnostics(tmp_path: Path) -> None:
    metadata = ScheduleArchive(SAMPLES)
    output, reference = tmp_path / "audit", tmp_path / "pilot"
    report = audit(ScheduleArchive(SAMPLES), metadata, metadata.groups(GROUPS), output, WINDOW)
    build_pilot(SAMPLES, reference, WINDOW)

    assert report["parsed_groups"] == 3
    assert report["http_complete"] is True
    assert report["exported_groups"] == 1
    assert report["exported_trips"] == 55
    assert (output / "schedule.gtfs.zip").read_bytes() == (
        reference / "schedule.gtfs.zip"
    ).read_bytes()
    coverage = json.loads((output / "coverage.json").read_bytes())
    assert [row["trip_count"] for row in coverage["coverage"]] == [55, 0, 0]
    assert report["ambiguous_terminal_groups"] == 1
    review = coverage["audit"]["terminal_candidates"]["tram-0013-A-11"]
    assert review["source_id"] == "1838"
    assert [item["platform_id"] for item in review["candidates"]] == ["1910", "1687"]
    assert review["opposite_origin"] is None


@pytest.mark.parametrize("status", [None, 503])
def test_incomplete_http_archive_preserves_report_without_gtfs(
    tmp_path: Path, status: int | None
) -> None:
    archive = tmp_path / "archive"
    shutil.copytree(SAMPLES, archive)
    manifest = archive / "manifest.json"
    data = json.loads(manifest.read_bytes())
    if status is None:
        data["requests"] = [
            row for row in data["requests"] if row["file"] != "tram13-A-day11-all.html"
        ]
    else:
        entry = next(row for row in data["requests"] if row["file"] == "tram13-A-day11-all.html")
        entry["status"] = status
    manifest.write_text(json.dumps(data))
    metadata = ScheduleArchive(SAMPLES)
    output = tmp_path / "output"
    result = audit(ScheduleArchive(archive), metadata, metadata.groups(GROUPS), output, WINDOW)
    assert result["parsed_groups"] == 2
    assert result["http_complete"] is False
    assert result["exported_groups"] == 0
    assert result["exported_trips"] == 0
    assert not (output / "schedule.gtfs.zip").exists()
    coverage = json.loads((output / "coverage.json").read_bytes())
    assert [row["trip_count"] for row in coverage["coverage"]] == [55, 0]
    errors = result["schedule_errors"]
    assert isinstance(errors, dict)
    expected = "архиве отсутствует ответ" if status is None else "HTTP 503"
    assert expected in errors["tram-0013-A-11"]
