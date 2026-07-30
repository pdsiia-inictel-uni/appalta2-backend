from sqlalchemy.orm import Session

from app.models.station import Station
from app.models.sensor import Sensor
from app.models.station_measurement import StationMeasurement
from app.models.sensor_measurement import SensorMeasurement
from app.schemas.station import SensorMeasurementResponse


def get_sensor_history(

    db: Session,

    station_code: str,

    sensor_code: str,

    start_time: int | None,

    end_time: int | None,

    limit: int | None

):

    query = (

        db.query(

            SensorMeasurement.measurement_timestamp,

            SensorMeasurement.sensor_value

        )

        .join(

            StationMeasurement,

            StationMeasurement.id ==
            SensorMeasurement.measurement_id

        )

        .join(

            Station,

            Station.id ==
            StationMeasurement.station_id

        )

        .join(

            Sensor,

            Sensor.id ==
            SensorMeasurement.sensor_id

        )

        .filter(

            Station.station_code == station_code,

            Sensor.sensor_code == sensor_code

        )

    )

    if start_time is not None:

        query = query.filter(

            SensorMeasurement.measurement_timestamp >= start_time

        )

    if end_time is not None:

        query = query.filter(

            SensorMeasurement.measurement_timestamp <= end_time

        )

    query = query.order_by(

        SensorMeasurement.measurement_timestamp.asc()

    )

    if limit is not None:

        query = query.limit(limit)

    rows = query.all()

    return rows

def get_measurement_sensors(
    db: Session,
    measurement_id: int
):

    rows = (

        db.query(

            SensorMeasurement,

            Sensor

        )

        .join(

            Sensor,

            Sensor.id ==
            SensorMeasurement.sensor_id

        )

        .filter(

            SensorMeasurement.measurement_id ==
            measurement_id

        )

        .all()

    )

    return [

        SensorMeasurementResponse(

            sensor_code=sensor.sensor_code,

            value=float(
                sensor_measurement.sensor_value
            )

        )

        for sensor_measurement, sensor in rows

    ]