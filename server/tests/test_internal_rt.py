from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as rt

from app.adapters.fake.feed import FakeTransitFeed
from app.config import Settings
from app.domain.models import Accessibility, Line, LiveVehicle, TransportType
from app.domain.schedule_snapshot import ScheduleSnapshot
from app.main import create_app
from app.ports import TransitFeedError
from app.services.live_snapshot import LiveSnapshotService
from app.services.realtime import RealtimeService
from tests.conftest import SAMPLES, ManualClock
from tests.test_trip_match import DAY, FIRST, SIX, WINDOW, _at, _obs, _service

_ALL = "/internal/gtfs-rt/all"
_LOW = "/internal/gtfs-rt/low-floor"


class _Feed(FakeTransitFeed):
    observations: list[LiveVehicle]

    def __init__(self) -> None:
        super().__init__(SAMPLES)
        self.observations = []

    async def lines(self) -> list[Line]:
        return [Line(id="bus-1", number="1", title="Тест", type=TransportType.BUS)]

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        assert line_ids == ["bus-1"]
        self.vehicle_requests += 1
        if self.fail:
            raise TransitFeedError("Отказ тестового источника")
        return self.observations


async def _get(client: httpx.AsyncClient, path: str) -> rt.FeedMessage:
    response = await client.get(path, params={"version": "test-graph"})
    assert response.status_code == 200
    assert response.headers["X-GoPoint-Graph-Version"] == "test-graph"
    assert response.headers["Content-Type"] == "application/x-protobuf"
    assert response.headers["Cache-Control"] == "no-store"
    return cast(rt.FeedMessage, rt.FeedMessage.FromString(response.content))


async def test_both_endpoints_use_one_snapshot_and_expiry_clears_delay() -> None:
    clock = ManualClock(_at(SIX + 90))
    feed = _Feed()
    schedule = ScheduleSnapshot("test-graph", WINDOW, (_service(FIRST),))
    app = create_app(
        Settings(), feed=feed, clock=clock, start_poller=False, realtime_schedule=schedule
    )
    live: LiveSnapshotService = app.state.live
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        service: RealtimeService = app.state.realtime
        assert not (await _get(client, _ALL)).entity
        assert (await client.get(_LOW)).status_code == 422
        assert (await client.get(f"{_LOW}?version=previous-graph")).status_code == 503
        initial = await _get(client, _LOW)
        assert initial.header.incrementality == rt.FeedHeader.FULL_DATASET
        assert len(initial.entity) == 7
        assert all(
            e.trip_update.trip.schedule_relationship == rt.TripDescriptor.CANCELED
            for e in initial.entity
        )
        assert feed.vehicle_requests == 0 and not live.is_active()

        feed.observations = [_obs(SIX + 90, 0.0025)]
        await live.refresh()
        service.update()
        assert not (await _get(client, _ALL)).entity

        clock.advance(140)
        feed.observations = [_obs(SIX + 210, 0.0075)]
        await live.refresh()
        service.update()
        current = await _get(client, _ALL)
        (entity,) = current.entity
        delay = entity.trip_update
        assert delay.trip.trip_id == "A-0"
        assert delay.timestamp == int(_at(SIX + 210).timestamp())
        assert delay.timestamp < current.header.timestamp
        assert delay.stop_time_update[0].stop_sequence == 3
        assert delay.stop_time_update[0].departure.delay == 30
        low = await _get(client, _LOW)
        assert len(low.entity) == 7
        assert (
            sum(
                e.trip_update.trip.schedule_relationship == rt.TripDescriptor.CANCELED
                for e in low.entity
            )
            == 6
        )
        assert feed.vehicle_requests == 2 and not live.is_active()

        clock.advance(30)
        feed.fail = True
        with pytest.raises(TransitFeedError):
            await live.refresh()
        service.update()
        assert (await _get(client, _ALL)).entity[0].trip_update.timestamp == delay.timestamp

        clock.now = _at(SIX + 210) + timedelta(seconds=300)
        assert (await client.get(_LOW, params={"version": "test-graph"})).status_code == 503
        service.update()
        assert not (await _get(client, _ALL)).entity
        assert all(
            e.trip_update.trip.schedule_relationship == rt.TripDescriptor.CANCELED
            for e in (await _get(client, _LOW)).entity
        )
    assert app.state.realtime is None


async def test_high_floor_confirmation_updates_all_and_is_cancelled_in_low() -> None:
    clock = ManualClock(_at(SIX + 90))
    feed = _Feed()
    schedule = ScheduleSnapshot("test-graph", WINDOW, (_service(FIRST),))
    app = create_app(
        Settings(), feed=feed, clock=clock, start_poller=False, realtime_schedule=schedule
    )
    live: LiveSnapshotService = app.state.live
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        service: RealtimeService = app.state.realtime
        feed.observations = [_obs(SIX + 90, 0.0025, ramp=Accessibility.NO)]
        await live.refresh()
        service.update()
        clock.advance(120)
        feed.observations = [_obs(SIX + 210, 0.0075, ramp=Accessibility.NO)]
        await live.refresh()
        service.update()
        assert len((await _get(client, _ALL)).entity) == 1
        assert all(
            e.trip_update.trip.schedule_relationship == rt.TripDescriptor.CANCELED
            for e in (await _get(client, _LOW)).entity
        )


async def test_departure_after_midnight_keeps_its_service_date() -> None:
    clock = ManualClock(_at(86400))
    feed = _Feed()
    overnight = _service((86280, 86520, 86640, 86880))
    schedule = ScheduleSnapshot("test-graph", WINDOW, (overnight,))
    app = create_app(
        Settings(), feed=feed, clock=clock, start_poller=False, realtime_schedule=schedule
    )
    live: LiveSnapshotService = app.state.live
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        service: RealtimeService = app.state.realtime
        feed.observations = [_obs(86400, 0.0025)]
        await live.refresh()
        service.update()
        clock.advance(180)
        feed.observations = [_obs(86580, 0.0075)]
        await live.refresh()
        service.update()
        (item,) = (await _get(client, _ALL)).entity
        assert item.trip_update.trip.start_date == DAY.strftime("%Y%m%d")
        low = {
            entity.trip_update.trip.start_date: entity.trip_update.trip.schedule_relationship
            for entity in (await _get(client, _LOW)).entity
        }
        assert len(low) == 7
        assert low.pop(item.trip_update.trip.start_date) == rt.TripDescriptor.SCHEDULED
        assert set(low.values()) == {rt.TripDescriptor.CANCELED}


async def test_missing_release_keeps_api_available(tmp_path: Path) -> None:
    app = create_app(
        Settings(realtime_release=tmp_path / "missing"), feed=_Feed(), start_poller=False
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (await client.get("/health")).status_code == 200
        assert (await client.get(_LOW, params={"version": "test-graph"})).status_code == 503
        paths = (await client.get("/api/openapi.json")).json()["paths"]
        assert all(not path.startswith("/internal/") for path in paths)
