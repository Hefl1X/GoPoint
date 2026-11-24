import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.gtfs import ServiceWindow
from app.domain.schedule_snapshot import ScheduleSnapshot
from tools.capture_gps_series import GpsSample, GpsSeries
from tools.replay_gps_series import replay

START = datetime(2026, 11, 24, 11, 36, 38, tzinfo=UTC)
DAY = date(2026, 11, 24)
SNAPSHOT = ScheduleSnapshot("fixture", ServiceWindow(DAY, DAY), ())


def _fixture(archive: Path) -> None:
    marker = {
        "lat": "55.001",
        "lng": "82.901",
        "id_typetr": "1",
        "direction": "A",
        "time_nav": "24.11.26 18:36:18",
        "marsh": "8",
        "graph": "1",
        "title": "8",
        "speed": "14",
        "ramp": "1",
    }
    body = json.dumps({"markers": [marker]}).encode()
    series = GpsSeries(START.isoformat(), (START + timedelta(hours=1)).isoformat(), "duration")
    for sequence in (1, 2, 3):
        started = START + timedelta(seconds=30 * (sequence - 1))
        received = started + timedelta(seconds=1)
        if sequence == 2:
            series.requests.append(
                GpsSample(started.isoformat(), received.isoformat(), 503, 4, "http_status")
            )
            continue
        filename = f"markers-{sequence:03}.json"
        (archive / filename).write_bytes(body)
        series.requests.append(
            GpsSample(
                started.isoformat(),
                received.isoformat(),
                200,
                len(body),
                None,
                filename,
                hashlib.sha256(body).hexdigest(),
            )
        )
    series.write(archive)


def test_replay_distinguishes_repeated_observations_and_http_failures(tmp_path: Path) -> None:
    _fixture(tmp_path)
    result = replay(tmp_path, SNAPSHOT)
    assert result["requests"] == 3 and result["saved"] == 2
    assert result["http_issues"] == {"http_status": 1}
    assert result["min_interval_s"] == 30
    assert result["invalid_samples"] == {}
    metrics = result["directions"]
    assert isinstance(metrics, dict)
    bus = metrics["bus-8:A"]
    assert bus["unique_observations"] == 1
    assert bus["repeated_observations"] == 1
    assert bus["age_s_p50"] == 21
    assert bus["matches"] == {"unmatched": 1}
    assert bus["low_floor_observations"] == 0


def test_replay_rejects_corrupt_http_body_before_parsing(tmp_path: Path) -> None:
    _fixture(tmp_path)
    first = tmp_path / "markers-001.json"
    data = first.read_bytes()
    first.write_bytes(data.replace(b'"14"', b'"17"'))
    with pytest.raises(ValueError, match="контрольная сумма"):
        replay(tmp_path, SNAPSHOT)
