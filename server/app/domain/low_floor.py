"""Проверка результата OTP по актуальным подтверждениям каждой посадки."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType


@dataclass(frozen=True)
class TripOccurrence:
    trip_id: str
    service_date: date


@dataclass(frozen=True)
class LowFloorSnapshot:
    graph_version: str
    valid_until: datetime
    confirmed_until: Mapping[TripOccurrence, datetime]

    def __post_init__(self) -> None:
        object.__setattr__(self, "confirmed_until", MappingProxyType(dict(self.confirmed_until)))


def allows_low_floor(
    boardings: Sequence[TripOccurrence],
    *,
    otp_version: str | None,
    requested: LowFloorSnapshot | None,
    current: LowFloorSnapshot | None,
    now: datetime,
) -> bool:
    """Транспорт допустим при согласованной свежей версии и подтверждении всех рейсов."""
    if not boardings:
        return True
    if (
        current is None
        or current is not requested
        or not otp_version
        or otp_version != current.graph_version
        or now >= current.valid_until
    ):
        return False
    return all(
        (expires := current.confirmed_until.get(trip)) is not None and now < expires
        for trip in boardings
    )
