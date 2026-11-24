"""Проверить GPS-архив и повторить сопоставление с выбранным комплектом OTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel

from app.adapters.otp.schedule import load_release_schedule
from app.adapters.tsugaet.parse import parse_vehicles
from app.domain.low_floor import TripOccurrence
from app.domain.models import LiveVehicle
from app.domain.schedule_snapshot import ScheduleSnapshot
from app.domain.trip_match import TripMatches, TripScheduleIndex, VehicleMatch, match_trips
from tools.capture_gps_series import (
    DURATION_S,
    GPS_URL,
    INTERVAL_S,
    MAX_BYTES,
    MAX_REQUESTS,
    ROUTES,
)


class _Sample(BaseModel):
    started_at: datetime
    received_at: datetime
    status: int | None
    size: int
    issue: str | None
    file: str | None
    sha256: str | None


class _Manifest(BaseModel):
    url: str
    routes: tuple[str, ...]
    interval_s: int
    duration_s: int
    max_requests: int
    max_bytes: int
    started_at: datetime
    ended_at: datetime | None
    reason: str | None
    requests: list[_Sample]


def _verify_manifest(manifest: _Manifest) -> float | None:
    if (
        (manifest.url, manifest.routes) != (str(GPS_URL), ROUTES)
        or (manifest.interval_s, manifest.duration_s) != (INTERVAL_S, DURATION_S)
        or (manifest.max_requests, manifest.max_bytes) != (MAX_REQUESTS, MAX_BYTES)
    ):
        raise ValueError("Manifest не соответствует лимитам GPS-серии №8 и №35")
    times = [manifest.started_at]
    for row in manifest.requests:
        times.extend((row.started_at, row.received_at))
    if manifest.ended_at is not None:
        times.append(manifest.ended_at)
    if any(value.utcoffset() is None for value in times) or any(a > b for a, b in pairwise(times)):
        raise ValueError("Некорректное время в manifest GPS-серии")
    min_interval = min(
        ((b.started_at - a.started_at).total_seconds() for a, b in pairwise(manifest.requests)),
        default=None,
    )
    if (
        len(manifest.requests) > MAX_REQUESTS
        or any(item.size < 0 for item in manifest.requests)
        or sum(item.size for item in manifest.requests) > MAX_BYTES
        or (min_interval is not None and min_interval < INTERVAL_S - 0.01)
        or any(
            (item.started_at - manifest.started_at).total_seconds() >= DURATION_S
            for item in manifest.requests
        )
    ):
        raise ValueError("В manifest GPS-серии нарушен согласованный лимит")
    return min_interval


def _read_sample(archive: Path, sequence: int, sample: _Sample) -> bytes | None:
    if sample.file is None:
        if sample.sha256 is not None or sample.issue is None:
            raise ValueError(f"Неполная запись GPS-ответа {sequence}")
        return None
    if sample.file != f"markers-{sequence:03}.json" or sample.status != 200 or sample.issue:
        raise ValueError(f"Некорректная запись GPS-ответа {sequence}")
    path = archive / sample.file
    if path.stat().st_size != sample.size:
        raise ValueError(f"Не совпал размер {sample.file}")
    body = path.read_bytes()
    if len(body) != sample.size or hashlib.sha256(body).hexdigest() != sample.sha256:
        raise ValueError(f"Не совпала контрольная сумма {sample.file}")
    return body


def _percentile(values: list[float], part: float) -> float | None:
    return round(sorted(values)[math.ceil(len(values) * part) - 1], 3) if values else None


@dataclass
class _DirectionMetrics:
    records: int = 0
    seen: set[tuple[str, datetime]] = field(default_factory=set)
    ages: list[float] = field(default_factory=list)
    source_states: Counter[str] = field(default_factory=Counter)
    motion: Counter[str] = field(default_factory=Counter)
    matches: Counter[str] = field(default_factory=Counter)
    ramps: Counter[str] = field(default_factory=Counter)
    occurrences: set[TripOccurrence] = field(default_factory=set)
    confirmed_low_floor: int = 0
    plans: int = 0

    def record(self, live: LiveVehicle, match: VehicleMatch, received_at: datetime) -> bool:
        self.records += 1
        vehicle = live.vehicle
        key = vehicle.id, vehicle.position_observed_at
        if key in self.seen:
            return False
        self.seen.add(key)
        self.ages.append((received_at - vehicle.position_observed_at).total_seconds())
        self.source_states[live.state.value] += 1
        self.ramps[vehicle.low_floor.value] += 1
        self.plans += bool(live.plan)
        if match.observed_at != vehicle.position_observed_at:
            self.matches["ignored_out_of_order"] += 1
            return True
        self.motion[match.motion.value] += 1
        self.matches[match.status.value] += 1
        if match.assignment is not None:
            self.occurrences.add(match.assignment.occurrence)
        self.confirmed_low_floor += match.low_floor_occurrence is not None
        return True

    def summary(self) -> dict[str, object]:
        return {
            "vehicles": len({key for key, _ in self.seen}),
            "records": self.records,
            "unique_observations": len(self.seen),
            "repeated_observations": self.records - len(self.seen),
            "age_s_p50": _percentile(self.ages, 0.50),
            "age_s_p95": _percentile(self.ages, 0.95),
            "source_states": dict(self.source_states),
            "motion": dict(self.motion),
            "matches": dict(self.matches),
            "ramps": dict(self.ramps),
            "observations_with_plan": self.plans,
            "confirmed_occurrences": len(self.occurrences),
            "low_floor_observations": self.confirmed_low_floor,
        }


def _observations(body: bytes) -> tuple[dict[str, LiveVehicle], int]:
    parsed = parse_vehicles(json.loads(body))
    observations = {live.vehicle.id: live for live in parsed.vehicles}
    if len(observations) != len(parsed.vehicles):
        raise ValueError("Повторяющийся ID машины в одном ответе")
    if any(live.vehicle.line_id not in ROUTES for live in parsed.vehicles):
        raise ValueError("Ответ содержит маршрут вне согласованной серии")
    return observations, parsed.skipped


def _event(sample: int, observation: LiveVehicle, match: VehicleMatch) -> dict[str, object]:
    vehicle = observation.vehicle
    used = match.observed_at == vehicle.position_observed_at
    assignment = match.assignment if used else None
    return {
        "sample": sample,
        "vehicle_id": vehicle.id,
        "observed_at": vehicle.position_observed_at.isoformat(),
        "evidence_at": match.observed_at.isoformat(),
        "direction": vehicle.direction.value,
        "motion": match.motion.value if used else None,
        "match": match.status.value if used else "ignored_out_of_order",
        "ramp": vehicle.low_floor.value,
        "trip_id": assignment.occurrence.trip_id if assignment else None,
        "service_date": assignment.occurrence.service_date.isoformat() if assignment else None,
        "delay_s": assignment.delay_s if assignment else None,
        "candidate_count": len(match.candidates) if used else None,
    }


def replay(archive: Path, snapshot: ScheduleSnapshot) -> dict[str, object]:
    manifest = _Manifest.model_validate_json((archive / "manifest.json").read_bytes())
    min_interval = _verify_manifest(manifest)
    index = TripScheduleIndex(snapshot)
    previous: TripMatches | None = None
    metrics: dict[str, _DirectionMetrics] = {}
    events: list[dict[str, object]] = []
    invalid_samples: dict[int, str] = {}
    skipped_records = 0
    for sequence, sample in enumerate(manifest.requests, 1):
        body = _read_sample(archive, sequence, sample)
        observations: dict[str, LiveVehicle] = {}
        if body is not None:
            try:
                observations, skipped = _observations(body)
                skipped_records += skipped
            except ValueError as exc:
                invalid_samples[sequence] = str(exc)
        current = match_trips(index, observations, now=sample.received_at, previous=previous)
        for vehicle_id, observation in observations.items():
            match = current.vehicles[vehicle_id]
            key = f"{observation.vehicle.line_id}:{observation.vehicle.direction.value}"
            stats = metrics.setdefault(key, _DirectionMetrics())
            if stats.record(observation, match, sample.received_at):
                events.append(_event(sequence, observation, match))
        previous = current

    return {
        "graph_version": snapshot.version,
        "published_directions": sorted(
            {
                f"{service.line_id}:{service.direction.value}"
                for service in snapshot.services
                if service.line_id in ROUTES
            }
        ),
        "started_at": manifest.started_at.isoformat(),
        "ended_at": manifest.ended_at.isoformat() if manifest.ended_at else None,
        "reason": manifest.reason,
        "requests": len(manifest.requests),
        "bytes": sum(item.size for item in manifest.requests),
        "saved": sum(row.file is not None for row in manifest.requests),
        "min_interval_s": min_interval,
        "http_issues": dict(Counter(row.issue for row in manifest.requests if row.issue)),
        "invalid_samples": invalid_samples,
        "skipped_records": skipped_records,
        "directions": {key: stats.summary() for key, stats in metrics.items()},
        "observations": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = replay(args.archive, load_release_schedule(args.release))
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{report['saved']}/{report['requests']} ответов; {report['bytes']} байт; {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
