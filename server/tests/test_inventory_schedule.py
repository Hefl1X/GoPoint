import json
from pathlib import Path

import httpx
import pytest

from app.adapters.tsugaet.schedule import ScheduleBudget, TsugaetScheduleSource
from tools.collect_schedule import ScheduleArchive
from tools.inventory_schedule import inventory, main

CATALOG = [{"type": 0, "ways": [{"marsh": "8", "name": "8", "stopb": "A", "stope": "B"}]}]


async def _skip(_seconds: float) -> None:
    pass


def _request(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    if request.url.path == "/listmarsh.php":
        assert params == {"r": "true"}
        return httpx.Response(200, json=CATALOG)
    assert request.url.path.endswith("/grasp.php")
    assert params.pop("m") == "8"
    assert params.pop("t") == "1"
    if not params:
        content = '<routes><route id="A" title="A–B"/><route id="B" title="B–A"/></routes>'
    elif params == {"r": "A"}:
        content = '<schedules><schedule id="23" title="ЕЖЕДНЕВНО"/></schedules>'
    else:
        assert params == {"r": "B"}
        content = '<schedules><schedule id="99" title="ПРАЗДНИК"/></schedules>'
    return httpx.Response(200, content=content.encode("utf-8"))


async def test_inventories_and_replays_only_catalog_and_metadata(tmp_path: Path) -> None:
    archive, replay = tmp_path / "archive", tmp_path / "replay"
    async with httpx.AsyncClient(transport=httpx.MockTransport(_request)) as client:
        first = await inventory(
            TsugaetScheduleSource(client, ScheduleBudget(4, 10_000), sleep=_skip), archive
        )
    transport = httpx.MockTransport(ScheduleArchive(archive).response)
    async with httpx.AsyncClient(transport=transport) as client:
        second = await inventory(
            TsugaetScheduleSource(client, ScheduleBudget(4, 10_000), sleep=_skip), replay
        )
    assert first == second
    assert first["complete"] is True
    assert first["groups"] == 2
    assert first["supported_groups"] == 1
    assert first["full_requests_without_retries"] == 10
    assert first["requests"] == 4
    assert (archive / "manifest.json").read_bytes() == (replay / "manifest.json").read_bytes()


async def test_budget_exhaustion_keeps_partial_archive(tmp_path: Path) -> None:
    output = tmp_path / "partial"
    async with httpx.AsyncClient(transport=httpx.MockTransport(_request)) as client:
        report = await inventory(
            TsugaetScheduleSource(client, ScheduleBudget(2, 10_000), sleep=_skip), output
        )
    assert report["complete"] is False
    assert report["full_requests_without_retries"] is None
    assert report["requests"] == 2
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert len(manifest["requests"]) == 2


def test_cli_refuses_more_than_320_attempts(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--capture", "--max-requests", "321", "--output", str(tmp_path / "archive")])
    assert not list(tmp_path.iterdir())
