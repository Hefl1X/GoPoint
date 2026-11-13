"""Поиск маршрута «сейчас» по машинам на линии. Чистые функции без сети.

Раздел 8 docs/ARCHITECTURE.md, пункты 3–5. Каждая машина — это «рейс»: список
остановок впереди с временем прихода (domain/linear.py). Поиск по кругам, как в
RAPTOR: круг k — лучшее время на остановках после k поездок (до трёх поездок, то
есть до двух пересадок). Пешие участки до остановок, от остановок и между
остановками на пересадке приходят готовыми (длительность в секундах).

Запасы:
- board_margin_s: человек должен быть на остановке за столько до машины (аппарель);
- transfer_margin_s: ещё столько на пересадке (сверх board_margin_s).
Выбирается самое раннее прибытие; запасные варианты — другие наборы машин,
не хуже лучшего больше чем на max_extra_s.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.domain.linear import StopCall
from app.domain.models import VariantLabel


@dataclass(frozen=True)
class Trip:
    """Одна машина и остановки впереди неё (по порядку движения)."""

    vehicle_id: str
    calls: Sequence[StopCall]


@dataclass(frozen=True)
class SearchParams:
    board_margin_s: int = 120
    transfer_margin_s: int = 180
    max_rides: int = 3
    max_alternatives: int = 2
    max_extra_s: int = 30 * 60
    # Сесть в первую машину нужно не позже, чем через столько (горизонт 60 минут).
    board_within_s: int = 60 * 60


@dataclass(frozen=True)
class Ride:
    trip: Trip
    board: int  # номер в trip.calls
    alight: int


@dataclass(frozen=True)
class TransferWalk:
    from_stop: str
    to_stop: str
    duration_s: int


@dataclass(frozen=True)
class Plan:
    """Найденный вариант: пешком до остановки, поездки, пересадки, пешком до цели."""

    access_stop: str
    steps: tuple[Ride | TransferWalk, ...]
    egress_stop: str
    arrive_at: datetime  # у цели
    walk_s: int = 0  # всего пешком: до остановки, на пересадках, от остановки
    labels: tuple[VariantLabel, ...] = ()

    @property
    def rides(self) -> list[Ride]:
        return [s for s in self.steps if isinstance(s, Ride)]

    @property
    def vehicle_ids(self) -> tuple[str, ...]:
        return tuple(r.trip.vehicle_id for r in self.rides)


@dataclass(frozen=True)
class _Label:
    time: datetime
    ride: Ride | None = None  # как приехали на остановку (None в круге 0: дошли от точки А)
    board_stop: str | None = None  # для поездки: где сели
    walk: TransferWalk | None = None  # для пешей пересадки: откуда пришли


@dataclass
class _Round:
    rides: dict[str, _Label] = field(default_factory=dict)  # приехали на машине
    walks: dict[str, _Label] = field(default_factory=dict)  # дошли пешком (пересадка)

    def ready(self, stop: str) -> _Label | None:
        a, b = self.rides.get(stop), self.walks.get(stop)
        if a is None or (b is not None and b.time < a.time):
            return b
        return a


class SearchError(RuntimeError):
    """Внутренняя ошибка поиска (нарушена связность меток). Не должна случаться."""


def search(
    now: datetime,
    trips: Sequence[Trip],
    access: Mapping[str, int],
    egress: Mapping[str, int],
    transfers: Mapping[str, Sequence[tuple[str, int]]],
    params: SearchParams,
    first_vehicle: str | None = None,
) -> list[Plan]:
    """Лучший вариант и до max_alternatives запасных; пустой список, если доехать нельзя.

    first_vehicle: искать только варианты, где первая поездка на этой машине
    (для проверки уже выбранного маршрута); тогда запасные не ищутся.

    Запасные варианты ищутся повторно без первой машины уже найденных вариантов:
    если она не придёт, у человека будет вариант на другой машине.
    """
    found = _search_once(now, trips, access, egress, transfers, params, first_vehicle)
    if not found:
        return []
    if first_vehicle is not None:
        return [replace(found[0], labels=("fastest",))]
    chosen = _label_variants(found, params)
    # Добираем запасные варианты на других машинах: если первая машина не придёт,
    # у человека будет вариант без неё.
    limit = chosen[0].arrive_at + timedelta(seconds=params.max_extra_s)
    excluded: set[str] = set()
    while len(chosen) <= params.max_alternatives:
        excluded |= {p.vehicle_ids[0] for p in chosen}
        rest = [t for t in trips if t.vehicle_id not in excluded]
        more = _search_once(now, rest, access, egress, transfers, params)
        new = [
            p
            for p in more
            if p.arrive_at <= limit and p.vehicle_ids not in {c.vehicle_ids for c in chosen}
        ]
        if not new:
            break
        chosen = [*chosen, new[0]]
    return chosen[: params.max_alternatives + 1]


def _label_variants(plans: list[Plan], params: SearchParams) -> list[Plan]:
    """Быстрее всего, меньше пересадок, меньше пешком: до трёх разных вариантов с ярлыками.

    Все — не позже самого быстрого больше чем на max_extra_s. Один вариант может
    получить несколько ярлыков.
    """
    fastest = min(plans, key=lambda p: (p.arrive_at, len(p.rides), p.walk_s))
    limit = fastest.arrive_at + timedelta(seconds=params.max_extra_s)
    near = [p for p in plans if p.arrive_at <= limit]
    picks: list[tuple[VariantLabel, Plan]] = [
        ("fastest", fastest),
        ("fewest_transfers", min(near, key=lambda p: (len(p.rides), p.arrive_at, p.walk_s))),
        ("least_walking", min(near, key=lambda p: (p.walk_s, p.arrive_at, len(p.rides)))),
    ]
    result: list[Plan] = []
    for label, plan in picks:
        for i, existing in enumerate(result):
            if existing.vehicle_ids == plan.vehicle_ids:
                result[i] = replace(existing, labels=(*existing.labels, label))
                break
        else:
            result.append(replace(plan, labels=(label,)))
    return result


def _search_once(
    now: datetime,
    trips: Sequence[Trip],
    access: Mapping[str, int],
    egress: Mapping[str, int],
    transfers: Mapping[str, Sequence[tuple[str, int]]],
    params: SearchParams,
    first_vehicle: str | None = None,
) -> list[Plan]:
    start = _Round()
    for stop, walk_s in access.items():
        start.walks[stop] = _Label(now + timedelta(seconds=walk_s))
    rounds = [start]
    best: dict[str, datetime] = {}

    for k in range(1, params.max_rides + 1):
        prev = rounds[k - 1]
        margin = timedelta(
            seconds=params.board_margin_s + (params.transfer_margin_s if k > 1 else 0)
        )
        current = _Round()
        board_until = now + timedelta(seconds=params.board_within_s) if k == 1 else None
        for trip in trips:
            if k == 1 and first_vehicle is not None and trip.vehicle_id != first_vehicle:
                continue
            _scan_trip(trip, prev, current, best, margin, board_until)
        if not current.rides:
            break
        for stop, label in current.rides.items():
            if stop not in best or label.time < best[stop]:
                best[stop] = label.time
        _add_transfers(current, transfers)
        rounds.append(current)

    return _choose(_collect(rounds, access, egress), params)


def _scan_trip(
    trip: Trip,
    prev: _Round,
    current: _Round,
    best: dict[str, datetime],
    margin: timedelta,
    board_until: datetime | None,
) -> None:
    """Сесть на машину на первой подходящей остановке и отметить остановки после неё."""
    boarded: int | None = None
    for i, call in enumerate(trip.calls):
        stop = call.stop.id
        if boarded is not None:
            have = current.rides.get(stop)
            known = best.get(stop)
            if (have is None or call.arrive_at < have.time) and (
                known is None or call.arrive_at < known
            ):
                current.rides[stop] = _Label(
                    call.arrive_at, Ride(trip, boarded, i), trip.calls[boarded].stop.id
                )
        ready = prev.ready(stop)
        if (
            boarded is None
            and ready is not None
            and ready.time + margin <= call.arrive_at
            and (board_until is None or call.arrive_at <= board_until)
        ):
            boarded = i


def _add_transfers(current: _Round, transfers: Mapping[str, Sequence[tuple[str, int]]]) -> None:
    """Пешком на соседнюю остановку для следующей пересадки."""
    for stop, label in current.rides.items():
        for other, walk_s in transfers.get(stop, ()):
            t = label.time + timedelta(seconds=walk_s)
            have = current.walks.get(other)
            if have is None or t < have.time:
                current.walks[other] = _Label(t, walk=TransferWalk(stop, other, walk_s))


def _reconstruct(rounds: list[_Round], k: int, stop: str) -> tuple[str, list[Ride | TransferWalk]]:
    """Шаги варианта, который приехал на stop в круге k (с конца к началу)."""
    steps: list[Ride | TransferWalk] = []
    label = rounds[k].rides.get(stop)
    while k > 0:
        if label is None or label.ride is None or label.board_stop is None:
            raise SearchError("нет поездки в цепочке")
        steps.append(label.ride)
        stop = label.board_stop
        k -= 1
        label = rounds[k].ready(stop)
        if label is not None and label.walk is not None:
            steps.append(label.walk)
            stop = label.walk.from_stop
            label = rounds[k].rides.get(stop)
    steps.reverse()
    return stop, steps


def _collect(
    rounds: list[_Round], access: Mapping[str, int], egress: Mapping[str, int]
) -> list[Plan]:
    plans: list[Plan] = []
    for k in range(1, len(rounds)):
        for stop, label in rounds[k].rides.items():
            if stop not in egress:
                continue
            access_stop, steps = _reconstruct(rounds, k, stop)
            transfers_s = sum(s.duration_s for s in steps if isinstance(s, TransferWalk))
            plans.append(
                Plan(
                    access_stop=access_stop,
                    steps=tuple(steps),
                    egress_stop=stop,
                    arrive_at=label.time + timedelta(seconds=egress[stop]),
                    walk_s=access.get(access_stop, 0) + transfers_s + egress[stop],
                )
            )
    return plans


def _choose(plans: list[Plan], params: SearchParams) -> list[Plan]:
    """Лучший по прибытию (при равенстве меньше пересадок), затем разные наборы машин."""
    by_vehicles: dict[tuple[str, ...], Plan] = {}
    for plan in sorted(plans, key=lambda p: (p.arrive_at, len(p.rides))):
        by_vehicles.setdefault(plan.vehicle_ids, plan)
    ordered = list(by_vehicles.values())
    if not ordered:
        return []
    best = ordered[0]
    limit = best.arrive_at + timedelta(seconds=params.max_extra_s)
    chosen = [best]
    for plan in ordered[1:]:
        if len(chosen) > params.max_alternatives:
            break
        # Запасной вариант с теми же машинами плюс лишняя пересадка не нужен.
        if plan.arrive_at > limit or set(best.vehicle_ids) <= set(plan.vehicle_ids):
            continue
        chosen.append(plan)
    return chosen


def with_transfer_times(
    transfers: Mapping[str, Sequence[tuple[str, int]]],
    fixes: Sequence[tuple[str, str, int | None]],
) -> dict[str, list[tuple[str, int]]]:
    """Пешие пересадки с настоящим временем по улицам: (откуда, куда, секунды или None).

    None: пути по улицам нет, пересадка убирается.
    """
    fixed = {stop: list(pairs) for stop, pairs in transfers.items()}
    for from_stop, to_stop, seconds in fixes:
        pairs = [(sid, s) for sid, s in fixed.get(from_stop, []) if sid != to_stop]
        if seconds is not None:
            pairs.append((to_stop, seconds))
        fixed[from_stop] = pairs
    return fixed
