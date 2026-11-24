"""Сверить интервалы проезда контрольных остановок по сохранённой GPS-серии."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path

from app.adapters.otp.schedule import load_release_schedule
from app.adapters.tsugaet.parse import NOVOSIBIRSK
from app.domain.linear import (
    LineGeometry,
    build_geometry,
    normalize_stop_name,
    projection_candidates,
)
from app.domain.models import LinePath, LiveVehicle, PlannedStop
from app.domain.schedule_snapshot import ScheduledService, ScheduleSnapshot
from app.domain.trip_match import DEFAULT_MATCH_SETTINGS
from tools.replay_gps_series import GpsFrame, read_gps_archive

_MAX_GAP_S = 120
_MAX_OFFSET_M = 65.0
_SETTINGS = DEFAULT_MATCH_SETTINGS


@dataclass(frozen=True)
class _Point:
    live: LiveVehicle
    along_m: float

    @property
    def at(self) -> datetime:
        return self.live.vehicle.position_observed_at


@dataclass(frozen=True)
class _Passage:
    stop_index: int
    before: _Point
    after: _Point


def _tracks(frames: Sequence[GpsFrame], line_id: str) -> list[list[LiveVehicle | None]]:
    tracks: dict[str, dict[datetime, LiveVehicle | None]] = defaultdict(dict)
    for frame in frames:
        for live in frame.observations.values():
            vehicle = live.vehicle
            if vehicle.line_id != line_id:
                continue
            at = vehicle.position_observed_at
            track = tracks[vehicle.id]
            if at in track:
                first = track[at]
                if first is not None and (
                    first.vehicle.point != vehicle.point
                    or first.vehicle.direction != vehicle.direction
                ):
                    track[at] = None
                continue
            age = (frame.received_at - at).total_seconds()
            track[at] = live if 0 <= age < _SETTINGS.stale_s else None
    return [[track[key] for key in sorted(track)] for _, track in sorted(tracks.items())]


def _control_stops(
    service: ScheduledService, tracks: list[list[LiveVehicle | None]]
) -> tuple[dict[str, int], tuple[int, ...]]:
    positions: dict[str, list[int]] = defaultdict(list)
    for index, binding in enumerate(service.bindings):
        positions[normalize_stop_name(binding.platform.stop.name)].append(index)
    unique = {name: indices[0] for name, indices in positions.items() if len(indices) == 1}
    controls = {
        unique[name]
        for track in tracks
        for live in track
        if live is not None and live.vehicle.direction == service.direction
        for stop in live.plan
        if (name := normalize_stop_name(stop.stop_name)) in unique
    }
    return unique, tuple(
        sorted(index for index in controls if 0 < index < len(service.bindings) - 1)
    )


def _project(live: LiveVehicle | None, geometry: LineGeometry) -> _Point | None:
    if live is None or live.vehicle.direction != geometry.path.direction:
        return None
    options = projection_candidates(geometry, live.vehicle.point, max_offset_m=_MAX_OFFSET_M)
    if len(options) != 1:
        return None
    return _Point(live, options[0].along_m)


def _passages(
    geometry: LineGeometry, track: list[LiveVehicle | None], controls: tuple[int, ...]
) -> list[_Passage]:
    result: list[_Passage] = []
    for before, after in pairwise(_project(live, geometry) for live in track):
        if before is None or after is None:
            continue
        seconds = (after.at - before.at).total_seconds()
        progress = after.along_m - before.along_m
        if not 0 < seconds <= _MAX_GAP_S or not (
            _SETTINGS.min_progress_m <= progress <= seconds * _SETTINGS.max_speed_mps
        ):
            continue
        result.extend(
            _Passage(index, before, after)
            for index in controls
            if before.along_m < geometry.stop_along_m[index] < after.along_m
        )
    return result


def _time_comparison(planned: datetime, passage: _Passage) -> dict[str, object]:
    return {
        "planned_at": planned.astimezone(NOVOSIBIRSK).isoformat(),
        "inside_interval": passage.before.at <= planned <= passage.after.at,
        "offset_s": [
            (point.at - planned).total_seconds() for point in (passage.before, passage.after)
        ],
    }


def _schedule_times(service: ScheduledService, passage: _Passage) -> list[dict[str, object]]:
    earliest = passage.before.at - timedelta(seconds=_SETTINGS.late_s)
    latest = passage.after.at + timedelta(seconds=_SETTINGS.early_s)
    latest_planned_s = max(trip.stop_times[passage.stop_index].arrival for trip in service.trips)
    first_day = max(
        service.window.start,
        (earliest - timedelta(seconds=latest_planned_s)).astimezone(NOVOSIBIRSK).date(),
    )
    last_day = min(service.window.end, latest.astimezone(NOVOSIBIRSK).date())
    result: list[dict[str, object]] = []
    for offset in range((last_day - first_day).days + 1):
        day: date = first_day + timedelta(days=offset)
        if not service.operates_on(day):
            continue
        midnight = datetime.combine(day, time(), NOVOSIBIRSK)
        for trip in service.trips:
            planned = midnight + timedelta(seconds=trip.stop_times[passage.stop_index].arrival)
            if earliest <= planned <= latest:
                result.append(
                    {
                        "trip_id": trip.trip_id,
                        "service_date": day.isoformat(),
                        **_time_comparison(planned, passage),
                    }
                )
    return result


def _rasp_times(passage: _Passage, names: dict[str, int]) -> list[dict[str, object]]:
    runs: list[list[tuple[int, PlannedStop]]] = [[]]
    for stop in passage.before.live.plan:
        index = names.get(normalize_stop_name(stop.stop_name))
        if index is None or (
            runs[-1] and (index <= runs[-1][-1][0] or stop.at <= runs[-1][-1][1].at)
        ):
            runs.append([])
        if index is not None:
            runs[-1].append((index, stop))
    matches = [
        (stop.at, len(run) > 1)
        for run in runs
        for index, stop in run
        if index == passage.stop_index
    ]
    return [
        {"forward_order": forward and len(matches) == 1, **_time_comparison(at, passage)}
        for at, forward in matches
    ]


def check_passages(
    snapshot: ScheduleSnapshot, service_id: str, frames: Sequence[GpsFrame]
) -> dict[str, object]:
    service = next((item for item in snapshot.services if item.service_id == service_id), None)
    if service is None or not service.trips:
        raise ValueError(f"Группа {service_id} отсутствует в принятом расписании")
    tracks = _tracks(frames, service.line_id)
    names, controls = _control_stops(service, tracks)
    geometry = build_geometry(
        LinePath(
            line_id=service.line_id,
            direction=service.direction,
            points=list(service.shape),
            stops=[binding.platform for binding in service.bindings],
        )
    )
    rows = []
    for passage in sorted(
        (item for track in tracks for item in _passages(geometry, track, controls)),
        key=lambda item: (item.before.at, item.before.live.vehicle.id, item.stop_index),
    ):
        stop = service.bindings[passage.stop_index].platform.stop
        rows.append(
            {
                "vehicle_id": passage.before.live.vehicle.id,
                "stop_id": stop.id,
                "stop_name": stop.name,
                "before": passage.before.at.astimezone(NOVOSIBIRSK).isoformat(),
                "after": passage.after.at.astimezone(NOVOSIBIRSK).isoformat(),
                "schedule": _schedule_times(service, passage),
                "rasp": _rasp_times(passage, names),
            }
        )
    return {
        "graph_version": snapshot.version,
        "service_id": service_id,
        "max_gap_s": _MAX_GAP_S,
        "max_offset_m": _MAX_OFFSET_M,
        "controls": [geometry.path.stops[index].stop.id for index in controls],
        "passages": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("archive", "release", "output"):
        parser.add_argument(f"--{argument}", type=Path, required=True)
    parser.add_argument("--service", required=True)
    args = parser.parse_args()
    try:
        archive = read_gps_archive(args.archive)
        report = check_passages(load_release_schedule(args.release), args.service, archive.frames)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
