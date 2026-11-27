import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.adapters.tsugaet.gps_capture import capture_markers
from tools import capture_gps_series


class _Stream(httpx.AsyncByteStream):
    def __init__(self, *parts: bytes) -> None:
        self.parts = parts
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            self.read += 1
            yield part


async def test_capture_guards_known_length_and_stops_stream_at_budget() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"Content-Length": "6"} if request.url.path == "/known" else {}
        return httpx.Response(200, headers=headers, stream=known if headers else unknown)

    known, unknown = _Stream(b"abcdef"), _Stream(b"abc", b"def", b"ghi")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        short = await capture_markers(
            client, httpx.URL("https://example.test/known"), max_bytes=5, timeout_s=1
        )
        streamed = await capture_markers(
            client, httpx.URL("https://example.test/unknown"), max_bytes=5, timeout_s=1
        )
    assert short.issue == streamed.issue == "byte_limit"
    assert short.body == b"" and known.read == 0
    assert streamed.body == b"abcde" and unknown.read == 2


async def test_gps_series_persists_replies_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_gps_series, "INTERVAL_S", 0.001)
    monkeypatch.setattr(capture_gps_series, "DURATION_S", 0.1)
    monkeypatch.setattr(capture_gps_series, "MAX_REQUESTS", 2)
    attempts: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url)
        return httpx.Response(503 if len(attempts) == 1 else 200, stream=_Stream(b"{}"))

    output = tmp_path / "series"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await capture_gps_series.capture(client, output)
    assert attempts == [capture_gps_series.GPS_URL] * 2
    assert result.reason == "duration"
    assert [sample.status for sample in result.requests] == [503, 200]
    assert [sample.file for sample in result.requests] == [None, "markers-002.json"]
    assert not (output / "markers-001.json").exists()
    assert (output / "markers-002.json").read_bytes() == b"{}"
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert len(manifest["requests"]) == 2
    assert manifest["requests"][0]["issue"] == "http_status"
    assert sum(sample["size"] for sample in manifest["requests"]) == 4
    assert manifest["ended_at"] is not None


async def test_source_refusal_stops_the_series(tmp_path: Path) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, stream=_Stream(b"wait"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await capture_gps_series.capture(client, tmp_path / "series")
    assert result.reason == "source_refused"
    assert attempts == 1
