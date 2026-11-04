import asyncio
from collections.abc import Sequence
from datetime import timedelta

import pytest

from app.adapters.fake.feed import FakeTransitFeed
from app.domain.models import Direction, LiveVehicle
from app.ports import TransitFeedError
from app.services.live_snapshot import LiveSnapshotService
from tests.conftest import ManualClock


def service(feed: FakeTransitFeed, clock: ManualClock) -> LiveSnapshotService:
    return LiveSnapshotService(feed, clock=clock, poll_interval_s=30, active_window_s=120)


async def test_refresh_polls_in_batches_of_six(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    svc = service(fake_feed, clock)
    snap = await svc.snapshot()
    lines = await svc.lines()
    assert fake_feed.vehicle_requests == -(-len(lines) // 6)
    assert len(snap.vehicles) == 36
    assert snap.complete
    assert snap.fetched_at == clock.now


async def test_snapshot_is_shared_and_not_refetched_within_interval(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    svc = service(fake_feed, clock)
    await svc.snapshot()
    first = fake_feed.vehicle_requests
    clock.advance(20)
    await asyncio.gather(*(svc.snapshot() for _ in range(100)))  # сто пользователей
    assert fake_feed.vehicle_requests == first


async def test_concurrent_refreshes_make_one_poll(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    svc = service(fake_feed, clock)
    await asyncio.gather(svc.refresh(), svc.refresh(), svc.refresh())
    lines = await svc.lines()
    assert fake_feed.vehicle_requests == -(-len(lines) // 6)


async def test_old_snapshot_returned_when_source_fails(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    svc = service(fake_feed, clock)
    good = await svc.snapshot()
    fake_feed.fail = True
    clock.advance(600)
    snap = await svc.snapshot()
    assert snap is good
    assert snap.fetched_at == clock.now - timedelta(seconds=600)


async def test_no_snapshot_and_source_fails_is_error(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    fake_feed.fail = True
    with pytest.raises(TransitFeedError):
        await service(fake_feed, clock).snapshot()


async def test_failed_batch_keeps_previous_vehicles_of_those_lines(
    fake_feed: FakeTransitFeed, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = service(fake_feed, clock)
    await svc.snapshot()
    original = fake_feed.vehicles

    async def flaky(line_ids: Sequence[str]) -> list[LiveVehicle]:
        if "tram-0013" in line_ids:
            raise TransitFeedError("пачка не пришла")
        return await original(line_ids)

    monkeypatch.setattr(fake_feed, "vehicles", flaky)
    clock.advance(31)
    snap = await svc.refresh()
    assert not snap.complete
    assert len(snap.by_line["tram-0013"]) == 19  # из прошлого снимка
    assert len(snap.by_line["bus-3"]) == 12


async def test_activity_window(fake_feed: FakeTransitFeed, clock: ManualClock) -> None:
    svc = service(fake_feed, clock)
    assert not svc.is_active()
    svc.touch()
    clock.advance(120)
    assert svc.is_active()
    clock.advance(1)
    assert not svc.is_active()


async def test_poller_polls_only_while_someone_uses_api(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    svc = service(fake_feed, clock)
    task = asyncio.create_task(svc.run_poller(tick_s=0.001))
    try:
        await asyncio.sleep(0.02)
        assert fake_feed.vehicle_requests == 0  # никого нет: опроса нет
        svc.touch()
        await asyncio.sleep(0.02)
        polls_once = fake_feed.vehicle_requests
        assert polls_once > 0
        await asyncio.sleep(0.02)
        assert fake_feed.vehicle_requests == polls_once  # 30 с ещё не прошло
        clock.advance(30)
        await asyncio.sleep(0.02)
        assert fake_feed.vehicle_requests == 2 * polls_once
        clock.advance(200)  # пользователи ушли
        await asyncio.sleep(0.02)
        assert fake_feed.vehicle_requests == 2 * polls_once
    finally:
        task.cancel()


async def test_lines_cached_for_a_day(fake_feed: FakeTransitFeed, clock: ManualClock) -> None:
    svc = service(fake_feed, clock)
    first = await svc.lines()
    fake_feed.fail = True
    clock.advance(3600)
    assert await svc.lines() is first  # из кэша, к источнику не ходили
    clock.advance(86_400)
    assert await svc.lines() is first  # кэш устарел, источник молчит: прошлый список


async def test_line_path_cached(fake_feed: FakeTransitFeed, clock: ManualClock) -> None:
    svc = service(fake_feed, clock)
    path = await svc.line_path("bus-3", Direction.A)
    fake_feed.fail = True
    assert await svc.line_path("bus-3", Direction.A) is path
