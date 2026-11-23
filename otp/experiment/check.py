# /// script
# requires-python = ">=3.12"
# dependencies = ["gtfs-realtime-bindings==3.0.0", "protobuf==7.36.2"]
# ///
"""Пилот OTP 2.10.0: две копии GTFS №8 и управляемые GTFS-Realtime потоки."""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from zipfile import ZipFile

from google.transit import gtfs_realtime_pb2 as rt

ROOT = Path(__file__).resolve().parents[2]
SERVICE_DATE = "2026-11-24"
FEEDS = ("all", "low")
OPENER = build_opener(ProxyHandler({}))
PLAN_QUERY = """
query Pilot($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
            $time: OffsetDateTime!, $agency: String!) {
  planConnection(origin: $from, destination: $to, dateTime: {earliestDeparture: $time}
    first: 5, modes: {direct: [WALK], transit: {access: [WALK], egress: [WALK], transfer: [WALK]}}
    preferences: {
      transit: {
        filters: [{include: [{agencies: [$agency]}]}]
        board: {slack: "30s"}
        transfer: {slack: "60s", maximumTransfers: 2}
        timetable: {excludeRealTimeUpdates: false, includeRealTimeCancellations: false,
                    includePlannedCancellations: false}
      }
      street: {walk: {speed: 1.3}}
      accessibility: {wheelchair: {enabled: false}}
    }) {
    edges { node { legs { mode trip { gtfsId } } } }
  }
}
"""
TRIP_QUERY = """
query SelectedTrip($id: String!, $date: LocalDate!) {
  trip(id: $id) {
    onServiceDate(date: $date) {
      serviceDate
      stopCalls {
        stopLocation { ... on Stop { gtfsId } }
        schedule { time { ... on ArrivalDepartureTime { arrival departure } } }
        realTime { arrival { time } }
      }
    }
  }
}
"""


class _Leg(TypedDict):
    mode: str
    trip: dict[str, str] | None


class _Node(TypedDict):
    legs: list[_Leg]


class _Edge(TypedDict):
    node: _Node


class _Plan(TypedDict):
    edges: list[_Edge]


class _Schedule(TypedDict):
    time: dict[str, str]


class _Call(TypedDict):
    stopLocation: dict[str, str]
    schedule: _Schedule
    realTime: dict[str, dict[str, str] | None] | None


class _TripOnDate(TypedDict):
    serviceDate: str
    stopCalls: list[_Call]


def _graphql(query: str, variables: dict[str, object]) -> dict[str, object]:
    request = Request(
        "http://127.0.0.1:18800/otp/gtfs/v1",
        json.dumps({"query": query, "variables": variables}).encode(),
        {"Content-Type": "application/json"},
    )
    with OPENER.open(request, timeout=8) as response:
        body = json.load(response)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return cast(dict[str, object], body["data"])


