"""Привязка остановок расписания к площадкам направления."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from app.domain.models import LinePath, RouteStop
from app.domain.schedule import RouteSchedule, ScheduleStop


@dataclass(frozen=True)
class StopBinding:
    scheduled: ScheduleStop
    platform: RouteStop


@dataclass(frozen=True)
class ReviewedAlignment:
    """Проверенный порядок площадок для конкретной версии двух списков остановок."""

    signature: str
    platform_orders: tuple[int, ...]
    evidence: str


class BindingIssueKind(StrEnum):
    MISSING_GEOMETRY = "missing_geometry"
    WRONG_LINE = "wrong_line"
    INVALID_GEOMETRY = "invalid_geometry"
    MISSING_PLATFORM = "missing_platform"
    MISSING_SCHEDULE_STOP = "missing_schedule_stop"
    AMBIGUOUS_PLATFORM = "ambiguous_platform"
    STOP_ORDER = "stop_order"
    INVALID_REVIEW = "invalid_review"


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


def alignment_signature(schedule: RouteSchedule, path: LinePath) -> str:
    """Фиксирует названия, позиции, ID и координаты площадок, сверенные при привязке."""
    stops = [
        (s.source_id, s.sequence, s.name, s.source_sequence)
        for s in (row.stop for row in schedule.stops)
    ]
    platforms = [
        (p.order, p.point_index, p.stop.id, p.stop.name, p.stop.point.lat, p.stop.point.lon)
        for p in path.stops
    ]
    data = json.dumps(
        [1, path.line_id, path.direction.value, stops, platforms], separators=(",", ":")
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _bind_review(
    schedule: RouteSchedule, path: LinePath, review: ReviewedAlignment
) -> StopBindings:
    orders = review.platform_orders
    if (
        review.signature != alignment_signature(schedule, path)
        or not review.evidence.strip()
        or len(orders) != len(schedule.stops)
        or any(not 0 <= order < len(path.stops) for order in orders)
        or any(a >= b for a, b in pairwise(orders))
    ):
        return StopBindings(issues=(BindingIssue(BindingIssueKind.INVALID_REVIEW),))
    return StopBindings(
        stops=tuple(
            StopBinding(row.stop, path.stops[order])
            for row, order in zip(schedule.stops, orders, strict=True)
        )
    )


def _bind_by_name(schedule: RouteSchedule, path: LinePath) -> StopBindings:
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


def bind_stops(
    schedule: RouteSchedule, path: LinePath | None, review: ReviewedAlignment | None = None
) -> StopBindings:
    """Связывает последовательности по сохранённой сверке либо по полному совпадению имён."""
    if path is None:
        return StopBindings(issues=(BindingIssue(BindingIssueKind.MISSING_GEOMETRY),))
    if path.line_id != schedule.route.line_id or path.direction != schedule.route.direction:
        return StopBindings(issues=(BindingIssue(BindingIssueKind.WRONG_LINE),))
    if not _geometry_is_ordered(path):
        return StopBindings(issues=(BindingIssue(BindingIssueKind.INVALID_GEOMETRY),))
    return _bind_review(schedule, path, review) if review else _bind_by_name(schedule, path)


def ordered_terminal_candidates(schedule: RouteSchedule, path: LinePath) -> tuple[RouteStop, ...]:
    """Площадки конечной, совместимые с порядком всех имён в расписании."""
    if not schedule.stops or not _geometry_is_ordered(path):
        return ()
    if path.line_id != schedule.route.line_id or path.direction != schedule.route.direction:
        return ()

    platforms = iter(path.stops)
    for table in schedule.stops[:-1]:
        name = _name_key(table.stop.name)
        if not any(_name_key(platform.stop.name) == name for platform in platforms):
            return ()
    name = _name_key(schedule.stops[-1].stop.name)
    return tuple(platform for platform in platforms if _name_key(platform.stop.name) == name)
