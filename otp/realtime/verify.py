"""Проверка обновлений расписания в контрольном Docker-проекте."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import TypedDict, cast

import httpx

DAY = "2026-11-24"
TRIP = "bus-8-A-23-021660"
OTP = "http://127.0.0.1:18821/otp/gtfs/v1"
WEB = "http://127.0.0.1:18822"
FEEDS = "{ feeds { feedId version } }"
PLAN = """
query CheckPlan($agency: String!) {
  planConnection(
    origin: {location: {coordinate: {latitude: 54.8396143, longitude: 83.0880278}}}
    destination: {location: {coordinate: {latitude: 55.0075878, longitude: 82.9379628}}}
    dateTime: {earliestDeparture: "2026-11-24T05:58:00+07:00"}
    first: 5
    modes: {direct: [WALK], transit: {access: [WALK], egress: [WALK], transfer: [WALK]}}
    preferences: {transit: {
      filters: [{include: [{agencies: [$agency]}]}]
      timetable: {excludeRealTimeUpdates: false, includeRealTimeCancellations: false}
    }}
  ) { edges { node { legs { trip { gtfsId } } } } }
}
"""
CALLS = """
query CheckCalls($id: String!, $date: LocalDate!) {
  trip(id: $id) { onServiceDate(date: $date) { stopCalls {
    schedule { time { ... on ArrivalDepartureTime { arrival } } }
    realTime { arrival { time } }
  } } }
}
"""


class _Call(TypedDict):
    schedule: dict[str, dict[str, str]]
    realTime: dict[str, dict[str, str] | None] | None


class _Leg(TypedDict):
    trip: dict[str, str] | None


class _Edge(TypedDict):
    node: dict[str, list[_Leg]]


def _graphql(client: httpx.Client, query: str, variables: dict[str, str]) -> dict[str, object]:
    response = client.post(OTP, json={"query": query, "variables": variables})
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return cast(dict[str, object], body["data"])


def _trips(client: httpx.Client, feed: str) -> set[str]:
    data = _graphql(client, PLAN, {"agency": f"gopoint-{feed}:tsugaet"})
    plan = cast(dict[str, list[_Edge]], data["planConnection"])
    return {
        trip["gtfsId"]
        for edge in plan["edges"]
        for leg in edge["node"]["legs"]
        if (trip := leg["trip"]) is not None
    }


def _versions(client: httpx.Client) -> dict[str, str | None]:
    data = _graphql(client, FEEDS, {})
    feeds = cast(list[dict[str, str | None]], data["feeds"])
    return {str(feed["feedId"]): feed["version"] for feed in feeds}


def _delays(client: httpx.Client, feed: str) -> tuple[int, ...]:
    data = _graphql(client, CALLS, {"id": f"gopoint-{feed}:{TRIP}", "date": DAY})
    trip = cast(dict[str, dict[str, list[_Call]]], data["trip"])
    delays = []
    for call in trip["onServiceDate"]["stopCalls"][:3]:
        realtime = call["realTime"]
        planned = call["schedule"]["time"]["arrival"]
        expected = realtime.get("arrival") if realtime else None
        actual = expected["time"] if expected else planned
        delays.append(
            int((datetime.fromisoformat(actual) - datetime.fromisoformat(planned)).total_seconds())
        )
    return tuple(delays)


def _wait_for(label: str, check: Callable[[], bool]) -> None:
    deadline = monotonic() + 45
    while monotonic() < deadline:
        try:
            if check():
                print(label, flush=True)
                return
        except (httpx.TransportError, httpx.HTTPStatusError):
            pass
        sleep(0.5)
    raise RuntimeError(f"Нет ожидаемого результата: {label}")


def _step(client: httpx.Client, path: Path, step: int, *, complete: bool) -> None:
    # Одна цифра без замены файла. Bind mount Docker Desktop может увидеть
    # промежуточное отсутствие файла при переименовании на Mac.
    with path.open("r+b", buffering=0) as stream:
        stream.write(str(step).encode("ascii"))
    response = client.get(f"{WEB}/api/v1/live/vehicles")
    response.raise_for_status()
    if response.json()["diagnostics"]["complete"] is not complete:
        raise RuntimeError(f"Неожиданное состояние GPS на шаге {step}")


def verify(directory: Path, version: str, phase: str) -> None:
    path = directory / "scenario" / "step"
    all_trip = f"gopoint-all:{TRIP}"
    low_trip = f"gopoint-low:{TRIP}"
    with httpx.Client(trust_env=False, timeout=10) as client:
        _wait_for("GoPoint запущен", lambda: client.get(f"{WEB}/health").is_success)
        if client.get(f"{WEB}/internal/gtfs-rt/all").status_code != 404:
            raise RuntimeError("Caddy не вернул 404 для внутреннего фида")
        _wait_for(
            f"OTP загрузил оба фида версии {version[:8]}",
            lambda: _versions(client) == {"gopoint-all": version, "gopoint-low": version},
        )
        current = path.read_text(encoding="ascii").strip()
        if phase == "reset":
            if current != "2":
                raise RuntimeError("Для проверки сброса оставьте последнюю отметку на шаге 2")
            _step(client, path, 2, complete=True)
            _wait_for(
                "Новый процесс сбросил подтверждение и задержку предыдущей версии",
                lambda: (
                    _delays(client, "all") == (0, 0, 0)
                    and all_trip in _trips(client, "all")
                    and not _trips(client, "low")
                ),
            )
            return
        if current != "0":
            raise RuntimeError("Начните со свежих контейнеров на шаге 0")
        _step(client, path, 0, complete=True)
        _wait_for(
            "Без GPS: №8 по расписанию в общем фиде, low пуст",
            lambda: all_trip in _trips(client, "all") and not _trips(client, "low"),
        )
        _step(client, path, 1, complete=True)
        sleep(2)
        _step(client, path, 2, complete=True)
        _wait_for(
            "Подтверждённый №8: задержка 120 с с третьей остановки в обоих фидах",
            lambda: (
                _delays(client, "all") == _delays(client, "low") == (0, 0, 120)
                and low_trip in _trips(client, "low")
            ),
        )
        if phase == "confirm":
            return
        _step(client, path, 3, complete=True)
        _wait_for(
            "После ramp=0: low пуст, общий сохраняет задержку №8",
            lambda: not _trips(client, "low") and _delays(client, "all") == (0, 0, 120),
        )
        _step(client, path, 4, complete=False)
        _wait_for(
            "Сбой GPS и истечение срока: плановый №8 остаётся в общем фиде, low пуст",
            lambda: (
                _delays(client, "all") == (0, 0, 0)
                and all_trip in _trips(client, "all")
                and not _trips(client, "low")
            ),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("version")
    parser.add_argument("--phase", choices=("full", "confirm", "reset"), default="full")
    args = parser.parse_args()
    verify(args.directory, args.version, args.phase)
