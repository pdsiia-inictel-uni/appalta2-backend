from pydantic import BaseModel
from typing import Optional

class StationResponse(BaseModel):
    station_code: str
    measurement_timestamp: Optional[int] = None

    latitude: Optional[float] = None
    longitude: Optional[float] = None

    battery_level: Optional[float] = None

    ambient_temperature: Optional[float] = None
    ambient_humidity: Optional[float] = None
    atmospheric_pressure: Optional[float] = None

    soil_temperature: Optional[float] = None
    soil_moisture: Optional[float] = None
    soil_ph: Optional[float] = None