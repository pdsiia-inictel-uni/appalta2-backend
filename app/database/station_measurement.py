from sqlalchemy.orm import Session

from app.models.station import Station
from app.models.sensor import Sensor
from app.models.station_measurement import StationMeasurement
from app.models.sensor_measurement import SensorMeasurement

from app.schemas.station_measurement import (
    StationMeasurementRequest
)

def get_sensor_map(
    db: Session,
    sensor_codes: list[str]
) -> dict[str, int]:

    rows = (

        db.query(
            Sensor.sensor_code,
            Sensor.id
        )

        .filter(
            Sensor.sensor_code.in_(sensor_codes)
        )

        .all()

    )

    return {

        sensor_code: sensor_id

        for sensor_code, sensor_id in rows

    }


def save_measurement(
    db: Session,
    station: Station,
    data: StationMeasurementRequest
) -> StationMeasurement:

    measurement = StationMeasurement(

        station_id=station.id,

        measurement_timestamp=data.timestamp,

        latitude=data.latitude,

        longitude=data.longitude,

        battery_level=data.battery_level

    )

    db.add(measurement)

    # Ejecuta el INSERT para obtener measurement.id
    # sin hacer commit.
    db.flush()

    sensor_codes = [

        measurement.sensor_code

        for measurement in data.measurements

    ]

    sensor_map = get_sensor_map(
        db,
        sensor_codes
    )

    for sensor in data.measurements:

        db.add(

            SensorMeasurement(

                measurement_id=measurement.id,

                sensor_id=sensor_map[
                    sensor.sensor_code
                ],

                measurement_timestamp=data.timestamp,

                sensor_value=sensor.value

            )

        )

    station.last_timestamp = data.timestamp

    db.commit()

    db.refresh(measurement)

    return measurement



def get_latest_station_measurement(
    db: Session,
    station_code: str
):

    return (

        db.query(

            Station,

            StationMeasurement

        )

        .outerjoin(

            StationMeasurement,

            StationMeasurement.station_id == Station.id

        )

        .filter(

            Station.station_code == station_code

        )

        .order_by(

            StationMeasurement.measurement_timestamp.desc()

        )

        .first()

    )