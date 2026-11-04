from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.adapters.fake.feed import FakeTransitFeed

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "tsugaet" / "samples"
# Момент, когда сняты образцы: 04.11.2026 12:28 по Новосибирску.
SAMPLE_NOW = datetime(2026, 11, 4, 5, 28, tzinfo=UTC)


class ManualClock:
    def __init__(self, now: datetime = SAMPLE_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def fake_feed() -> FakeTransitFeed:
    return FakeTransitFeed(SAMPLES)
