"""Два потока GTFS-Realtime из одной версии расписания и общего снимка GPS."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.low_floor import LowFloorSnapshot, TripOccurrence
from app.domain.realtime import TripDelay
from app.domain.schedule_snapshot import ScheduleSnapshot
from app.domain.trip_match import (
    MatchSettings,
    MatchStatus,
    TripMatches,
    TripScheduleIndex,
    match_trips,
)
from app.ports import RealtimeEncoder
from app.services.live_snapshot import Clock, LiveSnapshotService, Snapshot

_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeSnapshot:
    all_payload: bytes
    low_payload: bytes
    low_access: LowFloorSnapshot


def _occurrences(schedule: ScheduleSnapshot) -> tuple[TripOccurrence, ...]:
    days = (
        schedule.window.start + timedelta(days=i)
        for i in range((schedule.window.end - schedule.window.start).days + 1)
    )
    return tuple(
        TripOccurrence(trip.trip_id, day)
        for day in days
        for service in schedule.services
        if service.operates_on(day)
        for trip in service.trips
    )


class RealtimeService:
    def __init__(
        self,
        live: LiveSnapshotService,
        schedule: ScheduleSnapshot,
        encoder: RealtimeEncoder,
        *,
        clock: Clock,
        settings: MatchSettings,
    ) -> None:
        self._live = live
        self._index = TripScheduleIndex(schedule)
        self._calendar = _occurrences(schedule)
        self._published = frozenset(self._calendar)
        self._encoder = encoder
        self._clock = clock
        self._settings = settings
        self._last_live: Snapshot | None = None
        self._matches: TripMatches | None = None
        self._current: RealtimeSnapshot | None = None

    @property
    def current(self) -> RealtimeSnapshot | None:
        snapshot = self._current
        return snapshot if snapshot and self._clock() < snapshot.low_access.valid_until else None

    def update(self) -> None:
        observed = self._live.current
        if observed is self._last_live and self.current is not None:
            return
        now = self._clock()
        vehicles = observed.vehicles if observed is not None else []
        counts = Counter(item.vehicle.id for item in vehicles)
        observations = {item.vehicle.id: item for item in vehicles if counts[item.vehicle.id] == 1}
        previous = self._matches
        if previous is not None and any(count > 1 for count in counts.values()):
            previous = TripMatches(
                previous.version,
                {key: match for key, match in previous.vehicles.items() if counts[key] < 2},
            )
        matches = match_trips(
            self._index, observations, now=now, previous=previous, settings=self._settings
        )
        self._current = self._payloads(matches, now)
        self._matches = matches
        self._last_live = observed

    def _payloads(self, matches: TripMatches, now: datetime) -> RealtimeSnapshot:
        delays: list[TripDelay] = []
        confirmed: dict[TripOccurrence, datetime] = {}
        expires = _FAR_FUTURE
        for match in matches.vehicles.values():
            candidate = match.assignment
            if (
                match.status is not MatchStatus.CONFIRMED
                or candidate is None
                or now >= match.valid_until
                or candidate.occurrence not in self._published
            ):
                continue
            expires = min(expires, match.valid_until)
            if match.low_floor_occurrence is not None:
                confirmed[candidate.occurrence] = match.valid_until
            if candidate.delay_s is not None:
                delays.append(
                    TripDelay(
                        candidate.occurrence,
                        candidate.stop_sequence,
                        round(candidate.delay_s),
                        match.observed_at,
                    )
                )
        delays.sort(key=lambda item: (item.occurrence.service_date, item.occurrence.trip_id))
        return RealtimeSnapshot(
            self._encoder.encode(delays, (), generated_at=now),
            self._encoder.encode(
                [delay for delay in delays if delay.occurrence in confirmed],
                [occurrence for occurrence in self._calendar if occurrence not in confirmed],
                generated_at=now,
            ),
            LowFloorSnapshot(matches.version, expires, confirmed),
        )

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.update)
            except Exception:
                log.exception("Ошибка обновления GTFS-Realtime")
            await asyncio.sleep(1)
