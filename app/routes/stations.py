from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database import station as station_db
from app.database.sensor_measurement import get_measurement_sensors
from app.database.station_measurement import get_latest_station_measurement
from app.schemas.station import StationResponse
from app.utils import ONLINE_TIMEOUT
import time

router = APIRouter()

@router.get(
        "/stations",
        response_model = list[StationResponse])
async def get_all_stations(
    db: Session = Depends(get_db)
):
    return station_db.get_all_stations(db)


@router.get(

    "/stations/{station_code}/latest",

    response_model=StationResponse

)
def get_latest_station(

    station_code: str = Path(...),

    db: Session = Depends(get_db)

):

    result = get_latest_station_measurement(

        db,

        station_code

    )

    if result is None:

        raise HTTPException(

            status_code=404,

            detail="Estación no encontrada."

        )

    station, measurement = result

    measurements = []

    if measurement is not None:

        measurements = get_measurement_sensors(

            db,

            measurement.id

        )
    online = False

    if measurement is not None:
        online = (
            int(time.time()) -
            measurement.measurement_timestamp
        ) <= ONLINE_TIMEOUT

    return StationResponse(

        station_code=station.station_code,
        name=station.name,
        online=online,
        
        measurement_timestamp=(

            measurement.measurement_timestamp

            if measurement

            else None

        ),

        latitude=(

            float(measurement.latitude)

            if measurement and measurement.latitude is not None

            else None

        ),

        longitude=(

            float(measurement.longitude)

            if measurement and measurement.longitude is not None

            else None

        ),

        battery_level=(

            float(measurement.battery_level)

            if measurement and measurement.battery_level is not None

            else None

        ),

        measurements=measurements

    )