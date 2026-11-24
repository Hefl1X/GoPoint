"""Подтверждённая задержка для конкретного выполнения рейса."""

from dataclasses import dataclass
from datetime import datetime

from app.domain.low_floor import TripOccurrence


@dataclass(frozen=True)
class TripDelay:
    occurrence: TripOccurrence
    stop_sequence: int
    seconds: int
    observed_at: datetime
