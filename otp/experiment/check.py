# /// script
# requires-python = ">=3.12"
# dependencies = ["gtfs-realtime-bindings==3.0.0", "protobuf==7.36.2"]
# ///
"""Пилот OTP 2.10.0: две копии GTFS №8 и управляемые GTFS-Realtime потоки."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from http.client import RemoteDisconnected
from pathlib import Path
from typing import TypedDict, cast
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from zipfile import ZipFile

from app.domain.low_floor import LowFloorSnapshot, TripOccurrence, allows_low_floor
from fixtures import (
    LAB_DESTINATION,
    LAB_TRANSFER,
    LAB_TRIPS,
    active_dates,
    read_csv,
    write_experiment_feed,
)
from google.transit import gtfs_realtime_pb2 as rt

ROOT = Path(__file__).resolve().parents[2]
SERVICE_DATE = date(2026, 11, 24)
LAB_REQUEST = f"{SERVICE_DATE}T22:54:00+07:00"
FEEDS = ("all", "low")
OPENER = build_opener(ProxyHandler({}))
PLAN_QUERY = """
query Pilot($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
            $time: OffsetDateTime!, $agency: String!) {
  feeds { feedId version }
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
    routingErrors { code }
    edges { node { legs { mode serviceDate trip { gtfsId } } } }
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
    serviceDate: str | None


class _Feed(TypedDict):
    feedId: str
    version: str | None


class _Node(TypedDict):
    legs: list[_Leg]


class _Edge(TypedDict):
    node: _Node


class _Plan(TypedDict):
    edges: list[_Edge]
    routingErrors: list[dict[str, str]]


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


def _location(stop: dict[str, str]) -> dict[str, object]:
    point = {"latitude": float(stop["stop_lat"]), "longitude": float(stop["stop_lon"])}
    return {"location": {"coordinate": point}}


@dataclass(frozen=True)
class _Pilot:
    root: Path
    trips: tuple[str, ...]
    active_dates: dict[str, tuple[date, ...]]
    locations: dict[str, dict[str, object]]

    @classmethod
    def load(cls, root: Path) -> _Pilot:
        with ZipFile(root / "graph/all.gtfs.zip") as archive:
            dates = active_dates(archive)
            trips = tuple(dates)
            locations = {row["stop_id"]: _location(row) for row in read_csv(archive, "stops.txt")}
        if trips[:2] != ("bus-8-A-23-021660", "bus-8-A-23-022500"):
            raise ValueError("Ожидался пилотный GTFS №8 с первыми рейсами 06:01 и 06:15")
        return cls(root, trips, dates, locations)

    def publish(
        self,
        feed: str,
        *,
        cancel_unconfirmed: bool = False,
        confirmed: Collection[TripOccurrence] = (),
        delays: Mapping[TripOccurrence, int] | None = None,
    ) -> int:
        message = rt.FeedMessage()
        message.header.gtfs_realtime_version = "2.0"
        message.header.incrementality = rt.FeedHeader.FULL_DATASET
        message.header.timestamp = int(time.time())
        for trip, dates in self.active_dates.items():
            for day in dates:
                occurrence = TripOccurrence(trip, day)
                delay = delays.get(occurrence) if delays is not None else None
                if cancel_unconfirmed and occurrence not in confirmed:
                    _add_update(message, occurrence, delay=None)
                elif delay is not None:
                    _add_update(message, occurrence, delay=delay)

        target = self.root / "rt" / f"{feed}.pb"
        staged = target.with_suffix(".tmp")
        payload = message.SerializeToString()  # type: ignore[no-untyped-call]
        size = staged.write_bytes(payload)
        staged.replace(target)
        return size

    def _plan(
        self, feed: str, departure: str, origin: str, destination: str
    ) -> tuple[str | None, _Plan]:
        data = _graphql(
            PLAN_QUERY,
            {
                "from": self.locations[origin],
                "to": self.locations[destination],
                "time": departure,
                "agency": f"gopoint-{feed}:tsugaet",
            },
        )
        versions = {item["feedId"]: item["version"] for item in cast(list[_Feed], data["feeds"])}
        version = versions.get("gopoint-all")
        agreed = version if version == versions.get("gopoint-low") else None
        return agreed, cast(_Plan, data["planConnection"])

    def plan(self, feed: str, departure: str = "05:58") -> tuple[str, ...]:
        _, journeys = self.journeys(feed, f"{SERVICE_DATE}T{departure}:00+07:00", "2223", "47")
        return tuple(leg.trip_id for journey in journeys for leg in journey)

    def journeys(
        self, feed: str, departure: str, origin: str, destination: str
    ) -> tuple[str | None, tuple[tuple[TripOccurrence, ...], ...]]:
        version, result = self._plan(feed, departure, origin, destination)
        prefix = f"gopoint-{feed}:"
        journeys = []
        for edge in result["edges"]:
            boardings = []
            for leg in edge["node"]["legs"]:
                if leg["trip"] is None:
                    if leg["mode"] != "WALK":
                        raise ValueError("Транспортный участок без идентификатора рейса")
                    continue
                trip_id = leg["trip"]["gtfsId"]
                service_date = leg["serviceDate"]
                if not trip_id.startswith(prefix) or service_date is None:
                    raise ValueError(f"Чужой фид или отсутствующая дата рейса: {trip_id}")
                boardings.append(
                    TripOccurrence(trip_id.removeprefix(prefix), date.fromisoformat(service_date))
                )
            journeys.append(tuple(boardings))
        return version, tuple(journeys)

    def can_walk(self) -> bool:
        _, result = self._plan("low", f"{SERVICE_DATE}T05:58:00+07:00", "2223", "645")
        return any(
            all(leg["mode"] == "WALK" for leg in edge["node"]["legs"])
            for edge in result["edges"]
            if edge["node"]["legs"]
        )


def _add_update(message: rt.FeedMessage, trip: TripOccurrence, *, delay: int | None) -> None:
    service_date = trip.service_date.strftime("%Y%m%d")
    entity = message.entity.add()
    entity.id = f"{trip.trip_id}-{service_date}"
    update = entity.trip_update
    update.trip.trip_id = trip.trip_id
    update.trip.start_date = service_date
    if delay is None:
        update.trip.schedule_relationship = rt.TripDescriptor.CANCELED
        return
    update.trip.schedule_relationship = rt.TripDescriptor.SCHEDULED
    call = update.stop_time_update.add()
    call.stop_sequence = 1
    call.departure.delay = delay


def _selected_trip(trip: TripOccurrence) -> _TripOnDate:
    data = _graphql(
        TRIP_QUERY, {"id": f"gopoint-all:{trip.trip_id}", "date": trip.service_date.isoformat()}
    )
    result = cast(dict[str, _TripOnDate], data["trip"])
    return result["onServiceDate"]


def _wait_for(label: str, check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            if check():
                print(label, flush=True)
                return
        except (URLError, RemoteDisconnected, TimeoutError):
            # Контейнер может ещё загружать граф.
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Нет ожидаемого результата: {label}")


def _prepare(root: Path, feed: Path, osm: Path, version: str) -> None:
    root.mkdir()
    graph = root / "graph"
    graph.mkdir()
    (root / "rt").mkdir()
    shutil.copyfile(osm, graph / "novosibirsk.osm.pbf")
    start, end = write_experiment_feed(feed, graph / "all.gtfs.zip", version)
    shutil.copyfile(graph / "all.gtfs.zip", graph / "low.gtfs.zip")
    build = json.loads((ROOT / "otp/build-config.json").read_bytes())
    build.update(transitServiceStart=start.isoformat(), transitServiceEnd=end.isoformat())
    build["transitFeeds"] = [
        {"type": "gtfs", "feedId": f"gopoint-{name}", "source": f"{name}.gtfs.zip"}
        for name in FEEDS
    ]
    (graph / "build-config.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    router = json.loads((ROOT / "otp/router-config.json").read_bytes())
    router["timetableUpdates"] = {"purgeExpiredData": False}
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
    first_run = TripOccurrence(first, SERVICE_DATE)
    second_run = TripOccurrence(second, SERVICE_DATE)
    for name in FEEDS:
        pilot.publish(name)
    _wait_for("OTP: в 05:58 первый рейс 06:01", lambda: pilot.plan("all")[:1] == (first,))
    _wait_for(
        "OTP: в 06:02 следующий рейс 06:15", lambda: pilot.plan("all", "06:02")[:1] == (second,)
    )

    pilot.publish("low", cancel_unconfirmed=True, confirmed=(second_run,))
    _wait_for(
        "Отмена действует только в low",
        lambda: pilot.plan("low") == (second,) and pilot.plan("all")[:1] == (first,),
    )
    pilot.publish("low", cancel_unconfirmed=True, confirmed=(first_run,), delays={first_run: 0})
    _wait_for("Явное подтверждение вернуло рейс в low", lambda: pilot.plan("low") == (first,))

    selected = _selected_trip(first_run)
    if selected["serviceDate"] != SERVICE_DATE.isoformat() or len(selected["stopCalls"]) != 38:
        raise ValueError("Неверная дата или число остановок выбранного рейса")
    terminal = selected["stopCalls"][-1]
    if (
        terminal["stopLocation"]["gtfsId"] != "gopoint-all:76"
        or terminal["schedule"]["time"]["arrival"] != f"{SERVICE_DATE}T07:22:00+07:00"
    ):
        raise ValueError("Неверное плановое прибытие выбранного рейса")

    pilot.publish("all", delays={first_run: 120})

    def arrival_delayed() -> bool:
        realtime = _selected_trip(first_run)["stopCalls"][-1]["realTime"]
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


def _lab_journeys(
    pilot: _Pilot, feed: str
) -> tuple[str | None, tuple[tuple[TripOccurrence, ...], ...]]:
    return pilot.journeys(feed, LAB_REQUEST, "2223", LAB_DESTINATION)


def _missing_from_low(pilot: _Pilot, run: TripOccurrence) -> bool:
    return all(run not in options for options in _lab_journeys(pilot, "low")[1])


def _check_calendar(pilot: _Pilot) -> None:
    first, *_, last = pilot.active_dates[LAB_TRIPS[0]]
    for day in (first, last):
        _, journeys = pilot.journeys("all", f"{day}T22:54:00+07:00", "2223", LAB_DESTINATION)
        if tuple(TripOccurrence(trip, day) for trip in LAB_TRIPS) not in journeys:
            raise ValueError(f"Нет цепочки на границе календаря: {day}")
    after = last + timedelta(days=1)
    _, plan = pilot._plan("all", f"{after}T00:03:00+07:00", LAB_TRANSFER, LAB_DESTINATION)
    if {issue["code"] for issue in plan["routingErrors"]} != {"OUTSIDE_SERVICE_PERIOD"}:
        raise ValueError("Не воспроизведена граница доступности последнего дня обслуживания")
    print(f"Календарь: {first}–{last}; в {after} 00:03 OTP вернул OUTSIDE_SERVICE_PERIOD")


def _check_transfers(pilot: _Pilot) -> tuple[TripOccurrence, ...]:
    chain = tuple(TripOccurrence(trip, SERVICE_DATE) for trip in LAB_TRIPS)
    next_date = SERVICE_DATE + timedelta(days=1)
    submitted = f"{next_date}T00:03:00+07:00"
    next_chain = tuple(TripOccurrence(trip, next_date) for trip in LAB_TRIPS)

    _wait_for(
        "Общий фид: две пересадки, 24:05 и 24:28", lambda: chain in _lab_journeys(pilot, "all")[1]
    )
    _, midnight = pilot.journeys("all", submitted, LAB_TRANSFER, LAB_DESTINATION)
    _, tomorrow = pilot.journeys("all", f"{next_date}T22:54:00+07:00", "2223", LAB_DESTINATION)
    if chain[1:] not in midnight or next_chain not in tomorrow:
        raise ValueError("OTP не различил дату обслуживания и календарную дату второй посадки")
    print("00:03: рейсы предыдущих суток; через день те же ID с новой датой")
    _check_calendar(pilot)

    calls = _selected_trip(chain[0])["stopCalls"]
    visits = tuple(
        (index, call["schedule"]["time"]["departure"])
        for index, call in enumerate(calls, start=1)
        if call["stopLocation"]["gtfsId"] == "gopoint-all:645"
    )
    if visits != (
        (2, f"{SERVICE_DATE}T23:33:00+07:00"),
        (4, f"{SERVICE_DATE}T23:37:00+07:00"),
    ):
        raise ValueError(f"Неверные позиции повторной площадки: {visits}")
    print("Выбранный рейс: площадка 645 возвращена дважды с разными временами и позициями")

    pilot.publish("all", delays={chain[0]: 300})
    _wait_for(
        "Задержка 300 с сорвала пересадку в 24:05",
        lambda: chain not in _lab_journeys(pilot, "all")[1],
    )
    pilot.publish("all")
    _wait_for(
        "Сброс задержки восстановил пересадку", lambda: chain in _lab_journeys(pilot, "all")[1]
    )

    pilot.publish("low", cancel_unconfirmed=True, confirmed=chain)
    _wait_for("Low: подтверждены все три посадки", lambda: chain in _lab_journeys(pilot, "low")[1])
    for missing in chain[1:]:
        size = pilot.publish(
            "low", cancel_unconfirmed=True, confirmed=tuple(run for run in chain if run != missing)
        )
        _wait_for(
            f"Low: отмена поздней посадки {missing.trip_id} убрала цепочку ({size} байт)",
            partial(_missing_from_low, pilot, missing),
        )
        pilot.publish("low", cancel_unconfirmed=True, confirmed=chain)
        _wait_for(
            f"Low: возврат {missing.trip_id} восстановил цепочку",
            lambda: chain in _lab_journeys(pilot, "low")[1],
        )
    return chain


def _compose(root: Path, *args: str) -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker нужен для проверки перезапуска OTP")
    result = subprocess.run(  # noqa: S603 — аргументы локального Compose-проекта
        [
            docker,
            "compose",
            "--env-file",
            "/dev/null",
            "-p",
            "gopoint-otp-exp",
            "-f",
            str(ROOT / "otp/experiment/compose.yml"),
            *args,
        ],
        env={**os.environ, "GOPOINT_OTP_EXPERIMENT_DIR": str(root.resolve())},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _check_recovery(pilot: _Pilot, chain: tuple[TripOccurrence, ...], replacement: Path) -> None:
    version, journeys = _lab_journeys(pilot, "low")
    if not version or chain not in journeys:
        raise ValueError("Для проверки отказа нужна подтверждённая цепочка")
    now = datetime(2026, 11, 24, 15, 54, tzinfo=UTC)
    expires = now + timedelta(seconds=10)
    snapshot = LowFloorSnapshot(version, expires, dict.fromkeys(chain, expires))

    def admits(
        target: tuple[TripOccurrence, ...],
        otp_version: str | None,
        current: LowFloorSnapshot | None,
        at: datetime = now,
    ) -> bool:
        return allows_low_floor(
            target, otp_version=otp_version, requested=snapshot, current=current, now=at
        )

    if not admits(chain, version, snapshot):
        raise ValueError("Свежая подтверждённая цепочка должна пройти проверку")

    missing_last = LowFloorSnapshot(version, expires, dict.fromkeys(chain[:-1], expires))
    if allows_low_floor(
        chain, otp_version=version, requested=missing_last, current=missing_last, now=now
    ):
        raise ValueError("Отставший OTP пропустил позднюю посадку после потери подтверждения")
    print("Отставший OTP: старый маршрут отфильтрован по третьей посадке")

    missing_log = 'GET /low.pb HTTP/1.1" 404'
    previous_errors = _compose(pilot.root, "logs", "fixture").count(missing_log)
    (pilot.root / "rt/low.pb").unlink()
    _wait_for(
        "Updater получил 404",
        lambda: _compose(pilot.root, "logs", "fixture").count(missing_log) > previous_errors,
    )
    version, journeys = _lab_journeys(pilot, "low")
    if chain not in journeys or admits(chain, version, snapshot, expires):
        raise ValueError("Неверный результат проверки отказа и истечения TTL")
    print("OTP сохранил предыдущий ответ при 404; просроченный маршрут запрещён")

    _compose(pilot.root, "restart", "otp")
    _wait_for(
        "Холодный OTP снова видит плановые рейсы low при 404",
        lambda: chain in _lab_journeys(pilot, "low")[1],
    )
    if admits(chain, version, None):
        raise ValueError("Рейс допущен при холодном старте без готового снимка")

    graph = pilot.root / "graph/graph.obj"
    staged = graph.with_suffix(".tmp")
    shutil.copyfile(replacement / "graph/graph.obj", staged)
    staged.replace(graph)
    _compose(pilot.root, "restart", "otp")

    def switched() -> bool:
        loaded, candidates = _lab_journeys(pilot, "low")
        return bool(
            loaded
            and loaded != snapshot.graph_version
            and chain in candidates
            and not admits(chain, loaded, snapshot)
        )

    _wait_for("Новая версия графа видна в обоих фидах, прежние подтверждения отклонены", switched)
    pilot.publish("low", cancel_unconfirmed=True, confirmed=chain)
    _wait_for(
        "После перезапуска применён полный набор отмен нового графа",
        lambda: not pilot.plan("low") and chain in _lab_journeys(pilot, "low")[1],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare")
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--feed", type=Path, required=True)
    prepare.add_argument("--osm", type=Path, default=ROOT / "data/otp/novosibirsk.osm.pbf")
    prepare.add_argument("--version", default="gopoint-experiment-a")
    check = actions.add_parser("check")
    check.add_argument("root", type=Path)
    check.add_argument("--replacement", type=Path, help="Каталог собранного графа другой версии")
    args = parser.parse_args()
    if args.action == "prepare":
        _prepare(args.root, args.feed, args.osm, args.version)
    else:
        pilot = _Pilot.load(args.root)
        _check(pilot)
        chain = _check_transfers(pilot)
        if args.replacement is not None:
            _check_recovery(pilot, chain, args.replacement)


if __name__ == "__main__":
    main()
