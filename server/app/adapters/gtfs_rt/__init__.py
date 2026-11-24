"""Сериализация снимка в официальный GTFS-Realtime 2.0."""

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from google.transit import gtfs_realtime_pb2 as rt

from app.domain.low_floor import TripOccurrence
from app.domain.realtime import TripDelay


def _trip_update(message: rt.FeedMessage, occurrence: TripOccurrence) -> rt.TripUpdate:
    entity = message.entity.add()
    service_date = occurrence.service_date.strftime("%Y%m%d")
    entity.id = f"{occurrence.trip_id}-{service_date}"
    update = entity.trip_update
    update.trip.trip_id = occurrence.trip_id
    update.trip.start_date = service_date
    return cast(rt.TripUpdate, update)


class GtfsRealtimeEncoder:
    def encode(
        self,
        delays: Sequence[TripDelay],
        cancellations: Sequence[TripOccurrence],
        *,
        generated_at: datetime,
    ) -> bytes:
        message = rt.FeedMessage()
        message.header.gtfs_realtime_version = "2.0"
        message.header.incrementality = rt.FeedHeader.FULL_DATASET
        message.header.timestamp = int(generated_at.timestamp())
        for occurrence in cancellations:
            _trip_update(
                message, occurrence
            ).trip.schedule_relationship = rt.TripDescriptor.CANCELED
        for delay in delays:
            update = _trip_update(message, delay.occurrence)
            update.trip.schedule_relationship = rt.TripDescriptor.SCHEDULED
            update.timestamp = int(delay.observed_at.timestamp())
            call = update.stop_time_update.add()
            call.stop_sequence = delay.stop_sequence
            call.arrival.delay = delay.seconds
            call.departure.delay = delay.seconds
        return cast(bytes, message.SerializeToString())
