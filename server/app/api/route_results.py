"""Представление поездок для публичного контракта."""

from collections.abc import Mapping
from datetime import datetime

from app.api.schemas import CheckedLeg, ScheduledJourney, ScheduledLeg, ScheduledTransitLeg
from app.domain.low_floor import TripOccurrence
from app.domain.models import Accessibility, EtaDiagnostics, EtaMethod
from app.domain.trip_plan import CheckedRide, JourneyOption, PlannedWalk
from app.services.realtime import MatchedVehicle


def journey_response(
    option: JourneyOption,
    at: datetime,
    low_floor_only: bool,
    vehicles: Mapping[TripOccurrence, MatchedVehicle],
    *,
    now: datetime,
) -> ScheduledJourney:
    legs: list[ScheduledLeg] = []
    ready_at = at
    for step in option.journey.legs:
        if isinstance(step, PlannedWalk):
            legs.append(step.leg)
        else:
            occurrence = step.segment.occurrence
            board = step.segment.board_sequence
            match = vehicles.get(occurrence)
            if match is not None and (
                now >= match.valid_until
                or match.next_sequence > board
                or (low_floor_only and match.low_floor is not Accessibility.YES)
            ):
                match = None
            floor = match.low_floor if match else Accessibility.UNKNOWN
            diagnostics = (
                EtaDiagnostics(method=EtaMethod.PLANNED, position_observed_at=match.observed_at)
                if match and match.vehicle_id and step.time_source == "realtime"
                else None
            )
            legs.append(
                ScheduledTransitLeg(
                    trip_id=occurrence.trip_id,
                    service_date=occurrence.service_date,
                    board_sequence=board,
                    alight_sequence=step.segment.alight_sequence,
                    time_source=step.time_source,
                    vehicle_id=match.vehicle_id if match else None,
                    stops_away=board - match.next_sequence if match and match.vehicle_id else None,
                    low_floor=Accessibility.YES if low_floor_only else floor,
                    diagnostics=diagnostics,
                    line=step.line,
                    board_stop=step.board_stop,
                    alight_stop=step.alight_stop,
                    wait_s=max(0, round((step.depart_at - ready_at).total_seconds())),
                    stops_count=step.segment.alight_sequence - board,
                    toward=step.toward,
                    depart_at=step.depart_at,
                    arrive_at=step.arrive_at,
                    geometry=list(step.geometry),
                )
            )
        ready_at = step.arrive_at
    arrive_at = option.journey.arrive_at
    return ScheduledJourney(
        legs=legs,
        depart_at=at,
        arrive_at=arrive_at,
        duration_s=max(0, round((arrive_at - at).total_seconds())),
        transfers=len(option.journey.rides) - 1,
        low_floor_only=low_floor_only,
        labels=list(option.labels),
    )


def checked_response(ride: CheckedRide) -> CheckedLeg:
    segment = ride.segment
    return CheckedLeg(
        trip_id=segment.occurrence.trip_id,
        service_date=segment.occurrence.service_date,
        board_sequence=segment.board_sequence,
        alight_sequence=segment.alight_sequence,
        depart_at=ride.depart_at,
        arrive_at=ride.arrive_at,
        time_source=ride.time_source,
    )
