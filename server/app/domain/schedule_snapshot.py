"""Рейсы и площадки, принятые в транспортный граф OTP."""

from dataclasses import dataclass
from datetime import date

from app.domain.gtfs import ServiceWindow
from app.domain.models import Direction, LatLon
from app.domain.stop_binding import StopBinding


@dataclass(frozen=True)
class CallTime:
    """Секунды от полуночи местного дня обслуживания, включая переход суток."""

    arrival: int
    departure: int


@dataclass(frozen=True)
class PublishedTrip:
    trip_id: str  # тот же ID, что в GTFS и GTFS-Realtime
    stop_times: tuple[CallTime, ...]  # в порядке привязок остановок группы


@dataclass(frozen=True)
class ScheduledService:
    service_id: str
    line_id: str
    direction: Direction
    weekdays: frozenset[int]  # как date.weekday(), понедельник = 0
    window: ServiceWindow
    bindings: tuple[StopBinding, ...]
    shape: tuple[LatLon, ...]
    trips: tuple[PublishedTrip, ...]

    def operates_on(self, service_date: date) -> bool:
        return self.window.start <= service_date <= self.window.end and (
            service_date.weekday() in self.weekdays
        )


@dataclass(frozen=True)
class ScheduleSnapshot:
    version: str
    window: ServiceWindow
    services: tuple[ScheduledService, ...]
