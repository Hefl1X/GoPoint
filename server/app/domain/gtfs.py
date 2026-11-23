"""Детерминированные строки GTFS из проверенных остановок и расписаний."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.domain.models import Direction, LinePath, TransportType
from app.domain.schedule import (
    RouteSchedule,
    ScheduleDayKind,
    ScheduledTrip,
    ScheduleIssue,
    reconstruct_trips,
)
from app.domain.stop_binding import BindingIssue, StopBinding, bind_stops

type Row = tuple[str, ...]

AGENCY_ID = "tsugaet"
_ROUTE_TYPE = {
    TransportType.TRAM: "0",
    TransportType.BUS: "3",
    TransportType.MINIBUS: "3",
    TransportType.TROLLEYBUS: "11",
}
_DAYS = {
    ScheduleDayKind.DAILY: ("1",) * 7,
    ScheduleDayKind.WEEKDAYS: ("1",) * 5 + ("0",) * 2,
    ScheduleDayKind.WEEKENDS: ("0",) * 5 + ("1",) * 2,
}


class GtfsBuildError(ValueError):
    """Противоречие идентификаторов или календаря при построении фида."""


@dataclass(frozen=True)
class ServiceWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise GtfsBuildError("Конец календаря раньше начала")

    @property
    def dates(self) -> tuple[str, str]:
        return self.start.isoformat().replace("-", ""), self.end.isoformat().replace("-", "")

    def serves(self, days: Row) -> bool:
        day_count = min(7, (self.end - self.start).days + 1)
        return any(days[(self.start.weekday() + offset) % 7] == "1" for offset in range(day_count))


@dataclass(frozen=True)
class GtfsTable:
    name: str
    header: Row
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class ServiceCoverage:
    service_id: str
    trip_count: int
    bindings: tuple[StopBinding, ...]
    binding_issues: tuple[BindingIssue, ...]
    schedule_issues: tuple[ScheduleIssue, ...]


@dataclass(frozen=True)
class GtfsBuild:
    tables: tuple[GtfsTable, ...]
    coverage: tuple[ServiceCoverage, ...]


def service_id_for(schedule: RouteSchedule) -> str:
    route = schedule.route
    return f"{route.line_id}-{route.direction.value}-{schedule.day.source_id}"


def _gtfs_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _insert[K, V](rows: dict[K, V], key: K, value: V) -> None:
    if rows.setdefault(key, value) != value:
        raise GtfsBuildError(f"Разные записи GTFS с одним ID {key!r}")


@dataclass
class _FeedRows:
    stops: dict[str, Row] = field(default_factory=dict)
    routes: dict[str, Row] = field(default_factory=dict)
    shapes: dict[str, tuple[Row, ...]] = field(default_factory=dict)
    trips: list[Row] = field(default_factory=list)
    stop_times: list[Row] = field(default_factory=list)
    calendar: list[Row] = field(default_factory=list)

    def add(
        self,
        schedule: RouteSchedule,
        path: LinePath,
        window: ServiceWindow,
        bindings: tuple[StopBinding, ...],
        trips: tuple[ScheduledTrip, ...],
    ) -> None:
        route = schedule.route
        service_id = service_id_for(schedule)
        days = _DAYS[schedule.day.kind]
        if not window.serves(days):
            raise GtfsBuildError(f"Нет действующих дат для {service_id} в указанном календаре")
        self.calendar.append((service_id, *days, *window.dates))

        route_row = (route.line_id, AGENCY_ID, route.number, _ROUTE_TYPE[route.type])
        _insert(self.routes, route.line_id, route_row)
        shape_id = f"{route.line_id}-{route.direction.value}"
        shape = tuple(
            (shape_id, str(point.lat), str(point.lon), str(seq))
            for seq, point in enumerate(path.points, start=1)
        )
        _insert(self.shapes, shape_id, shape)
        for binding in bindings:
            stop = binding.platform.stop
            stop_row = (stop.id, stop.name, str(stop.point.lat), str(stop.point.lon))
            _insert(self.stops, stop.id, stop_row)

        direction_id = "0" if route.direction is Direction.A else "1"
        for trip in trips:
            trip_id = f"{service_id}-{trip.calls[0].time:06d}"
            self.trips.append((route.line_id, service_id, trip_id, direction_id, shape_id))
            for call, binding in zip(trip.calls, bindings, strict=True):
                when = _gtfs_time(call.time)
                self.stop_times.append(
                    (trip_id, when, when, binding.platform.stop.id, str(call.stop.sequence))
                )

    def tables(self, window: ServiceWindow) -> tuple[GtfsTable, ...]:
        return (
            GtfsTable(
                "agency.txt",
                ("agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"),
                (
                    (
                        AGENCY_ID,
                        "МКУ «ЦУГАЭТ»",
                        "https://www.nskgortrans.ru/",
                        "Asia/Novosibirsk",
                        "ru",
                    ),
                ),
            ),
            GtfsTable(
                "stops.txt",
                ("stop_id", "stop_name", "stop_lat", "stop_lon"),
                tuple(self.stops.values()),
            ),
            GtfsTable(
                "routes.txt",
                ("route_id", "agency_id", "route_short_name", "route_type"),
                tuple(self.routes.values()),
            ),
            GtfsTable(
                "trips.txt",
                ("route_id", "service_id", "trip_id", "direction_id", "shape_id"),
                tuple(self.trips),
            ),
            GtfsTable(
                "stop_times.txt",
                ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
                tuple(self.stop_times),
            ),
            GtfsTable(
                "calendar.txt",
                (
                    "service_id",
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                    "start_date",
                    "end_date",
                ),
                tuple(self.calendar),
            ),
            GtfsTable(
                "shapes.txt",
                ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
                tuple(row for shape in self.shapes.values() for row in shape),
            ),
            GtfsTable(
                "feed_info.txt",
                (
                    "feed_publisher_name",
                    "feed_publisher_url",
                    "feed_lang",
                    "feed_start_date",
                    "feed_end_date",
                ),
                (("GoPoint", "https://github.com/Hefl1X/GoPoint", "ru", *window.dates),),
            ),
        )


def build_gtfs(
    sources: Sequence[tuple[RouteSchedule, LinePath | None]], window: ServiceWindow
) -> GtfsBuild:
    """Формирует фид для проверенных групп и учёт покрытия для каждой группы."""
    rows = _FeedRows()
    coverage: dict[str, ServiceCoverage] = {}
    for schedule, path in sorted(sources, key=lambda item: service_id_for(item[0])):
        service_id = service_id_for(schedule)
        if service_id in coverage:
            raise GtfsBuildError(f"Повторная группа расписания {service_id!r}")
        bindings = bind_stops(schedule, path)
        result = reconstruct_trips(schedule)
        trip_count = 0
        if path is not None and not bindings.issues and result.trips:
            rows.add(schedule, path, window, bindings.stops, result.trips)
            trip_count = len(result.trips)
        coverage[service_id] = ServiceCoverage(
            service_id, trip_count, bindings.stops, bindings.issues, result.issues
        )

    return GtfsBuild(rows.tables(window) if rows.trips else (), tuple(coverage.values()))
