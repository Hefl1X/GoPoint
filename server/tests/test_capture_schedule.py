import json
from pathlib import Path

import httpx

from app.adapters.tsugaet.schedule import ScheduleBudget, TsugaetScheduleSource
from tools.capture_schedule import capture
from tools.inventory_schedule import inventory


async def _skip_wait(_delay: float) -> None:
    pass


def _metadata(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/listmarsh.php":
        return httpx.Response(
            200,
            json=[{"type": 0, "ways": [{"marsh": "8", "name": "8", "stopb": "A", "stope": "B"}]}],
        )
    if request.url.params.get("r") == "A":
        return httpx.Response(
            200, content=b"<schedules><schedule id='23' title='Daily'/></schedules>"
        )
    return httpx.Response(200, content=b"<routes><route id='A' title='A-B'/></routes>")


async def test_capture_fetches_only_new_content_and_reports_budget(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    async with httpx.AsyncClient(transport=httpx.MockTransport(_metadata)) as client:
        await inventory(
            TsugaetScheduleSource(client, ScheduleBudget(3, 1000), sleep=_skip_wait), metadata
        )

    calls: list[httpx.URL] = []

    def content(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, content=b"fixture")

    output = tmp_path / "capture"
    async with httpx.AsyncClient(transport=httpx.MockTransport(content)) as client:
        report = await capture(
            TsugaetScheduleSource(client, ScheduleBudget(3, 30), sleep=_skip_wait), metadata, output
        )
    assert report["complete"] is True
    assert report["reused_metadata"] == 3
    assert report["network_requests"] == 3
    assert [url.params.get("s") for url in calls] == [None, "0", None]
    assert calls[0].params.get("sch") == "23"
    assert calls[2].path == "/trasses.php"
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert len(manifest["requests"]) == 6

    calls.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(content)) as client:
        partial = await capture(
            TsugaetScheduleSource(client, ScheduleBudget(1, 30), sleep=_skip_wait),
            metadata,
            tmp_path / "partial",
        )
    assert partial["complete"] is False
    assert partial["network_requests"] == len(calls) == 1
    assert partial["network_responses"] == 1
