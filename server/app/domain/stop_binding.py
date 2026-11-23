"""Привязка остановок расписания к площадкам направления."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from app.domain.models import LinePath, RouteStop
from app.domain.schedule import RouteSchedule, ScheduleStop


@dataclass(frozen=True)
class StopBinding:
    scheduled: ScheduleStop
    platform: RouteStop


class BindingIssueKind(StrEnum):
    MISSING_GEOMETRY = "missing_geometry"
    WRONG_LINE = "wrong_line"
    INVALID_GEOMETRY = "invalid_geometry"
    MISSING_PLATFORM = "missing_platform"
    MISSING_SCHEDULE_STOP = "missing_schedule_stop"
    AMBIGUOUS_PLATFORM = "ambiguous_platform"
    STOP_ORDER = "stop_order"


@dataclass(frozen=True)
class BindingIssue:
    kind: BindingIssueKind
    scheduled: tuple[ScheduleStop, ...] = ()
    platforms: tuple[RouteStop, ...] = ()


@dataclass(frozen=True)
class StopBindings:
    stops: tuple[StopBinding, ...] = ()
    issues: tuple[BindingIssue, ...] = ()


def _name_key(name: str) -> str:
    return " ".join(name.casefold().replace("ё", "е").split())


def _name_issues(
    scheduled: tuple[ScheduleStop, ...], platforms: list[RouteStop]
) -> tuple[BindingIssue, ...]:
    scheduled_by_name: dict[str, list[ScheduleStop]] = {}
    platforms_by_name: dict[str, list[RouteStop]] = {}
    for stop in scheduled:
        scheduled_by_name.setdefault(_name_key(stop.name), []).append(stop)
    for platform in platforms:
        platforms_by_name.setdefault(_name_key(platform.stop.name), []).append(platform)

    issues: list[BindingIssue] = []
    for name in dict.fromkeys((*scheduled_by_name, *platforms_by_name)):
        stops = tuple(scheduled_by_name.get(name, ()))
        candidates = tuple(platforms_by_name.get(name, ()))
        if not candidates:
            issues.append(BindingIssue(BindingIssueKind.MISSING_PLATFORM, stops))
        elif not stops:
            issues.append(BindingIssue(BindingIssueKind.MISSING_SCHEDULE_STOP, (), candidates))
        elif len(candidates) != len(stops):
            issues.append(BindingIssue(BindingIssueKind.AMBIGUOUS_PLATFORM, stops, candidates))
    return tuple(issues)


def _geometry_is_ordered(path: LinePath) -> bool:
    if len(path.points) < 2:
        return False
    if any(a.point_index >= b.point_index for a, b in pairwise(path.stops)):
        return False
    return all(
        stop.order == index
        and stop.point_index < len(path.points)
        and stop.stop.point == path.points[stop.point_index]
        for index, stop in enumerate(path.stops)
    )


def bind_stops(schedule: RouteSchedule, path: LinePath | None) -> StopBindings:
    """Связывает последовательности при полном совпадении имён и порядка."""
    if path is None:
        return StopBindings(issues=(BindingIssue(BindingIssueKind.MISSING_GEOMETRY),))
    if path.line_id != schedule.route.line_id or path.direction != schedule.route.direction:
        return StopBindings(issues=(BindingIssue(BindingIssueKind.WRONG_LINE),))
    if not _geometry_is_ordered(path):
        return StopBindings(issues=(BindingIssue(BindingIssueKind.INVALID_GEOMETRY),))

    scheduled = tuple(table.stop for table in schedule.stops)
    issues = _name_issues(scheduled, path.stops)
    if issues:
        return StopBindings(issues=issues)

    pairs = tuple(zip(scheduled, path.stops, strict=True))
    for stop, platform in pairs:
        if _name_key(stop.name) != _name_key(platform.stop.name):
            return StopBindings(
                issues=(BindingIssue(BindingIssueKind.STOP_ORDER, (stop,), (platform,)),)
            )
    return StopBindings(stops=tuple(StopBinding(stop, platform) for stop, platform in pairs))
