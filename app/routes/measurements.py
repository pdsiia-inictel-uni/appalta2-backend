from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.config.config import MAX_DRIFT_SECONDS
from app.database.sensor_measurement import get_sensor_history
from app.database.station import get_station_by_station_code, update_last_timestamp
from app.database.station_measurement import save_measurement
from app.database.station_events import save_events
from app.schemas.sensor_measurement import SensorMeasurementHistoryItem, SensorMeasurementHistoryResponse
from app.utils import build_message, verify_signature
from app.schemas.station_measurement import StationMeasurementRequest, StationMeasurementEvent, SensorMeasurementEvent
from app.models.station_measurement import StationMeasurement
from app.services.sse_manager import sse_manager
from sse_starlette.sse import EventSourceResponse
from typing import Optional
import logging
import time
import re

logger = logging.getLogger(__name__)

router = APIRouter()

API_KEYS = {
    "EST001": "abc123",
    "EST002": "def456"
}

SECRET_KEYS = {
    "EST001": "secret_123"
}

LAST_TIMESTAMPS = {}

@router.post("/stations/{station_code}/measurements")
async def recive_data(
    station_code: str = Path(...),
    data: StationMeasurementRequest = ...,
    signature: str = Header(..., alias="Signature"),
    db: Session = Depends(get_db)
):  
    
    if not re.match(
        r"^[A-Z0-9_-]+$",
        station_code
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid station code"
        )

    station = get_station_by_station_code(
            db,
            station_code
    )
        
    if station is None:
            raise HTTPException(
                status_code=404,
                detail="Estación no encontrada"
            )
    
    print(f"station_code:{station_code}")
    #expected = API_KEYS.get(station_code)
    print("TIMESTAMP VERIFICADO")
 
    current_time = int(time.time())

    if abs(current_time - data.timestamp) > MAX_DRIFT_SECONDS:
        raise HTTPException(
            status_code=401,
            detail="Timestamp inválido o expirado"
        )
    
    message = build_message(
        station_code.strip(),
        data
    )
    print("message:\n", message)
    print()
    secret_key = station.secret_key#SECRET_KEYS[station_code]

    
    if not verify_signature(
        message,
        secret_key,
        signature
    ):
        raise HTTPException(
            status_code=401,
            detail="Firma inválida"
        )
    
    print("Firma Acceptada: ", signature)

    last_timestamp = station.last_timestamp #LAST_TIMESTAMPS.get(station_code)

    if last_timestamp is not None:
        if data.timestamp <= last_timestamp:
            raise HTTPException(
                status_code=401,
                detail="Timestamp repetido"
            )
    print("TIMESTAMP NUEVO")
    #LAST_TIMESTAMPS[station_code] = data.timestamp
    
    # station = get_station_by_station_code(
    #     db,
    #     station_code
    # )
    
    measurement = StationMeasurement(
        station_id=station.id,
        measurement_timestamp=data.timestamp,
        latitude=data.latitude,
        longitude=data.longitude,
        battery_level=data.battery_level
    )
    
    save_measurement(
        db,
        station,
        data
    )

    try:
        save_events(
            db,
            measurement,
            station,
            data
        )
    except Exception:
        logger.exception(
            "No fue posible guardar los eventos."
        )


    event = StationMeasurementEvent(

    station_code=station.station_code,

    timestamp=data.timestamp,

    latitude=data.latitude,

    longitude=data.longitude,

    battery_level=data.battery_level,

    measurements=[

        SensorMeasurementEvent(

            sensor_code=sensor.sensor_code,

            value=sensor.value

        )

        for sensor in data.measurements

    ]
)
    try:
        await sse_manager.broadcast(
            station.station_code,
            event.model_dump())
        
    except Exception:
        logger.exception(
            "No fue posible enviar el evento SSE para la estación %s",
            station.station_code
        )
    
    return {
        "status": "received",
        "station_id": station_code
    }

@router.get("/stations/stream")
async def station_stream(

    station: Optional[str] = Query(None),

    stations: Optional[str] = Query(None)

):

    subscriptions = None

    if station:

        subscriptions = {
            station
        }

    elif stations:

        subscriptions = {

            s.strip()

            for s in stations.split(",")

        }

    queue = await sse_manager.connect(
        subscriptions
    )

    async def event_generator():

        try:

            while True:

                data = await queue.get()

                yield {

                    "event": "measurement",

                    "data": data

                }

        finally:

            sse_manager.disconnect(
                queue
            )

    return EventSourceResponse(
        event_generator()
    )


@router.get(

    "/stations/{station_code}/sensors/{sensor_code}/measurements",

    response_model=SensorMeasurementHistoryResponse

)
def sensor_history(

    station_code: str = Path(...),

    sensor_code: str = Path(...),

    start_time: Optional[int] = Query(None),

    end_time: Optional[int] = Query(None),

    limit: Optional[int] = Query(
    None,
    ge=1,
    le=1000
),
    db: Session = Depends(get_db)

):
    if (
    start_time is not None
    and
    end_time is not None
    and
    start_time > end_time
    ):
        raise HTTPException(
            status_code=400,
            detail="start_time debe ser menor o igual que end_time."
        )

    rows = get_sensor_history(

        db,

        station_code,

        sensor_code,

        start_time,

        end_time,

        limit

    )

    return SensorMeasurementHistoryResponse(

        station_code=station_code,

        sensor_code=sensor_code,

        measurements=[

            SensorMeasurementHistoryItem(

                timestamp=row.measurement_timestamp,

                value=float(row.sensor_value)

            )

            for row in rows

        ]

    )