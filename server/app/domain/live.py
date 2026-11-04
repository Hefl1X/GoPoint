"""Правила показа машин на линии. Чистые функции без сети."""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from datetime import datetime, timedelta

from app.domain.models import Accessibility, Bounds, Line, LiveVehicle, Vehicle

# Часы машины могут немного спешить относительно наших. Отметка «из будущего»
# дальше этого запаса считается ошибкой данных, и машина не показывается.
FUTURE_TOLERANCE = timedelta(minutes=2)


def is_fresh(observed_at: datetime, now: datetime, stale_seconds: int) -> bool:
    age = now - observed_at
    return -FUTURE_TOLERANCE <= age <= timedelta(seconds=stale_seconds)


def is_usable(live: LiveVehicle, now: datetime, stale_seconds: int, low_floor_only: bool) -> bool:
    """Машину можно показывать и брать в расчёт.

    Она на линии (правило сайта источника), её положение свежее, а при
    low_floor_only у неё точно низкий пол (yes; unknown не считается).
    """
    if not live.on_line:
        return False
    if not is_fresh(live.vehicle.position_observed_at, now, stale_seconds):
        return False
    return not low_floor_only or live.vehicle.low_floor is Accessibility.YES


def usable_vehicles(
    vehicles: Iterable[LiveVehicle],
    now: datetime,
    stale_seconds: int,
    low_floor_only: bool,
    bounds: Bounds | None = None,
) -> list[Vehicle]:
    return [
        live.vehicle
        for live in vehicles
        if is_usable(live, now, stale_seconds, low_floor_only)
        and (bounds is None or bounds.contains(live.vehicle.point))
    ]


_TYPE_ORDER = {"bus": 0, "trolleybus": 1, "tram": 2, "minibus": 3}


def line_sort_key(line: Line) -> tuple[int, int, str]:
    """Порядок в списке: вид транспорта, затем номер как число (2, 10, 45К)."""
    digits = "".join(itertools.takewhile(str.isdigit, line.number))
    return (_TYPE_ORDER.get(line.type.value, 9), int(digits) if digits else 10**6, line.number)
