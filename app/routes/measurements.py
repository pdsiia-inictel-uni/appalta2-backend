from fastapi import APIRouter, Depends, HTTPException, Header, Path
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.config import MAX_DRIFT_SECONDS
from app.database.station import get_station_by_station_code, update_last_timestamp
from app.database.station_measurement import create_measurement
from app.utils import build_message, verify_signature
from app.schemas.station_measurement import StationMeasurementRequest, StationMeasurementEvent
from app.models.station_measurement import StationMeasurement
from app.services.sse_manager import sse_manager
from sse_starlette.sse import EventSourceResponse
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
    api_key: str = Header(..., alias="Api-Key"),
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

    print("station_code:", station_code)
    expected = API_KEYS.get(station_code)
    print("llego aqui")
    print("data:",data)

    if expected is None:
        raise HTTPException(
            status_code=404,
            detail="Estación no encontrada"
        )

    if expected != api_key:
        raise HTTPException(
            status_code=401,
            detail="API Key inválida"
        )
    
    current_time = int(time.time())

    if abs(current_time - data.timestamp) > MAX_DRIFT_SECONDS:
        raise HTTPException(
            status_code=401,
            detail="Timestamp inválido o expirado"
        )
    
    message = build_message(
        station_code,
        data
    )
    
    secret_key = SECRET_KEYS[station_code]

    if not verify_signature(
        message,
        secret_key,
        signature
    ):
        raise HTTPException(
            status_code=401,
            detail="Firma inválida"
        )
    
    last_timestamp = LAST_TIMESTAMPS.get(station_code)

    if last_timestamp is not None:
        if data.timestamp <= last_timestamp:
            raise HTTPException(
                status_code=401,
                detail="Timestamp repetido"
            )

    LAST_TIMESTAMPS[station_code] = data.timestamp
    
    station = get_station_by_station_code(
        db,
        station_code
    )
    
    measurement = StationMeasurement(

        station_id=station.id,

        measurement_timestamp=data.timestamp,

        latitude=data.latitude,
        longitude=data.longitude,

        battery_level=data.battery_level,

        ambient_temperature=data.ambient_temperature,
        ambient_humidity=data.ambient_humidity,
        atmospheric_pressure=data.atmospheric_pressure,

        soil_temperature=data.soil_temperature,
        soil_moisture=data.soil_moisture,
        soil_ph=data.soil_ph
    )
    
    create_measurement(
        db,
        measurement
    )

    update_last_timestamp(
        db,
        station,
        data.timestamp
    )

    event = StationMeasurementEvent(
    station_code=station.station_code,
    measurement_timestamp=measurement.measurement_timestamp,
    latitude=measurement.latitude,
    longitude=measurement.longitude,
    battery_level=measurement.battery_level,
    ambient_temperature=measurement.ambient_temperature,
    ambient_humidity=measurement.ambient_humidity,
    atmospheric_pressure=measurement.atmospheric_pressure,
    soil_temperature=measurement.soil_temperature,
    soil_moisture=measurement.soil_moisture,
    soil_ph=measurement.soil_ph
    )
    
    try:
        await sse_manager.broadcast(event.model_dump())
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
async def station_stream():
    queue =  await sse_manager.connet()
    async def event_generator():
        try:
            while True:
                data = await queue.get()

                yield {
                    "event": "measurement",
                    "data": data
                }
        finally:
            sse_manager.disconnect(queue)

    return EventSourceResponse(event_generator())