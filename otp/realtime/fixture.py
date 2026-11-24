"""Контрольные GPS-отметки №8 для отдельного Docker-проекта."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.adapters.otp.schedule import load_release_schedule
from app.config import get_settings
from app.domain.models import (
    Accessibility,
    Direction,
    Line,
    LinePath,
    LiveVehicle,
    TransportType,
    Vehicle,
    VehicleState,
)
from app.main import create_app
from app.ports import TransitFeedError, UnknownLineError

_RELEASE = get_settings().realtime_release
if _RELEASE is None:
    raise RuntimeError("Укажите GOPOINT_REALTIME_RELEASE для контрольного GPS")
_SCHEDULE = load_release_schedule(_RELEASE)
_SERVICE = next(item for item in _SCHEDULE.services if item.service_id == "bus-8-A-23")
_PATH = LinePath(
    line_id="bus-8",
    direction=Direction.A,
    points=list(_SERVICE.shape),
    stops=[binding.platform for binding in _SERVICE.bindings],
)
_LINE = Line(id="bus-8", type=TransportType.BUS, number="8", title="Цветной проезд — Вокзал")
_TRIP = _SERVICE.trips[0]
_DAY = date(2026, 11, 24)
_MIDNIGHT = datetime.combine(_DAY, time(), ZoneInfo("Asia/Novosibirsk")).astimezone(UTC)
_TIMES_S = (
    5 * 3600 + 58 * 60,
    _TRIP.stop_times[1].arrival + 120,
    _TRIP.stop_times[2].arrival + 120,
    _TRIP.stop_times[2].arrival + 181,
    _TRIP.stop_times[2].arrival + 420,
)


def _step() -> int:
    return int(Path("/scenario/step").read_text(encoding="ascii"))


def _clock() -> datetime:
    return _MIDNIGHT + timedelta(seconds=_TIMES_S[_step()])


class _Feed:
    max_lines_per_request = 6

    async def lines(self) -> list[Line]:
        return [_LINE]

    async def line_path(self, line_id: str, direction: Direction) -> LinePath:
        if line_id == _LINE.id and direction is Direction.A:
            return _PATH
        raise UnknownLineError(line_id)

    async def line_paths(
        self, line_ids: Sequence[str], direction: Direction
    ) -> dict[str, LinePath]:
        return {_LINE.id: _PATH} if _LINE.id in line_ids and direction is Direction.A else {}

    async def vehicles(self, line_ids: Sequence[str]) -> list[LiveVehicle]:
        step = _step()
        if step == 4:
            raise TransitFeedError("Отказ контрольного GPS-источника")
        if step == 0 or _LINE.id not in line_ids:
            return []
        index = min(step, 2)
        return [
            LiveVehicle(
                vehicle=Vehicle(
                    id="bus-8-fixture",
                    line_id="bus-8",
                    type=TransportType.BUS,
                    number="8",
                    direction=Direction.A,
                    point=_PATH.stops[index].stop.point,
                    speed_kmh=20,
                    position_observed_at=_MIDNIGHT + timedelta(seconds=_TIMES_S[index]),
                    low_floor=Accessibility.NO if step == 3 else Accessibility.YES,
                ),
                state=VehicleState.ON_ROUTE,
                on_line=True,
            )
        ]


app = create_app(feed=_Feed(), clock=_clock, start_poller=False)
