"""Управляемые рейсы на остановках пилота для проверки OTP около полуночи."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZipFile, ZipInfo

LAB_TRIPS = ("lab-first", "lab-second", "lab-third")
LAB_TRANSFER = "734"
LAB_DESTINATION = "76"
DAY_COLUMNS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

type Row = dict[str, str]


def read_csv(archive: ZipFile, name: str) -> list[Row]:
    with io.TextIOWrapper(archive.open(name), encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(archive: ZipFile, name: str, rows: list[Row]) -> None:
    with io.StringIO(newline="") as stream:
        writer = csv.DictWriter(stream, tuple(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        archive.writestr(ZipInfo(name), stream.getvalue().encode())


def _service_days(row: Row) -> tuple[date, ...]:
    first = date.fromisoformat(row["start_date"])
    last = date.fromisoformat(row["end_date"])
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    return tuple(day for day in days if row[DAY_COLUMNS[day.weekday()]] == "1")


def active_dates(archive: ZipFile) -> dict[str, tuple[date, ...]]:
    service_days = {
        row["service_id"]: _service_days(row) for row in read_csv(archive, "calendar.txt")
    }
    return {
        row["trip_id"]: service_days[row["service_id"]] for row in read_csv(archive, "trips.txt")
    }


def _clock(minutes: int) -> str:
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:00"


def _stop_times(trip: str, stops: list[str], start: int, end: int) -> list[Row]:
    times: list[Row] = []
    for index, stop in enumerate(stops):
        clock = _clock(start + (end - start) * index // (len(stops) - 1))
        times.append(
            {
                "trip_id": trip,
                "arrival_time": clock,
                "departure_time": clock,
                "stop_id": stop,
                "stop_sequence": str(index + 1),
            }
        )
    return times


def write_experiment_feed(pilot: Path, target: Path, version: str) -> tuple[date, date]:
    with ZipFile(pilot) as original, ZipFile(target, "w") as archive:
        routes = read_csv(original, "routes.txt")
        trips = read_csv(original, "trips.txt")
        times = read_csv(original, "stop_times.txt")
        info = read_csv(original, "feed_info.txt")
        stop_ids = [row["stop_id"] for row in times if row["trip_id"] == trips[0]["trip_id"]]
        if stop_ids[13] != LAB_TRANSFER or stop_ids[-1] != LAB_DESTINATION:
            raise ValueError("Не совпали площадки пересадки и конца экспериментальной цепочки")

        # Второй визит на 645 отделён другой площадкой, чтобы проверить его позицию в рейсе.
        legs = [
            ([*stop_ids[:3], stop_ids[1], *stop_ids[3:14]], 23 * 60 + 31, 24 * 60 + 2),
            (stop_ids[13:24], 24 * 60 + 5, 24 * 60 + 25),
            (stop_ids[23:], 24 * 60 + 28, 24 * 60 + 51),
        ]
        for trip_id, (stops, start, end) in zip(LAB_TRIPS, legs, strict=True):
            routes.append(dict(routes[0], route_id=trip_id, route_short_name=trip_id))
            trips.append(dict(trips[0], trip_id=trip_id, route_id=trip_id, shape_id=""))
            times.extend(_stop_times(trip_id, stops, start, end))

        (feed_info,) = info
        feed_info["feed_version"] = version
        tables = {
            "routes.txt": routes,
            "trips.txt": trips,
            "stop_times.txt": times,
            "feed_info.txt": info,
        }
        for name in original.namelist():
            if name in tables:
                _write_csv(archive, name, tables[name])
            else:
                archive.writestr(ZipInfo(name), original.read(name))

    return date.fromisoformat(feed_info["feed_start_date"]), date.fromisoformat(
        feed_info["feed_end_date"]
    )
