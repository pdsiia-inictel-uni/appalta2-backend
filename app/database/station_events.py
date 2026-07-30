from sqlalchemy.orm import Session

from app.models.station import Station
from app.models.station_event import StationEvent
from app.models.station_measurement import StationMeasurement

from app.schemas.station_measurement import (
    StationMeasurementRequest
)


def save_events(
    db: Session,
    measurement: StationMeasurement,
    station: Station,
    data: StationMeasurementRequest
):

    if not data.events:
        return

    for event in data.events:

        db.add(

            StationEvent(

                station_id=station.id,

                measurement_id=measurement.id,

                event_timestamp=data.timestamp,

                event_type=event.event_type,

                event_message=event.message

            )

        )

    db.commit()