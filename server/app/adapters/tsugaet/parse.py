"""Разбор ответов сайта ЦУГАЭТ (map.nskgortrans.ru). Чистые функции, без сети.

Перенесено из data/tsugaet/nskgortrans.py; описание полей: data/tsugaet/NSKGORTRANS.md.
Правила:
- почти все числа приходят строками;
- ramp: только "1" это yes, только "0" это no, всё остальное unknown;
- time_nav местное время Новосибирска без пояса: сразу переводим в UTC;
- одна повреждённая машина пропускается, повреждённый ответ целиком это ошибка.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from app.domain.models import (
    Accessibility,
    Direction,
    LatLon,
    Line,
    LinePath,
    LiveVehicle,
    PlannedStop,
    RouteStop,
    Stop,
    TransportType,
    Vehicle,
    VehicleState,
)

log = logging.getLogger(__name__)

# Новосибирск: UTC+7 круглый год, перехода на летнее время нет.
NOVOSIBIRSK = timezone(timedelta(hours=7), "Asia/Novosibirsk")

# Код вида транспорта в markers/trasses. В listmarsh.php он на 1 меньше.
TYPE_BY_CODE: dict[int, TransportType] = {
    1: TransportType.BUS,
    2: TransportType.TROLLEYBUS,
    3: TransportType.TRAM,
    8: TransportType.MINIBUS,
}
CODE_BY_TYPE: dict[TransportType, int] = {t: c for c, t in TYPE_BY_CODE.items()}


class TsugaetFormatError(ValueError):
    """Ответ сайта целиком не в том формате, которого ждёт разбор."""


def line_id_for(type_: TransportType, marsh: str) -> str:
    """Наш id маршрута: вид и внутренний код ЦУГАЭТ (номера повторяются у разных видов)."""
    return f"{type_.value}-{marsh}"


@dataclass(frozen=True)
class RouteInfo:
    """Маршрут из listmarsh.php со сведениями, нужными для запросов к сайту."""

    type: TransportType
    marsh: str
    name: str
    stop_begin: str
    stop_end: str

    @property
    def type_code(self) -> int:
        return CODE_BY_TYPE[self.type]

    @property
    def line_id(self) -> str:
        return line_id_for(self.type, self.marsh)

    @property
    def line(self) -> Line:
        title = f"{self.stop_begin} — {self.stop_end}" if self.stop_end else self.stop_begin
        return Line(id=self.line_id, type=self.type, number=self.name, title=title)

    def key(self, direction: str = "W") -> str:
        """Ключ для параметра r: «тип-код-направление-номер|»."""
        if direction not in ("A", "B", "W"):
            raise ValueError(f"направление должно быть A, B или W, а не {direction!r}")
        return f"{self.type_code}-{self.marsh}-{direction}-{self.name}|"


@dataclass(frozen=True)
class ParsedVehicles:
    vehicles: list[LiveVehicle] = field(default_factory=list)
    skipped: int = 0


def _s(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise ValueError(f"поле {key} не строка")
    return value


def _float(item: dict[str, Any], key: str) -> float:
    value = float(_s(item, key))
    if not math.isfinite(value):
        raise ValueError(f"поле {key} не число")
    return value


# ---------------------------------------------------------------- маршруты


def parse_routes(data: Any) -> list[RouteInfo]:
    if not isinstance(data, list):
        raise TsugaetFormatError("listmarsh: ожидался список групп")
    routes: list[RouteInfo] = []
    for group in data:
        if not isinstance(group, dict) or not isinstance(group.get("ways"), list):
            raise TsugaetFormatError("listmarsh: группа без ways")
        code = group.get("type")
        if not isinstance(code, int) or isinstance(code, bool):
            raise TsugaetFormatError("listmarsh: type не число")
        type_ = TYPE_BY_CODE.get(code + 1)
        if type_ is None:
            log.warning("listmarsh: неизвестный вид транспорта %s пропущен", code)
            continue
        for way in group["ways"]:
            try:
                routes.append(
                    RouteInfo(
                        type=type_,
                        marsh=_s(way, "marsh"),
                        name=_s(way, "name"),
                        stop_begin=_s(way, "stopb"),
                        stop_end=_s(way, "stope"),
                    )
                )
            except (ValueError, AttributeError) as exc:
                raise TsugaetFormatError(f"listmarsh: {exc}") from exc
    return routes


# ---------------------------------------------------------------- время

_TIME_NAV = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})$")


def parse_time_nav(value: str) -> datetime:
    """'27.10.26 17:33:09' (местное время Новосибирска) -> datetime в UTC."""
    m = _TIME_NAV.match(value)
    if m is None:
        raise ValueError(f"time_nav: неверный формат {value!r}")
    d, mo, y, h, mi, s = (int(x) for x in m.groups())
    try:
        local = datetime(2000 + y, mo, d, h, mi, s, tzinfo=NOVOSIBIRSK)
    except ValueError as exc:
        raise ValueError(f"time_nav: несуществующая дата {value!r}") from exc
    return local.astimezone(UTC)


def nearest_moment(hour: int, minute: int, reference: datetime) -> datetime:
    """ЧЧ:ММ по Новосибирску, ближайшее к reference (±12 ч), в UTC.

    В плане rasp нет даты: так 00:07 после 23:55 попадает на следующие сутки,
    а 23:58 при отметке 00:05 на предыдущие.
    """
    local = reference.astimezone(NOVOSIBIRSK)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate - local > timedelta(hours=12):
        candidate -= timedelta(days=1)
    elif local - candidate > timedelta(hours=12):
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


_RASP_ITEM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)\+(.+)$")
_SPECIAL_RASP: dict[str, VehicleState] = {
    "-": VehicleState.NO_PLAN,
    "": VehicleState.NO_PLAN,
    "отстой": VehicleState.PARKED,
    "идет на обед": VehicleState.LUNCH,
    "идёт на обед": VehicleState.LUNCH,
    "обеденный+перерыв|": VehicleState.LUNCH,
    "обеденный перерыв": VehicleState.LUNCH,
}


def parse_rasp(text: str, reference: datetime) -> tuple[VehicleState, list[PlannedStop]]:
    """'17:22+Остановка|17:28+Другая|' -> (состояние машины, план на ближайших остановках)."""
    special = _SPECIAL_RASP.get(text.strip().casefold())
    if special is not None:
        return special, []
    plan: list[PlannedStop] = []
    for item in text.split("|"):
        m = _RASP_ITEM.match(item.strip())
        if m is None:
            continue
        at = nearest_moment(int(m.group(1)), int(m.group(2)), reference)
        plan.append(PlannedStop(stop_name=m.group(3).strip(), at=at))
    return (VehicleState.ON_ROUTE, plan) if plan else (VehicleState.NO_PLAN, [])


# ---------------------------------------------------------------- машины


def is_on_line(type_code: int, marsh: str, state: VehicleState) -> bool:
    """Правило сайта ЦУГАЭТ (GoTransport в main.1.3.min.js): скрыты машины на отстое
    и обеде, а без плана скрыты все, кроме маршруток и автобуса 24."""
    if state in (VehicleState.PARKED, VehicleState.LUNCH):
        return False
    if state is VehicleState.NO_PLAN:
        return type_code == 8 or (type_code == 1 and marsh == "24")
    return True


def ramp_to_accessibility(ramp: object) -> Accessibility:
    """Строго: только строка "1" это yes, только "0" это no, всё остальное unknown."""
    if isinstance(ramp, str):
        if ramp == "1":
            return Accessibility.YES
        if ramp == "0":
            return Accessibility.NO
    return Accessibility.UNKNOWN


def _azimuth(item: dict[str, Any]) -> int | None:
    try:
        value = round(_float(item, "azimuth"))
    except ValueError:
        return None
    return value if 0 <= value <= 360 else None


def _stops_passed(item: dict[str, Any]) -> int | None:
    try:
        value = int(_s(item, "segment_order"))
    except ValueError:
        return None
    return value if value >= 0 else None


def _vehicle(item: dict[str, Any]) -> LiveVehicle:
    lat, lon = _float(item, "lat"), _float(item, "lng")
    if lat == 0 and lon == 0:
        raise ValueError("нулевые координаты")
    code = int(_s(item, "id_typetr"))
    type_ = TYPE_BY_CODE.get(code)
    if type_ is None:
        raise ValueError(f"неизвестный вид транспорта {code}")
    direction = Direction(_s(item, "direction"))
    observed = parse_time_nav(_s(item, "time_nav"))
    rasp = item.get("rasp", "")
    state, plan = parse_rasp(rasp if isinstance(rasp, str) else "", observed)
    marsh, graph = _s(item, "marsh"), _s(item, "graph")
    speed = _float(item, "speed")
    if speed < 0:
        raise ValueError("отрицательная скорость")
    line_id = line_id_for(type_, marsh)
    vehicle = Vehicle(
        id=f"{line_id}-{graph}",
        line_id=line_id,
        type=type_,
        number=_s(item, "title"),
        direction=direction,
        point=LatLon(lat=lat, lon=lon),
        azimuth=_azimuth(item),
        speed_kmh=speed,
        low_floor=ramp_to_accessibility(item.get("ramp")),
        position_observed_at=observed,
    )
    return LiveVehicle(
        vehicle=vehicle,
        state=state,
        on_line=is_on_line(code, marsh, state),
        stops_passed=_stops_passed(item),
        plan=plan,
    )


def parse_vehicles(data: Any) -> ParsedVehicles:
    """Ответ markers.php. Повреждённая машина пропускается, повреждённый ответ: ошибка."""
    if not isinstance(data, dict) or not isinstance(data.get("markers"), list):
        raise TsugaetFormatError("markers: в ответе нет списка markers")
    vehicles: list[LiveVehicle] = []
    skipped = 0
    for item in data["markers"]:
        if not isinstance(item, dict):
            skipped += 1
            log.warning("markers: пропущена запись, это не объект")
            continue
        try:
            vehicles.append(_vehicle(item))
        except (ValueError, ValidationError) as exc:
            skipped += 1
            # Без координат и прочих значений: только какая машина и почему.
            log.warning(
                "markers: пропущена машина %s/%s: %s",
                item.get("title"),
                item.get("graph"),
                str(exc).splitlines()[0],
            )
    return ParsedVehicles(vehicles=vehicles, skipped=skipped)


# ---------------------------------------------------------------- линии


def parse_trace(data: Any, line_id: str, direction: Direction) -> LinePath:
    """Ответ trasses.php для одного маршрута в одном направлении."""
    if not isinstance(data, dict) or not isinstance(data.get("trasses"), list):
        raise TsugaetFormatError("trasses: в ответе нет списка trasses")
    routes = [
        route
        for group in data["trasses"]
        if isinstance(group, dict) and isinstance(group.get("r"), list)
        for route in group["r"]
        if isinstance(route, dict) and isinstance(route.get("u"), list)
    ]
    if not routes:
        raise TsugaetFormatError("trasses: линия маршрута не пришла")
    points: list[LatLon] = []
    stops: list[RouteStop] = []
    try:
        for raw in routes[0]["u"]:
            point = LatLon(lat=_float(raw, "lat"), lon=_float(raw, "lng"))
            name = raw.get("n")
            if isinstance(name, str) and name.strip() and name != "-":
                stop = Stop(id=_s(raw, "id"), name=name.strip(), point=point)
                stops.append(RouteStop(order=len(stops), stop=stop, point_index=len(points)))
            points.append(point)
    except (ValueError, AttributeError, ValidationError) as exc:
        raise TsugaetFormatError(f"trasses: {str(exc).splitlines()[0]}") from exc
    if len(points) < 2:
        raise TsugaetFormatError("trasses: в линии меньше двух точек")
    return LinePath(line_id=line_id, direction=direction, points=points, stops=stops)
