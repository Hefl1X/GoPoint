import json
import shutil
from datetime import date
from pathlib import Path

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
    assert report["exported_groups"] == 1
    assert report["exported_trips"] == 55
    assert (output / "schedule.gtfs.zip").read_bytes() == (
        reference / "schedule.gtfs.zip"
    ).read_bytes()
    coverage = json.loads((output / "coverage.json").read_bytes())
    assert [row["trip_count"] for row in coverage["coverage"]] == [55, 0, 0]


def test_missing_http_response_is_reported_without_treating_it_as_bad_html(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    shutil.copytree(SAMPLES, archive)
    manifest = archive / "manifest.json"
    data = json.loads(manifest.read_bytes())
    data["requests"] = [row for row in data["requests"] if row["file"] != "tram13-A-day11-all.html"]
    manifest.write_text(json.dumps(data))
    metadata = ScheduleArchive(SAMPLES)
    result = audit(
        ScheduleArchive(archive), metadata, metadata.groups(GROUPS), tmp_path / "output", WINDOW
    )
    assert result["parsed_groups"] == 2
    assert result["exported_trips"] == 55
    errors = result["schedule_errors"]
    assert isinstance(errors, dict)
    assert "архиве отсутствует ответ" in errors["tram-0013-A-11"]
