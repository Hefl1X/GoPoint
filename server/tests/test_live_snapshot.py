import asyncio
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from app.adapters.fake.feed import FakeTransitFeed
from app.domain.models import Direction, Line, LinePath, LiveVehicle
from app.ports import TransitFeedError
from app.services.live_snapshot import LiveSnapshotService
from tests.conftest import SAMPLES, ManualClock


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


async def test_poller_preloads_network_once_someone_uses_api(
    fake_feed: FakeTransitFeed, clock: ManualClock
) -> None:
    """Линии всех маршрутов грузятся заранее: первый маршрут не ждёт ~25 с."""
    svc = service(fake_feed, clock)
    task = asyncio.create_task(svc.run_poller(tick_s=0.001))
    try:
        await asyncio.sleep(0.02)
        assert fake_feed.path_requests == 0  # никого нет: ничего не грузим
        svc.touch()
        await asyncio.sleep(0.05)
        loaded = fake_feed.path_requests
        assert loaded > 0
        await asyncio.sleep(0.02)
        assert fake_feed.path_requests == loaded  # один раз, не на каждый такт
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


class CountingFeed(FakeTransitFeed):
    """Считает все запросы к источнику: машины, список маршрутов, линии."""

    def __init__(self, samples_dir: Path) -> None:
        super().__init__(samples_dir)
        self.calls = 0

    async def lines(self) -> list[Line]:
        self.calls += 1
        return await super().lines()

    async def line_path(self, line_id: str, direction: Direction) -> LinePath:
        self.calls += 1
        return await super().line_path(line_id, direction)

    async def line_paths(
        self, line_ids: Sequence[str], direction: Direction
    ) -> dict[str, LinePath]:
        self.calls += 1
        return await super().line_paths(line_ids, direction)

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        self.calls += 1
        return await super().vehicles(line_ids)


async def _hour_of_users(users: int) -> tuple[int, int, int]:
    """Час работы: каждые 30 с фоновый опрос (как run_poller), а каждый пользователь
    обновляет карту, список и строит маршрут. Потом 10 минут никого.
    Возвращает (запросов за час, за первые 2 минуты после ухода, за следующие 8 минут)."""
    feed = CountingFeed(SAMPLES)
    clock = ManualClock()
    svc = service(feed, clock)

    async def poller_tick() -> None:
        if svc.is_active():
            await svc.refresh()

    for _ in range(120):  # 120 × 30 с = 1 час
        await poller_tick()
        await asyncio.gather(
            *(svc.snapshot() for _ in range(users)),
            *(svc.lines() for _ in range(users)),
            *(svc.network() for _ in range(users)),
        )
        clock.advance(30)
    during = feed.calls
    for _ in range(4):  # 2 минуты: окно активности ещё открыто
        await poller_tick()
        clock.advance(30)
    tail = feed.calls - during
    for _ in range(16):  # ещё 8 минут: опроса нет
        await poller_tick()
        clock.advance(30)
    return during, tail, feed.calls - during - tail


async def test_load_on_source_same_for_one_and_hundred_users() -> None:
    """Запрос 9, пункт 4: нагрузка на ЦУГАЭТ не зависит от числа пользователей,
    а без пользователей опрос через 2 минуты останавливается."""
    one = await _hour_of_users(1)
    hundred = await _hour_of_users(100)
    assert one == hundred
    during, tail, idle = one
    # В образце список из 104 маршрутов, как на сайте ЦУГАЭТ: 18 пачек по 6 на опрос,
    # 120 опросов в час; список маршрутов 1 раз в сутки; линии 2 направления пачками.
    batches = -(-104 // 6)
    assert 120 * batches < during <= 120 * batches + 1 + 2 * batches
    assert tail <= 4 * batches  # окно активности 2 минуты
    assert idle == 0
