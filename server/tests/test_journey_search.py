"""Поиск маршрута по машинам на линии (без сети)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.journey_search import Ride, SearchParams, TransferWalk, Trip, search
from app.domain.linear import StopCall
from app.domain.models import EtaMethod, LatLon, Stop

NOW = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
P = SearchParams(board_margin_s=120, transfer_margin_s=180)


def minutes(m: float) -> datetime:
    return NOW + timedelta(minutes=m)


def trip(vehicle: str, *calls: tuple[str, float]) -> Trip:
    return Trip(
        vehicle_id=vehicle,
        calls=[
            StopCall(
                stop=Stop(id=s, name=s, point=LatLon(lat=55, lon=83)),
                order=i,
                arrive_at=minutes(m),
                method=EtaMethod.DISTANCE,
            )
            for i, (s, m) in enumerate(calls)
        ],
    )


def test_direct_ride() -> None:
    t = trip("bus-1", ("s0", 5), ("s1", 10), ("s3", 15))
    [plan] = search(NOW, [t], {"s0": 60}, {"s3": 120}, {}, P)
    assert plan.access_stop == "s0"
    assert plan.egress_stop == "s3"
    assert plan.vehicle_ids == ("bus-1",)
    assert plan.arrive_at == minutes(17)


def test_boarding_margin_is_respected() -> None:
    too_soon = trip("bus-1", ("s0", 2.5), ("s3", 10))  # дойти 1 мин + запас 2 мин = 3 мин
    later = trip("bus-2", ("s0", 8), ("s3", 18))
    plans = search(NOW, [too_soon, later], {"s0": 60}, {"s3": 0}, {}, P)
    assert [p.vehicle_ids for p in plans] == [("bus-2",)]


def test_no_vehicle_means_no_plan() -> None:
    t = trip("bus-1", ("s5", 5), ("s6", 10))
    assert search(NOW, [t], {"s0": 60}, {"s3": 0}, {}, P) == []


def test_transfer_with_walk_between_stops() -> None:
    first = trip("bus-1", ("s0", 5), ("s2", 15))
    second = trip("tram-0013-2", ("s5", 23), ("s9", 35))
    transfers = {"s2": [("s5", 120)]}
    [plan] = search(NOW, [first, second], {"s0": 60}, {"s9": 60}, transfers, P)
    assert plan.vehicle_ids == ("bus-1", "tram-0013-2")
    assert isinstance(plan.steps[0], Ride)
    assert plan.steps[1] == TransferWalk("s2", "s5", 120)
    assert isinstance(plan.steps[2], Ride)
    assert plan.arrive_at == minutes(36)


def test_late_first_vehicle_misses_transfer() -> None:
    # Первая машина опаздывает: на остановке пересадки в 20:00, пешком 2 мин,
    # запас 2 + 3 мин: на трамвай в 23:00 уже не успеть, берём следующий.
    late = trip("bus-1", ("s0", 5), ("s2", 20))
    missed = trip("tram-a", ("s5", 23), ("s9", 35))
    next_one = trip("tram-b", ("s5", 30), ("s9", 42))
    plans = search(NOW, [late, missed, next_one], {"s0": 60}, {"s9": 0}, {"s2": [("s5", 120)]}, P)
    assert plans[0].vehicle_ids == ("bus-1", "tram-b")
    assert all("tram-a" not in p.vehicle_ids for p in plans)


def test_at_most_two_transfers() -> None:
    legs = [
        trip("v1", ("a", 5), ("b", 10)),
        trip("v2", ("b", 16), ("c", 20)),
        trip("v3", ("c", 26), ("d", 30)),
        trip("v4", ("d", 36), ("e", 40)),
    ]
    assert search(NOW, legs, {"a": 0}, {"e": 0}, {}, P) == []
    assert search(NOW, legs, {"a": 0}, {"d": 0}, {}, P)[0].vehicle_ids == ("v1", "v2", "v3")


def test_best_first_and_alternatives_with_other_vehicles() -> None:
    fast = trip("bus-1", ("s0", 5), ("s3", 15))
    slow = trip("bus-2", ("s0", 7), ("s3", 22))
    slower = trip("bus-3", ("s1", 6), ("s4", 30))
    plans = search(NOW, [slow, fast, slower], {"s0": 60, "s1": 60}, {"s3": 0, "s4": 0}, {}, P)
    assert plans[0].vehicle_ids == ("bus-1",)
    assert {p.vehicle_ids for p in plans[1:]} == {("bus-2",), ("bus-3",)}


def test_vehicle_that_already_passed_stop_is_not_boarded() -> None:
    # У машины нет остановки посадки впереди: она уже проехала s0.
    passed = trip("bus-1", ("s2", 3), ("s3", 6))
    assert search(NOW, [passed], {"s0": 0}, {"s3": 0}, {}, P) == []


def test_first_vehicle_restriction() -> None:
    fast = trip("bus-1", ("s0", 5), ("s3", 15))
    slow = trip("bus-2", ("s0", 7), ("s3", 22))
    [plan] = search(NOW, [fast, slow], {"s0": 60}, {"s3": 0}, {}, P, first_vehicle="bus-2")
    assert plan.vehicle_ids == ("bus-2",)
    assert search(NOW, [fast], {"s0": 60}, {"s3": 0}, {}, P, first_vehicle="bus-9") == []


def test_boarding_must_be_within_horizon_but_ride_may_be_longer() -> None:
    long_ride = trip("bus-1", ("s0", 50), ("s3", 120))
    [plan] = search(NOW, [long_ride], {"s0": 0}, {"s3": 0}, {}, P)
    assert plan.arrive_at == minutes(120)
    too_late = trip("bus-2", ("s0", 70), ("s3", 80))
    assert search(NOW, [too_late], {"s0": 0}, {"s3": 0}, {}, P) == []
