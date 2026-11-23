import asyncio
from pathlib import Path

import httpx
import pytest

from app.adapters.tsugaet.parse import RouteInfo, TsugaetFormatError
from app.adapters.tsugaet.schedule import ScheduleBudget, ScheduleSourceError, TsugaetScheduleSource
from app.domain.models import Direction, TransportType
from app.domain.schedule import reconstruct_trips

SAMPLES = Path(__file__).resolve().parents[3] / "data/tsugaet/samples/audit-2026-11-21"
ROUTE = RouteInfo(TransportType.BUS, "8", "8", "Цветной проезд", "Вокзал")
_GRASP_SAMPLES = {
    (): "bus8-directions.xml",
    (("r", "A"),): "bus8-A-days.xml",
    (("r", "A"), ("sch", "23")): "bus8-A-stops.xml",
    (("r", "A"), ("s", "0"), ("sch", "23"), ("tv", "mr"), ("v", "0")): "bus8-A-day23-all.html",
}


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)


def _reply(request: httpx.Request) -> httpx.Response:
    parameters = dict(request.url.params)
    if request.url.host == "map.nskgortrans.ru":
        assert request.url.path == "/trasses.php"
        assert parameters == {"r": "1-8-A-8|"}
        sample = "trasses-A.json"
    else:
        assert request.url.host == "nskgortrans.ru"
        assert request.url.path.endswith("/grasp.php")
        assert parameters.pop("m") == "8"
        assert parameters.pop("t") == "1"
        sample = _GRASP_SAMPLES[tuple(sorted(parameters.items()))]
    return httpx.Response(200, content=(SAMPLES / sample).read_bytes())


async def test_loads_full_schedule_and_serializes_concurrent_requests() -> None:
    clock = _Clock()
    attempts: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        attempts.append(clock())
        return _reply(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = TsugaetScheduleSource(
            client, ScheduleBudget(10, 1_000_000), clock=clock, sleep=clock.sleep
        )
        first, second = await asyncio.gather(
            source.load(ROUTE, Direction.A, "23"), source.load(ROUTE, Direction.A, "23")
        )
    assert first == second
    assert first.path.line_id == "bus-8"
    assert len(first.schedule.stops) == 38
    assert len(reconstruct_trips(first.schedule).trips) == 55
    assert attempts == [index * 1.5 for index in range(10)]
    assert source.requests_made == 10


async def test_retries_transient_status_with_backoff_and_honors_retry_after() -> None:
    clock = _Clock()
    attempts: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        attempts.append(clock())
        if len(attempts) == 1:
            return httpx.Response(503)
        if len(attempts) == 2:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return _reply(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = TsugaetScheduleSource(
            client, ScheduleBudget(7, 1_000_000), clock=clock, sleep=clock.sleep
        )
        await source.load(ROUTE, Direction.A, "23")
    assert attempts == [0, 2, 9, 10.5, 12, 13.5, 15]


async def test_request_budget_counts_every_failed_attempt() -> None:
    clock = _Clock()

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = TsugaetScheduleSource(
            client, ScheduleBudget(2, 1_000_000), clock=clock, sleep=clock.sleep
        )
        with pytest.raises(ScheduleSourceError, match="бюджет запросов"):
            await source.load(ROUTE, Direction.A, "23")
    assert source.requests_made == 2
    assert clock.now == 2


async def test_byte_budget_aborts_before_fetching_the_next_page() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_reply)) as client:
        source = TsugaetScheduleSource(client, ScheduleBudget(5, 10))
        with pytest.raises(ScheduleSourceError, match="бюджет байтов"):
            await source.load(ROUTE, Direction.A, "23")
    assert source.requests_made == 1


@pytest.mark.parametrize("broken", [404, 200])
async def test_partial_failure_does_not_return_schedule(broken: int) -> None:
    clock = _Clock()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/trasses.php":
            return httpx.Response(broken, content=b"<html/>")
        return _reply(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = TsugaetScheduleSource(
            client, ScheduleBudget(8, 1_000_000), clock=clock, sleep=clock.sleep
        )
        error = ScheduleSourceError if broken == 404 else TsugaetFormatError
        with pytest.raises(error):
            await source.load(ROUTE, Direction.A, "23")
    assert source.requests_made == 5
