#!/usr/bin/env python3
"""Утилита для данных сайта ЦУГАЭТ (map.nskgortrans.ru). Без зависимостей: только Python 3.9+.

Запуск:   python3 nskgortrans.py <команда> [параметры]
Вывод:    JSON в stdout (UTF-8). Ошибки идут текстом в stderr, код выхода 1.
Описание сайта и всех полей: NSKGORTRANS.md (лежит рядом).

Команды:
  routes    [--type bus|trolleybus|tram|minibus]          список маршрутов с ключом r
  vehicles  [--route N --type T] [--low-floor] [--include-hidden] [--raw]
  trace     --route N --type T [--direction A|B|W] [--points]
  forecast  --stop STOP_ID [--raw]
  check     проверить, что формат ответов сайта не поменялся
  snapshot  [--out DIR]   сохранить сырые ответы сайта (образцы для тестов)

Бережём сервер ЦУГАЭТ: команду vehicles без --route (~18 запросов) запускайте
не чаще раза в 30 секунд. Их собственный сайт обновляет данные раз в 30 секунд.

Файл можно и импортировать: функции parse_* чистые (без сети), их удобно
переносить в другой язык или проект и покрывать тестами на образцах из samples/.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

BASE_URL = "https://map.nskgortrans.ru"
USER_AGENT = "nsk-lowfloor/0.1"
# markers.php отдаёт машины не больше чем по 6 маршрутам за запрос (проверено 2026-11-04).
MARKERS_MAX_ROUTES = 6
# Новосибирск: UTC+7 круглый год (переходов на летнее время нет с 2016 года).
# Фиксированный сдвиг, чтобы не зависеть от пакета tzdata (на Windows его нет).
NOVOSIBIRSK = timezone(timedelta(hours=7), "Asia/Novosibirsk")
UTC = timezone.utc

# Код вида транспорта в markers/trasses/forecast. В listmarsh.php он на 1 меньше.
TYPE_CODES = {"bus": 1, "trolleybus": 2, "tram": 3, "minibus": 8}
TYPE_NAMES = {code: name for name, code in TYPE_CODES.items()}


class SiteError(Exception):
    """Сайт не ответил или ответил не в том формате."""


# ---------------------------------------------------------------- модели


@dataclass(frozen=True)
class Route:
    """Маршрут из listmarsh.php."""

    type: str  # bus | trolleybus | tram | minibus
    type_code: int  # 1, 2, 3, 8
    marsh: str  # внутренний код ЦУГАЭТ ("0013" у трамвая 13)
    name: str  # номер для людей ("13", "45К")
    stop_begin: str
    stop_end: str  # пусто у кольцевых

    def key(self, direction: str = "W") -> str:
        return route_key(self.type_code, self.marsh, self.name, direction)


@dataclass(frozen=True)
class PlannedStop:
    at_utc: str  # ISO 8601
    at_local: str  # ЧЧ:ММ по Новосибирску
    stop_name: str


@dataclass(frozen=True)
class Vehicle:
    """Машина из markers.php."""

    id: str  # "тип-код-выход", например "1-3-12": устойчив в течение дня
    type: str
    route: str  # номер для людей
    marsh: str
    graph: str  # номер выхода (наряда)
    direction: str  # A или B
    lat: float
    lon: float
    recorded_at_utc: str  # момент GPS-отметки
    recorded_at_local: str
    azimuth: float
    speed_kmh: float
    segment_order: int  # примерно: сколько остановок направления уже проехала
    ramp: Optional[bool]  # True: низкий пол/аппарель, False: нет, None: нет данных
    accessibility: str  # yes | no | unknown (из ramp)
    state: str  # on_route | no_plan | parked | lunch
    on_line: bool  # показал бы её сайт ЦУГАЭТ
    plan: Tuple[PlannedStop, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TraceStop:
    order: int
    id: str  # нужен для forecast.php
    name: str
    lat: float
    lon: float
    point_index: int  # номер точки в линии маршрута


@dataclass(frozen=True)
class Trace:
    marsh: str
    points: Tuple[Tuple[float, float], ...]  # (lat, lon) по порядку движения
    stops: Tuple[TraceStop, ...]


@dataclass(frozen=True)
class Forecast:
    route_id: str  # id_marsh
    route: str
    marsh: str
    type: str
    direction: str
    minutes: Tuple[int, ...]  # через сколько минут придут машины
    stop_end: str


# ---------------------------------------------------------------- разбор (чистые функции)


def route_key(type_code: int, marsh: str, name: str, direction: str = "W") -> str:
    """Ключ маршрута для параметра r: «тип-код-направление-номер|».
    direction: A прямое, B обратное, W оба. Ключи склеиваются подряд."""
    if direction not in ("A", "B", "W"):
        raise ValueError(f"направление должно быть A, B или W, а не {direction!r}")
    return f"{type_code}-{marsh}-{direction}-{name}|"


def _s(item: Dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise ValueError(f"поле {key} не строка: {value!r}")
    return value


def parse_routes(data: Any) -> List[Route]:
    if not isinstance(data, list):
        raise ValueError("listmarsh: ожидался список групп")
    routes = []
    for group in data:
        if not isinstance(group, dict) or not isinstance(group.get("ways"), list):
            raise ValueError("listmarsh: группа без ways")
        if not isinstance(group.get("type"), int):
            raise ValueError("listmarsh: type не число")
        code = group["type"] + 1  # в listmarsh 0,1,2,7, везде остальном 1,2,3,8
        if code not in TYPE_NAMES:
            continue  # неизвестный вид транспорта: пропускаем, а не падаем
        for way in group["ways"]:
            routes.append(
                Route(
                    type=TYPE_NAMES[code],
                    type_code=code,
                    marsh=_s(way, "marsh"),
                    name=_s(way, "name"),
                    stop_begin=_s(way, "stopb"),
                    stop_end=_s(way, "stope"),
                )
            )
    return routes


_TIME_NAV = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})$")


def parse_time_nav(value: str) -> datetime:
    """'27.10.26 17:33:09' (местное время Новосибирска) -> datetime в UTC."""
    m = _TIME_NAV.match(value)
    if m is None:
        raise ValueError(f"time_nav: неверный формат {value!r}")
    d, mo, y, h, mi, s = (int(x) for x in m.groups())
    return datetime(2000 + y, mo, d, h, mi, s, tzinfo=NOVOSIBIRSK).astimezone(UTC)


_RASP_ITEM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)\+(.+)$")
_SPECIAL_RASP = {
    "-": "no_plan",
    "": "no_plan",
    "отстой": "parked",
    "идет на обед": "lunch",
    "обеденный+перерыв|": "lunch",
    "обеденный перерыв": "lunch",
}


def nearest_moment(hour: int, minute: int, reference: datetime) -> datetime:
    """ЧЧ:ММ по Новосибирску, ближайшее к reference (±12 ч). Так 00:07 после 23:55
    попадает на следующие сутки, а 23:58 после 00:05 на предыдущие."""
    local = reference.astimezone(NOVOSIBIRSK)
    cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if cand - local > timedelta(hours=12):
        cand -= timedelta(days=1)
    elif local - cand > timedelta(hours=12):
        cand += timedelta(days=1)
    return cand.astimezone(UTC)


def parse_rasp(text: str, reference: datetime) -> Tuple[str, Tuple[PlannedStop, ...]]:
    """'17:22+Остановка|17:28+Другая|' -> (состояние, план на ближайших остановках)."""
    special = _SPECIAL_RASP.get(text.strip().casefold())
    if special is not None:
        return special, ()
    plan = []
    for item in text.split("|"):
        m = _RASP_ITEM.match(item.strip())
        if m is None:
            continue
        at = nearest_moment(int(m.group(1)), int(m.group(2)), reference)
        plan.append(
            PlannedStop(
                at_utc=_iso(at),
                at_local=at.astimezone(NOVOSIBIRSK).strftime("%H:%M"),
                stop_name=m.group(3).strip(),
            )
        )
    return ("on_route", tuple(plan)) if plan else ("no_plan", ())


def is_on_line(type_code: int, marsh: str, state: str) -> bool:
    """Правило сайта ЦУГАЭТ (GoTransport в main.1.3.min.js): скрыты машины на отстое
    и обеде, а без плана ("-") скрыты все, кроме маршруток и автобуса 24."""
    if state in ("parked", "lunch"):
        return False
    if state == "no_plan":
        return type_code == 8 or (type_code == 1 and marsh == "24")
    return True


def ramp_to_accessibility(ramp: Any) -> Tuple[Optional[bool], str]:
    """Строго: только "1" = yes, только "0" = no, всё остальное = unknown."""
    if ramp == "1":
        return True, "yes"
    if ramp == "0":
        return False, "no"
    return None, "unknown"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vehicle(item: Dict[str, Any]) -> Vehicle:
    lat, lon = float(_s(item, "lat")), float(_s(item, "lng"))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        raise ValueError("неверные координаты")
    code = int(_s(item, "id_typetr"))
    if code not in TYPE_NAMES:
        raise ValueError(f"неизвестный вид транспорта {code}")
    direction = _s(item, "direction")
    if direction not in ("A", "B"):
        raise ValueError("direction не A и не B")
    recorded = parse_time_nav(_s(item, "time_nav"))
    state, plan = parse_rasp(str(item.get("rasp", "")), recorded)
    marsh, graph = _s(item, "marsh"), _s(item, "graph")
    ramp, accessibility = ramp_to_accessibility(item.get("ramp"))
    return Vehicle(
        id=f"{code}-{marsh}-{graph}",
        type=TYPE_NAMES[code],
        route=_s(item, "title"),
        marsh=marsh,
        graph=graph,
        direction=direction,
        lat=lat,
        lon=lon,
        recorded_at_utc=_iso(recorded),
        recorded_at_local=recorded.astimezone(NOVOSIBIRSK).strftime("%d.%m %H:%M:%S"),
        azimuth=float(_s(item, "azimuth")),
        speed_kmh=float(_s(item, "speed")),
        segment_order=int(_s(item, "segment_order")),
        ramp=ramp,
        accessibility=accessibility,
        state=state,
        on_line=is_on_line(code, marsh, state),
        plan=plan,
    )


def parse_vehicles(data: Any) -> List[Vehicle]:
    """Повреждённая запись одной машины пропускается, повреждённый ответ целиком: ошибка."""
    if not isinstance(data, dict) or not isinstance(data.get("markers"), list):
        raise ValueError("markers: в ответе нет списка markers")
    result = []
    for item in data["markers"]:
        if not isinstance(item, dict):
            continue
        try:
            result.append(_vehicle(item))
        except (ValueError, KeyError) as exc:
            # Одна странная машина не должна прятать остальные, но молча не теряем.
            print(f"пропущена машина {item.get('title')}/{item.get('graph')}: {exc}", file=sys.stderr)
    return result


def parse_traces(data: Any) -> List[Trace]:
    if not isinstance(data, dict) or not isinstance(data.get("trasses"), list):
        raise ValueError("trasses: в ответе нет списка trasses")
    traces = []
    for group in data["trasses"]:
        for route in group.get("r", []) if isinstance(group, dict) else []:
            points: List[Tuple[float, float]] = []
            stops: List[TraceStop] = []
            for raw in route.get("u", []):
                lat, lon = float(_s(raw, "lat")), float(_s(raw, "lng"))
                name = raw.get("n")
                if isinstance(name, str) and name and name != "-":
                    stops.append(TraceStop(len(stops), _s(raw, "id"), name, lat, lon, len(points)))
                points.append((lat, lon))
            traces.append(Trace(_s(route, "marsh"), tuple(points), tuple(stops)))
    return traces


def parse_forecast(data: Any) -> List[Forecast]:
    if not isinstance(data, dict) or not isinstance(data.get("routes"), list):
        raise ValueError("forecast: в ответе нет списка routes")
    result = []
    for item in data["routes"]:
        code = int(_s(item, "typetr"))
        result.append(
            Forecast(
                route_id=_s(item, "id_marsh"),
                route=_s(item, "title"),
                marsh=_s(item, "marsh"),
                type=TYPE_NAMES.get(code, str(code)),
                direction=_s(item, "direction"),
                minutes=tuple(int(m["time"]) for m in item.get("markers", []) if isinstance(m, dict)),
                stop_end=_s(item, "stop_end"),
            )
        )
    return result


# ---------------------------------------------------------------- сеть


def _ssl_context() -> ssl.SSLContext:
    """Проверка сертификата всегда включена. Python с python.org на macOS приходит без
    списка корневых сертификатов («CERTIFICATE_VERIFY_FAILED»): тогда берём certifi,
    если он установлен, иначе системный файл macOS/Linux."""
    try:
        import certifi  # type: ignore[import-not-found]

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
            if Path(path).is_file():
                ctx.load_verify_locations(cafile=path)
                break
    return ctx


class Client:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 10.0, pause: float = 0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pause = pause  # пауза между запросами, чтобы не нагружать их сервер
        self._last = 0.0
        self._ssl = _ssl_context()

    def get_json(self, path: str, params: Dict[str, str]) -> Any:
        wait = self._last + self.pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise SiteError(f"{path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SiteError(f"{path}: нет ответа ({exc})") from exc
        finally:
            self._last = time.monotonic()
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as exc:
            raise SiteError(f"{path}: ответ не JSON") from exc

    def _parsed(self, path: str, params: Dict[str, str], parse: Any) -> Any:
        data = self.get_json(path, params)
        try:
            return parse(data)
        except (ValueError, KeyError, TypeError) as exc:
            raise SiteError(f"{path}: неожиданный формат ({exc})") from exc

    def routes(self) -> List[Route]:
        return self._parsed("/listmarsh.php", {"r": "true"}, parse_routes)

    def vehicles_raw(self, routes: Sequence[Route]) -> List[Any]:
        return [
            self.get_json("/markers.php", {"r": "".join(r.key() for r in routes[i : i + MARKERS_MAX_ROUTES])})
            for i in range(0, len(routes), MARKERS_MAX_ROUTES)
        ]

    def vehicles(self, routes: Sequence[Route]) -> List[Vehicle]:
        result: List[Vehicle] = []
        for raw in self.vehicles_raw(routes):
            try:
                result.extend(parse_vehicles(raw))
            except ValueError as exc:
                raise SiteError(f"/markers.php: неожиданный формат ({exc})") from exc
        return result

    def traces(self, routes: Sequence[Route], direction: str = "A") -> List[Trace]:
        return self._parsed("/trasses.php", {"r": "".join(r.key(direction) for r in routes)}, parse_traces)

    def forecast(self, stop_id: str) -> List[Forecast]:
        return self._parsed("/forecast.php", {"id": stop_id, "type": "platform"}, parse_forecast)


# ---------------------------------------------------------------- команды


def find_route(routes: Sequence[Route], name: str, type_name: str) -> Route:
    for r in routes:
        if r.type == type_name and r.name.casefold() == name.casefold():
            return r
    raise SystemExit(f"Маршрут {name} ({type_name}) не найден. Список: routes --type {type_name}")


def cmd_routes(c: Client, a: argparse.Namespace) -> Any:
    routes = [r for r in c.routes() if not a.type or r.type == a.type]
    return [{**asdict(r), "key": r.key()} for r in routes]


def cmd_vehicles(c: Client, a: argparse.Namespace) -> Any:
    routes = c.routes()
    if a.route:
        if not a.type:
            raise SystemExit("Для --route нужен --type: номера повторяются у разных видов (автобус 13 и трамвай 13)")
        routes = [find_route(routes, a.route, a.type)]
    elif a.type:
        routes = [r for r in routes if r.type == a.type]
    if a.raw:
        return c.vehicles_raw(routes)
    vehicles = c.vehicles(routes)
    if not a.include_hidden:
        vehicles = [v for v in vehicles if v.on_line]
    if a.low_floor:
        vehicles = [v for v in vehicles if v.accessibility == "yes"]
    counts = {s: sum(v.accessibility == s for v in vehicles) for s in ("yes", "no", "unknown")}
    return {"count": len(vehicles), "accessibility": counts, "requestedRoutes": len(routes),
            "vehicles": [asdict(v) for v in vehicles]}


def cmd_trace(c: Client, a: argparse.Namespace) -> Any:
    route = find_route(c.routes(), a.route, a.type)
    out = []
    for t in c.traces([route], a.direction):
        item: Dict[str, Any] = {"marsh": t.marsh, "direction": a.direction,
                                "stops": [asdict(s) for s in t.stops], "pointsCount": len(t.points)}
        if a.points:
            item["points"] = [{"lat": lat, "lon": lon} for lat, lon in t.points]
        out.append(item)
    return out


def cmd_forecast(c: Client, a: argparse.Namespace) -> Any:
    if a.raw:
        return c.get_json("/forecast.php", {"id": a.stop, "type": "platform"})
    return {"stop": a.stop, "note": "Номера выхода в прогнозе нет: низкопольность по нему не узнать.",
            "routes": [asdict(f) for f in c.forecast(a.stop)]}


def cmd_check(c: Client, _a: argparse.Namespace) -> Any:
    """По одному запросу к каждому адресу: формат тот же, что ожидает разбор?"""
    report: Dict[str, Any] = {}
    routes = c.routes()
    report["listmarsh"] = {"ok": len(routes) > 0, "routes": len(routes)}
    bus = next(r for r in routes if r.type == "bus")
    vehicles = c.vehicles([bus])
    report["markers"] = {"ok": True, "route": bus.name, "vehicles": len(vehicles),
                         "withRampField": sum(v.ramp is not None for v in vehicles)}
    (trace,) = c.traces([bus], "A")
    report["trasses"] = {"ok": len(trace.stops) > 0, "stops": len(trace.stops)}
    fc = c.forecast(trace.stops[0].id)
    report["forecast"] = {"ok": True, "stop": trace.stops[0].id, "routes": len(fc)}
    report["ok"] = all(v["ok"] for v in report.values())
    return report


def cmd_snapshot(c: Client, a: argparse.Namespace) -> Any:
    c.pause = max(c.pause, 1.0)
    files = {
        "listmarsh.json": c.get_json("/listmarsh.php", {"r": "true"}),
        "markers.json": c.get_json("/markers.php", {"r": "1-3-W-3|3-0013-W-13|8-24-W-24|"}),
        "trasses_bus3_A.json": c.get_json("/trasses.php", {"r": "1-3-A-3|"}),
        "forecast_76.json": c.get_json("/forecast.php", {"id": "76", "type": "platform"}),
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"saved": sorted(files), "dir": str(out.resolve())}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nskgortrans.py",
                                description="Данные сайта ЦУГАЭТ (map.nskgortrans.ru). Описание: NSKGORTRANS.md")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--timeout", type=float, default=10.0)
    sub = p.add_subparsers(dest="command", required=True)
    types = list(TYPE_CODES)

    s = sub.add_parser("routes", help="список маршрутов")
    s.add_argument("--type", choices=types)

    s = sub.add_parser("vehicles", help="машины на линии")
    s.add_argument("--route", help="номер маршрута, например 3 или 45К")
    s.add_argument("--type", choices=types)
    s.add_argument("--low-floor", action="store_true", help="только ramp=1 (доступность yes)")
    s.add_argument("--include-hidden", action="store_true", help="и машины, которые сайт скрывает (парк, обед)")
    s.add_argument("--raw", action="store_true", help="сырые ответы markers.php без разбора")

    s = sub.add_parser("trace", help="остановки и линия маршрута")
    s.add_argument("--route", required=True)
    s.add_argument("--type", choices=types, required=True)
    s.add_argument("--direction", choices=["A", "B", "W"], default="A")
    s.add_argument("--points", action="store_true", help="включить все точки линии")

    s = sub.add_parser("forecast", help="прогноз прибытия на остановку")
    s.add_argument("--stop", required=True, help="id остановки из команды trace")
    s.add_argument("--raw", action="store_true")

    sub.add_parser("check", help="проверить формат ответов сайта")

    s = sub.add_parser("snapshot", help="сохранить сырые ответы (образцы для тестов)")
    s.add_argument("--out", default=str(Path(__file__).resolve().parent / "samples"))
    return p


COMMANDS = {"routes": cmd_routes, "vehicles": cmd_vehicles, "trace": cmd_trace,
            "forecast": cmd_forecast, "check": cmd_check, "snapshot": cmd_snapshot}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    client = Client(args.base_url, args.timeout)
    try:
        result = COMMANDS[args.command](client, args)
    except SiteError as exc:
        print(f"Ошибка сайта ЦУГАЭТ: {exc}", file=sys.stderr)
        return 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
