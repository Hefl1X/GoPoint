"""Адаптер ЦУГАЭТ с имитацией их сайта (httpx.MockTransport). Настоящей сети нет."""

import json
import time
from urllib.parse import unquote

import httpx
import pytest

from app.adapters.tsugaet.feed import TsugaetFeed
from app.domain.models import Direction, TransportType
from app.ports import TransitFeedError, UnknownLineError
from tests.conftest import SAMPLES

LISTMARSH = json.loads((SAMPLES / "listmarsh.json").read_text(encoding="utf-8"))
MARKERS = json.loads((SAMPLES / "markers.json").read_text(encoding="utf-8"))
TRASSES = json.loads((SAMPLES / "trasses_bus3_A.json").read_text(encoding="utf-8"))
UA = "GoPoint-test/1.0"


class FakeSite:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.times: list[float] = []
        self.markers_status = 200
        self.markers_body: bytes | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.times.append(time.monotonic())
        path = request.url.path
        if path == "/listmarsh.php":
            return httpx.Response(200, json=LISTMARSH)
        if path == "/markers.php":
            if self.markers_body is not None:
                return httpx.Response(self.markers_status, content=self.markers_body)
            return httpx.Response(self.markers_status, json=MARKERS)
        if path == "/trasses.php":
            return httpx.Response(200, json=TRASSES)
        return httpx.Response(404)


def make_feed(site: FakeSite, pause_s: float = 0.0, **kwargs: object) -> TsugaetFeed:
    return TsugaetFeed(
        user_agent=UA,
        pause_s=pause_s,
        transport=httpx.MockTransport(site),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_lines_and_user_agent() -> None:
    site = FakeSite()
    feed = make_feed(site)
    lines = await feed.lines()
    assert len(lines) == 104
    assert site.requests[0].headers["User-Agent"] == UA
    assert site.requests[0].url.params["r"] == "true"


async def test_types_filter_excludes_minibus() -> None:
    feed = make_feed(FakeSite(), types=frozenset({TransportType.BUS, TransportType.TRAM}))
    lines = await feed.lines()
    assert {line.type for line in lines} == {TransportType.BUS, TransportType.TRAM}


async def test_vehicles_request_uses_route_keys() -> None:
    site = FakeSite()
    feed = make_feed(site)
    await feed.lines()
    vehicles = await feed.vehicles(["bus-3", "tram-0013"])
    r = unquote(site.requests[-1].url.params["r"])
    assert r == "1-3-W-3|3-0013-W-13|"
    assert len(vehicles) == 36  # имитация отдаёт образец целиком


async def test_more_than_six_lines_is_refused() -> None:
    feed = make_feed(FakeSite())
    lines = await feed.lines()
    with pytest.raises(ValueError, match="6"):
        await feed.vehicles([line.id for line in lines[:7]])


async def test_pause_between_requests() -> None:
    site = FakeSite()
    feed = make_feed(site, pause_s=0.05)
    await feed.lines()
    await feed.vehicles(["bus-3"])
    await feed.vehicles(["bus-3"])
    gaps = [b - a for a, b in zip(site.times, site.times[1:], strict=False)]
    assert all(gap >= 0.045 for gap in gaps)
    assert feed.requests_made == 3


async def test_line_path() -> None:
    site = FakeSite()
    feed = make_feed(site)
    path = await feed.line_path("bus-3", Direction.A)
    assert len(path.stops) == 35
    assert unquote(site.requests[-1].url.params["r"]) == "1-3-A-3|"


async def test_unknown_line() -> None:
    feed = make_feed(FakeSite())
    with pytest.raises(UnknownLineError):
        await feed.line_path("bus-нет", Direction.A)


@pytest.mark.parametrize(
    ("status", "body"),
    [(500, b"oops"), (200, b"<html>maintenance</html>"), (200, b'{"nope": []}')],
)
async def test_bad_answers_become_feed_errors(status: int, body: bytes) -> None:
    site = FakeSite()
    site.markers_status, site.markers_body = status, body
    feed = make_feed(site)
    await feed.lines()
    with pytest.raises(TransitFeedError):
        await feed.vehicles(["bus-3"])


async def test_network_failure_becomes_feed_error() -> None:
    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("нет сети")

    feed = TsugaetFeed(user_agent=UA, pause_s=0, transport=httpx.MockTransport(broken))
    with pytest.raises(TransitFeedError):
        await feed.lines()
