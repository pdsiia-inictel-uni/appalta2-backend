from app.models.station import Station
from sqlalchemy import func
from app.models.station_measurement import StationMeasurement
from app.utils import to_float
from app.schemas.station import StationResponse
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

def get_all_stations(db):
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

    results = (
        db.query(
            Station,
            StationMeasurement
        )
        .outerjoin(
            latest_measurements,
            Station.id == latest_measurements.c.station_id
        )

        .outerjoin(
            StationMeasurement,
            (
                StationMeasurement.station_id
                == latest_measurements.c.station_id
            )
            &
            (
                StationMeasurement.measurement_timestamp
                == latest_measurements.c.max_timestamp
            )
        )
        .all()
    )

    stations = []

    for station, measurement in results:
        stations.append(StationResponse(

        station_code=station.station_code,

        measurement_timestamp=(
            measurement.measurement_timestamp
            if measurement
            else None
        ),

        latitude=to_float(measurement.latitude if measurement else None),
        longitude=to_float(measurement.longitude if measurement else None),

        battery_level=to_float(measurement.battery_level if measurement else None),

        ambient_temperature=to_float(measurement.ambient_temperature if measurement else None),
        ambient_humidity=to_float(measurement.ambient_humidity if measurement else None),
        atmospheric_pressure=to_float(measurement.atmospheric_pressure if measurement else None),

        soil_temperature=to_float(measurement.soil_temperature if measurement else None),
        soil_moisture=to_float(measurement.soil_moisture if measurement else None),
        soil_ph=to_float(measurement.soil_ph if measurement else None)

    )
)

    return stations
