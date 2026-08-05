from app.models.station import Station
from sqlalchemy import func
from app.models.station_measurement import StationMeasurement
from app.models.sensor_measurement import SensorMeasurement
from app.models.sensor import Sensor
from app.utils import ONLINE_TIMEOUT, to_float
from app.schemas.station import StationResponse, SensorMeasurementResponse
import time

def get_station_by_station_code(
    db,
    station_code
):

    return (
        db.query(Station)
        .filter(
            Station.station_code == station_code
        )
        .first()
    )

def update_last_timestamp(
    db,
    station,
    timestamp
):

    station.last_timestamp = timestamp

    db.commit()

def get_latest_station_measurements(db):

    latest_measurements = (

        db.query(

            StationMeasurement.station_id,

            func.max(
                StationMeasurement.measurement_timestamp
            ).label("max_timestamp")

        )

        .group_by(
            StationMeasurement.station_id
        )

        .subquery()

    )

    return (

        db.query(

            Station,

            StationMeasurement

        )

        .outerjoin(

            latest_measurements,

            Station.id ==
            latest_measurements.c.station_id

        )

        .outerjoin(

            StationMeasurement,

            (
                StationMeasurement.station_id ==
                latest_measurements.c.station_id
            )

            &

            (
                StationMeasurement.measurement_timestamp ==
                latest_measurements.c.max_timestamp
            )

        )

        .all()

    )

def get_sensor_measurements(
    db,
    measurement_ids
):

    if not measurement_ids:

        return {}

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

            SensorMeasurement.measurement_id.in_(
                measurement_ids
            )

        )

        .all()

    )

    sensor_map = {}

    for sensor_measurement, sensor in rows:

        sensor_map.setdefault(

            sensor_measurement.measurement_id,

            []

        ).append(

            SensorMeasurementResponse(

                sensor_code=sensor.sensor_code,

                value=float(
                    sensor_measurement.sensor_value
                )

            )

        )

    return sensor_map

def build_station_response(

    results,

    sensor_map

):

    stations = []

    current_timestamp = int(
        time.time()
    )

    for station, measurement in results:

        online = False

        if measurement is not None:
            online = (

                current_timestamp -

                measurement.measurement_timestamp

            ) <= ONLINE_TIMEOUT

        stations.append(

            StationResponse(

                station_code=station.station_code,

                online=online,

                measurement_timestamp=(

                    measurement.measurement_timestamp

                    if measurement

                    else None

                ),

                latitude=to_float(

                    measurement.latitude

                    if measurement

                    else None

                ),

                longitude=to_float(

                    measurement.longitude

                    if measurement

                    else None

                ),

                battery_level=to_float(

                    measurement.battery_level

                    if measurement

                    else None

                ),

                measurements=(

                    sensor_map.get(

                        measurement.id,

                        []

                    )

                    if measurement

                    else []

                )

            )

        )

    return stations

def get_all_stations(db):

    results = get_latest_station_measurements(
        db
    )

    measurement_ids = [

        measurement.id

        for _, measurement in results

        if measurement is not None

    ]

    sensor_map = get_sensor_measurements(

        db,

        measurement_ids

    )

    return build_station_response(

        results,

        sensor_map

    )
