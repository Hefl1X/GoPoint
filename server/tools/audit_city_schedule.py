"""Аудит полного архива ЦУГАЭТ и GTFS на проверенных группах."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx

from app.adapters.tsugaet.parse import TsugaetFormatError, parse_traces
from app.adapters.tsugaet.schedule import (
    ScheduleGroup,
    ScheduleRequest,
    group_content_requests,
    schedule_geometry_requests,
)
from app.adapters.tsugaet.schedule_parse import parse_route_schedule
from app.domain.gtfs import ServiceWindow, build_gtfs, service_id_for
from app.domain.models import Direction, LinePath
from app.domain.schedule import RouteSchedule, ScheduleRoute, reconstruct_trips
from app.domain.stop_binding import bind_stops
from tools.build_gtfs import write_snapshot
from tools.capture_schedule import inventory_groups
from tools.collect_schedule import MissingScheduleResponseError, ScheduleArchive

type Sources = list[tuple[RouteSchedule, LinePath | None]]


def _read(archive: ScheduleArchive, request: ScheduleRequest) -> bytes:
    url = httpx.URL(request.url, params=request.params)
    response = archive.response(httpx.Request("GET", url))
    if response.status_code != httpx.codes.OK:
        raise ValueError(f"Архивный {request.kind} вернул HTTP {response.status_code}")
    return response.content


def _platform_conflicts(sources: Sources) -> dict[str, list[str]]:
    """Один ID с разными исходными строками исключает затронутые группы."""
    signatures: dict[str, dict[tuple[str, float, float], set[str]]] = {}
    for schedule, path in sources:
        bound = bind_stops(schedule, path)
        if bound.issues or not reconstruct_trips(schedule).trips:
            continue
        service = service_id_for(schedule)
        for binding in bound.stops:
            stop = binding.platform.stop
            row = (stop.name, stop.point.lat, stop.point.lon)
            signatures.setdefault(stop.id, {}).setdefault(row, set()).add(service)
    return {
        stop_id: sorted(set().union(*rows.values()))
        for stop_id, rows in sorted(signatures.items())
        if len(rows) > 1
    }


def audit(
    archive: ScheduleArchive,
    metadata: ScheduleArchive,
    groups: Sequence[ScheduleGroup],
    output: Path,
    window: ServiceWindow,
) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"Укажите новый каталог GTFS: {output}")
    paths: dict[tuple[str, Direction], LinePath] = {}
    geometry_issues: list[dict[str, object]] = []
    for direction, routes, request in schedule_geometry_requests(groups):
        wanted = [(route.line_id, route.marsh) for route in routes]
        try:
            body = _read(archive, request)
        except MissingScheduleResponseError as exc:
            geometry_issues.append(
                {
                    "direction": direction.value,
                    "lines": [line for line, _ in wanted],
                    "error": str(exc),
                }
            )
            continue
        try:
            batch = parse_traces(json.loads(body), wanted, direction)
        except ValueError as exc:
            geometry_issues.append(
                {
                    "direction": direction.value,
                    "lines": [line for line, _ in wanted],
                    "error": str(exc),
                }
            )
            continue
        for line_id, path in batch.items():
            paths[line_id, direction] = path

    sources: Sources = []
    schedule_errors: dict[str, str] = {}
    for group in sorted(groups, key=lambda group: group.key):
        stops, table = group_content_requests(group)
        try:
            stops_body, table_body = _read(archive, stops), _read(archive, table)
        except MissingScheduleResponseError as exc:
            schedule_errors["-".join(group.key)] = str(exc)
            continue
        day_params = {key: value for key, value in stops.params.items() if key != "sch"}
        raw_days = _read(metadata, ScheduleRequest("stops", stops.url, day_params))
        route_info, direction = group.route, group.direction
        route = ScheduleRoute(route_info.type, route_info.marsh, route_info.name, direction)
        try:
            schedule = parse_route_schedule(
                table_body.decode("utf-8"),
                stops_body.decode("utf-8"),
                raw_days.decode("utf-8"),
                route=route,
                day_id=group.day_id,
            )
        except (TsugaetFormatError, UnicodeError) as exc:
            schedule_errors["-".join(group.key)] = str(exc)
            continue
        sources.append((schedule, paths.get((route.line_id, direction))))

    conflicts = _platform_conflicts(sources)
    excluded = {service for related in conflicts.values() for service in related}
    build = build_gtfs(
        [
            (schedule, path)
            for schedule, path in sources
            if service_id_for(schedule) not in excluded
        ],
        window,
    )
    exported = [row for row in build.coverage if row.trip_count]
    counts: dict[str, object] = {
        "requested_groups": len(groups),
        "parsed_groups": len(sources),
        "geometry_directions": len(paths),
        "exported_groups": len(exported),
        "exported_trips": sum(row.trip_count for row in exported),
        "exported_lines": len({row.service_id.rsplit("-", 2)[0] for row in exported}),
        "schedule_errors": schedule_errors,
        "geometry_errors": geometry_issues,
        "conflicting_platforms": conflicts,
    }
    write_snapshot(
        output,
        window,
        build,
        {"sources": metadata.checksums | archive.checksums, "audit": counts},
    )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--service-start", type=date.fromisoformat, required=True)
    parser.add_argument("--service-end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        archive = ScheduleArchive(args.archive)
        metadata = ScheduleArchive(args.metadata)
        groups = inventory_groups(args.metadata, metadata)
        result = audit(
            archive,
            metadata,
            groups,
            args.output,
            ServiceWindow(args.service_start, args.service_end),
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps({key: value for key, value in result.items() if isinstance(value, int)}))
    return 0 if result["exported_groups"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