def _read_csv(archive: ZipFile, name: str) -> list[dict[str, str]]:
    with io.TextIOWrapper(archive.open(name), encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _location(stop: dict[str, str]) -> dict[str, object]:
    point = {"latitude": float(stop["stop_lat"]), "longitude": float(stop["stop_lon"])}
    return {"location": {"coordinate": point}}


@dataclass(frozen=True)
class _Pilot:
    root: Path
    trips: tuple[str, ...]
    origin: dict[str, object]
    destination: dict[str, object]
    nearby: dict[str, object]

    @classmethod
    def load(cls, root: Path) -> _Pilot:
        with ZipFile(root / "graph/all.gtfs.zip") as archive:
            trips = tuple(row["trip_id"] for row in _read_csv(archive, "trips.txt"))
            stops = {row["stop_id"]: row for row in _read_csv(archive, "stops.txt")}
        if trips[:2] != ("bus-8-A-23-021660", "bus-8-A-23-022500"):
            raise ValueError("Ожидался пилотный GTFS №8 с первыми рейсами 06:01 и 06:15")
        return cls(
            root, trips, _location(stops["2223"]), _location(stops["47"]), _location(stops["645"])
        )

    def publish(
        self,
        feed: str,
        *,
        cancel_unconfirmed: bool = False,
        confirmed: str | None = None,
        delay: int | None = None,
    ) -> None:
        message = rt.FeedMessage()
        message.header.gtfs_realtime_version = "2.0"
        message.header.incrementality = rt.FeedHeader.FULL_DATASET
        message.header.timestamp = int(time.time())
        for trip in self.trips:
            if cancel_unconfirmed and trip != confirmed:
                _add_update(message, trip, delay=None)
            elif trip == confirmed and delay is not None:
                _add_update(message, trip, delay=delay)

        target = self.root / "rt" / f"{feed}.pb"
        staged = target.with_suffix(".tmp")
        staged.write_bytes(message.SerializeToString())  # type: ignore[no-untyped-call]
        staged.replace(target)

    def _plan(self, feed: str, departure: str, destination: dict[str, object]) -> _Plan:
        data = _graphql(
            PLAN_QUERY,
            {
                "from": self.origin,
                "to": destination,
                "time": f"{SERVICE_DATE}T{departure}:00+07:00",
                "agency": f"gopoint-{feed}:tsugaet",
            },
        )
        return cast(_Plan, data["planConnection"])

    def plan(self, feed: str, departure: str = "05:58") -> tuple[str, ...]:
        result = self._plan(feed, departure, self.destination)
        prefix = f"gopoint-{feed}:"
        trips = tuple(
            leg["trip"]["gtfsId"]
            for edge in result["edges"]
            for leg in edge["node"]["legs"]
            if leg["trip"] is not None
        )
        if any(not trip.startswith(prefix) for trip in trips):
            raise ValueError(f"Ответ содержит рейс другого фида: {trips}")
        return tuple(trip.removeprefix(prefix) for trip in trips)

    def can_walk(self) -> bool:
        result = self._plan("low", "05:58", self.nearby)
        return any(
            all(leg["mode"] == "WALK" for leg in edge["node"]["legs"])
            for edge in result["edges"]
            if edge["node"]["legs"]
        )


def _add_update(message: rt.FeedMessage, trip: str, *, delay: int | None) -> None:
    service_date = SERVICE_DATE.replace("-", "")
    entity = message.entity.add()
    entity.id = f"{trip}-{service_date}"
    update = entity.trip_update
    update.trip.trip_id = trip
    update.trip.start_date = service_date
    if delay is None:
        update.trip.schedule_relationship = rt.TripDescriptor.CANCELED
        return
    update.trip.schedule_relationship = rt.TripDescriptor.SCHEDULED
    call = update.stop_time_update.add()
    call.stop_sequence = 1
    call.departure.delay = delay


def _selected_trip(trip: str) -> _TripOnDate:
    data = _graphql(TRIP_QUERY, {"id": f"gopoint-all:{trip}", "date": SERVICE_DATE})
    result = cast(dict[str, _TripOnDate], data["trip"])
    return result["onServiceDate"]


def _wait_for(label: str, check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            if check():
                print(label, flush=True)
                return
        except URLError:
            # Контейнер может ещё загружать граф.
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Нет ожидаемого результата: {label}")


def _prepare(root: Path, feed: Path, osm: Path) -> None:
    root.mkdir()
    graph = root / "graph"
    graph.mkdir()
    (root / "rt").mkdir()
    shutil.copyfile(osm, graph / "novosibirsk.osm.pbf")
    for name in FEEDS:
        shutil.copyfile(feed, graph / f"{name}.gtfs.zip")
    build = json.loads((ROOT / "otp/build-config.json").read_bytes())
    build["transitFeeds"] = [
        {"type": "gtfs", "feedId": f"gopoint-{name}", "source": f"{name}.gtfs.zip"}
        for name in FEEDS
    ]
    (graph / "build-config.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    router = json.loads((ROOT / "otp/router-config.json").read_bytes())
    router["updaters"] = [
        {
            "type": "stop-time-updater",
            "feedId": f"gopoint-{name}",
            "url": f"http://fixture:9000/{name}.pb",
            "frequency": "2s",
            "fuzzyTripMatching": False,
        }
        for name in FEEDS
    ]
    (graph / "router-config.json").write_text(json.dumps(router, indent=2), encoding="utf-8")
    pilot = _Pilot.load(root)
    for name in FEEDS:
        pilot.publish(name)


def _check(pilot: _Pilot) -> None:
    first, second = pilot.trips[:2]
    for name in FEEDS:
        pilot.publish(name)
    _wait_for("OTP: в 05:58 первый рейс 06:01", lambda: pilot.plan("all")[:1] == (first,))
    _wait_for(
        "OTP: в 06:02 следующий рейс 06:15", lambda: pilot.plan("all", "06:02")[:1] == (second,)
    )

    pilot.publish("low", cancel_unconfirmed=True, confirmed=second)
    _wait_for(
        "Отмена действует только в low",
        lambda: pilot.plan("low") == (second,) and pilot.plan("all")[:1] == (first,),
    )
    pilot.publish("low", cancel_unconfirmed=True, confirmed=first, delay=0)
    _wait_for("Явное подтверждение вернуло рейс в low", lambda: pilot.plan("low") == (first,))

    selected = _selected_trip(first)
    if selected["serviceDate"] != SERVICE_DATE or len(selected["stopCalls"]) != 38:
        raise ValueError("Неверная дата или число остановок выбранного рейса")
    terminal = selected["stopCalls"][-1]
    if (
        terminal["stopLocation"]["gtfsId"] != "gopoint-all:76"
        or terminal["schedule"]["time"]["arrival"] != f"{SERVICE_DATE}T07:22:00+07:00"
    ):
        raise ValueError("Неверное плановое прибытие выбранного рейса")

    pilot.publish("all", confirmed=first, delay=120)

    def arrival_delayed() -> bool:
        realtime = _selected_trip(first)["stopCalls"][-1]["realTime"]
        arrival = realtime.get("arrival") if realtime else None
        return bool(arrival and arrival["time"] == f"{SERVICE_DATE}T07:24:00+07:00")

    _wait_for("Задержка выбранного рейса сдвинула прибытие с 07:22 до 07:24", arrival_delayed)

    pilot.publish("low")
    _wait_for(
        "Ограничение OTP: пустой FULL_DATASET вернул неподтверждённый рейс 06:15",
        lambda: second in pilot.plan("low"),
    )
    pilot.publish("low", cancel_unconfirmed=True)
    _wait_for(
        "Все рейсы low отменены, пеший маршрут и общий режим доступны",
        lambda: not pilot.plan("low") and pilot.can_walk() and bool(pilot.plan("all")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare")
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--feed", type=Path, required=True)
    prepare.add_argument("--osm", type=Path, default=ROOT / "data/otp/novosibirsk.osm.pbf")
    check = actions.add_parser("check")
    check.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        _prepare(args.root, args.feed, args.osm)
    else:
        _check(_Pilot.load(args.root))


if __name__ == "__main__":
    main()
