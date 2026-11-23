from datetime import UTC, date, datetime, timedelta

from app.domain.low_floor import LowFloorSnapshot, TripOccurrence, allows_low_floor

NOW = datetime(2026, 11, 23, 16, tzinfo=UTC)
SERVICE_DATE = date(2026, 11, 23)
FIRST = TripOccurrence("first", SERVICE_DATE)
SECOND = TripOccurrence("second", SERVICE_DATE)
THIRD = TripOccurrence("third", SERVICE_DATE)
FRESH = NOW + timedelta(seconds=10)


def test_all_boardings_must_be_confirmed_for_their_exact_service_date() -> None:
    snapshot = LowFloorSnapshot("v1", FRESH, {FIRST: FRESH, SECOND: FRESH})
    next_day = TripOccurrence("second", date(2026, 11, 24))
    for boardings, allowed in (
        ((FIRST, SECOND), True),
        ((FIRST, SECOND, THIRD), False),
        ((FIRST, next_day), False),
    ):
        assert (
            allows_low_floor(
                boardings, otp_version="v1", requested=snapshot, current=snapshot, now=NOW
            )
            is allowed
        )


def test_one_expired_boarding_or_the_feed_expiring_blocks_transit() -> None:
    snapshot = LowFloorSnapshot("v1", FRESH, {FIRST: FRESH, SECOND: NOW})
    assert not allows_low_floor(
        (FIRST, SECOND), otp_version="v1", requested=snapshot, current=snapshot, now=NOW
    )
    assert not allows_low_floor(
        (FIRST,), otp_version="v1", requested=snapshot, current=snapshot, now=FRESH
    )


def test_result_is_rejected_when_feed_or_graph_changed_during_request() -> None:
    old = LowFloorSnapshot("v1", FRESH, {FIRST: FRESH})
    same_contents = LowFloorSnapshot("v1", FRESH, {FIRST: FRESH})
    assert not allows_low_floor(
        (FIRST,), otp_version="v1", requested=old, current=same_contents, now=NOW
    )
    assert not allows_low_floor((FIRST,), otp_version="v2", requested=old, current=old, now=NOW)
    assert not allows_low_floor((FIRST,), otp_version=None, requested=old, current=old, now=NOW)


def test_walking_remains_available_when_transit_is_unavailable() -> None:
    assert allows_low_floor((), otp_version=None, requested=None, current=None, now=NOW)
    assert not allows_low_floor((FIRST,), otp_version=None, requested=None, current=None, now=NOW)
