from typing import Optional

from pydantic import BaseModel


class SensorMeasurementResponse(BaseModel):

    sensor_code: str

    value: float


class StationResponse(BaseModel):

    station_code: str

    online: bool
    
    measurement_timestamp: Optional[int] = None

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    battery_level: Optional[float] = None

    measurements: list[SensorMeasurementResponse] = []