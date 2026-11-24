"""Чтение расписания GoPoint из проверенного комплекта графа OTP."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, TypeAdapter

from app.adapters.otp.release import ArtifactError, verify_release
from app.domain.gtfs import ServiceCoverage, ServiceWindow
from app.domain.models import Direction, LatLon, Stop
from app.domain.schedule_snapshot import CallTime, PublishedTrip, ScheduledService, ScheduleSnapshot
from app.domain.stop_binding import StopBinding

_WEEK = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DIRECTION = {"0": Direction.A, "1": Direction.B}
_BINDINGS = TypeAdapter(dict[str, tuple[StopBinding, ...]])


class _CoverageReport(BaseModel):
    service_start: date
    service_end: date
    coverage: tuple[ServiceCoverage, ...]


def published_coverage(data: bytes, window: ServiceWindow) -> dict[str, ServiceCoverage]:
    report = _CoverageReport.model_validate_json(data)
    if (report.service_start, report.service_end) != (window.start, window.end):
        raise ArtifactError("Календарь GTFS и отчёта покрытия расходятся")
    published = [row for row in report.coverage if row.trip_count > 0]
    result = {row.service_id: row for row in published}
    if len(result) != len(published):
        raise ArtifactError("Повторная опубликованная группа в отчёте покрытия")
    return result


def binding_data(coverage: dict[str, ServiceCoverage]) -> bytes:
    """Данные привязок без метрик сбора и диагностики исключённых групп."""
    return _BINDINGS.dump_json({key: coverage[key].bindings for key in sorted(coverage)})


def _rows(archive: ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
        yield from csv.DictReader(text, strict=True)


def _window(row: dict[str, str], start: str, end: str) -> ServiceWindow:
    return ServiceWindow(date.fromisoformat(row[start]), date.fromisoformat(row[end]))


def _weekdays(archive: ZipFile, window: ServiceWindow) -> dict[str, frozenset[int]]:
    result: dict[str, frozenset[int]] = {}
    for row in _rows(archive, "calendar.txt"):
        values = tuple(row[day] for day in _WEEK)
        service = row["service_id"]
        if (
            service in result
            or set(values) - {"0", "1"}
            or _window(row, "start_date", "end_date") != window
            or not window.serves(values)
        ):
            raise ArtifactError(f"Некорректный календарь группы {service}")
        result[service] = frozenset(index for index, value in enumerate(values) if value == "1")
    return result


def _shapes(archive: ZipFile) -> dict[str, tuple[LatLon, ...]]:
    result: dict[str, list[LatLon]] = defaultdict(list)
    for row in _rows(archive, "shapes.txt"):
        shape = result[row["shape_id"]]
        if int(row["shape_pt_sequence"]) != len(shape) + 1:
            raise ArtifactError("Нарушен порядок точек геометрии GTFS")
        shape.append(LatLon(lat=float(row["shape_pt_lat"]), lon=float(row["shape_pt_lon"])))
    return {key: tuple(points) for key, points in result.items()}


def _platforms(archive: ZipFile) -> dict[str, Stop]:
    result: dict[str, Stop] = {}
    for row in _rows(archive, "stops.txt"):
        stop = Stop(
            id=row["stop_id"],
            name=row["stop_name"],
            point=LatLon(lat=float(row["stop_lat"]), lon=float(row["stop_lon"])),
        )
        if stop.id in result:
            raise ArtifactError(f"Повторная площадка {stop.id} в GTFS")
        result[stop.id] = stop
    return result


def _seconds(value: str) -> int:
    hour, minute, second = map(int, value.split(":"))
    if hour < 0 or not (0 <= minute < 60 and 0 <= second < 60):
        raise ArtifactError("Некорректное время остановки в GTFS")
    return (hour * 60 + minute) * 60 + second


@dataclass(frozen=True)
class _Pattern:
    line: str
    direction: Direction
    shape_id: str


def _trips(
    archive: ZipFile, coverage: dict[str, ServiceCoverage]
) -> tuple[dict[str, _Pattern], dict[str, list[PublishedTrip]]]:
    patterns: dict[str, _Pattern] = {}
    services: dict[str, str] = {}
    calls: dict[str, list[CallTime]] = {}
    for row in _rows(archive, "trips.txt"):
        trip, service = row["trip_id"], row["service_id"]
        pattern = _Pattern(row["route_id"], _DIRECTION[row["direction_id"]], row["shape_id"])
        if trip in services or patterns.setdefault(service, pattern) != pattern:
            raise ArtifactError(f"Несовместимое описание рейса {trip}")
        services[trip] = service
        calls[trip] = []

    for row in _rows(archive, "stop_times.txt"):
        trip = row["trip_id"]
        times = calls[trip]
        bindings = coverage[services[trip]].bindings
        sequence = len(times) + 1
        if sequence > len(bindings) or (int(row["stop_sequence"]), row["stop_id"]) != (
            sequence,
            bindings[sequence - 1].platform.stop.id,
        ):
            raise ArtifactError(f"Остановки рейса {trip} расходятся с привязками")
        arrival, departure = _seconds(row["arrival_time"]), _seconds(row["departure_time"])
        if arrival > departure or (times and arrival < times[-1].departure):
            raise ArtifactError(f"Нарушен порядок времён рейса {trip}")
        times.append(CallTime(arrival, departure))

    result: dict[str, list[PublishedTrip]] = defaultdict(list)
    for trip, service in services.items():
        times = calls[trip]
        if len(times) < 2 or len(times) != len(coverage[service].bindings):
            raise ArtifactError(f"Неполный список остановок рейса {trip}")
        result[service].append(PublishedTrip(trip, tuple(times)))
    return patterns, result


def _service(
    coverage: ServiceCoverage,
    pattern: _Pattern,
    window: ServiceWindow,
    weekdays: frozenset[int],
    shape: tuple[LatLon, ...],
    trips: list[PublishedTrip],
) -> ScheduledService:
    bindings = coverage.bindings
    indices = [binding.platform.point_index for binding in bindings]
    if (
        len(trips) != coverage.trip_count
        or len(shape) < 2
        or any(first >= second for first, second in pairwise(indices))
        or any(
            index >= len(shape) or shape[index] != bind.platform.stop.point
            for index, bind in zip(indices, bindings, strict=True)
        )
    ):
        raise ArtifactError(f"Группа {coverage.service_id} расходится с расписанием или геометрией")
    return ScheduledService(
        coverage.service_id,
        pattern.line,
        pattern.direction,
        weekdays,
        window,
        bindings,
        shape,
        tuple(sorted(trips, key=lambda trip: trip.stop_times[0].departure)),
    )


def read_published_schedule(
    feed: Path, coverage_data: bytes, version: str, window: ServiceWindow
) -> ScheduleSnapshot:
    try:
        coverage = published_coverage(coverage_data, window)
        with ZipFile(feed) as archive:
            info = list(_rows(archive, "feed_info.txt"))
            if (
                len(info) != 1
                or info[0]["feed_version"] != version
                or _window(info[0], "feed_start_date", "feed_end_date") != window
            ):
                raise ArtifactError("Версия или календарь GTFS расходится с manifest.json")
            if "calendar_dates.txt" in archive.namelist():
                raise ArtifactError("Календарные исключения GTFS ещё не поддерживаются")
            calendars = _weekdays(archive, window)
            shapes = _shapes(archive)
            platforms = _platforms(archive)
            patterns, trips = _trips(archive, coverage)
        if not coverage or not (coverage.keys() == calendars.keys() == patterns.keys()):
            raise ArtifactError("Группы рейсов, календарь и отчёт покрытия расходятся")
        for row in coverage.values():
            if any(
                platforms.get(binding.platform.stop.id) != binding.platform.stop
                for binding in row.bindings
            ):
                raise ArtifactError(f"Площадки группы {row.service_id} расходятся с GTFS")
        services = tuple(
            _service(
                row,
                patterns[key],
                window,
                calendars[key],
                shapes[patterns[key].shape_id],
                trips[key],
            )
            for key, row in sorted(coverage.items())
        )
    except ArtifactError:
        raise
    except (BadZipFile, csv.Error, KeyError, TypeError, ValueError) as exc:
        raise ArtifactError(f"Повреждён комплект расписания OTP: {exc}") from exc
    return ScheduleSnapshot(version, window, services)


def load_release_schedule(release: Path, *, otp_image: str | None = None) -> ScheduleSnapshot:
    manifest = verify_release(release, otp_image=otp_image)
    return read_published_schedule(
        release / "all.gtfs.zip",
        (release / "coverage.json").read_bytes(),
        manifest.version,
        ServiceWindow(manifest.service_start, manifest.service_end),
    )
