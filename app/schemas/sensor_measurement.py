from typing import Optional

from pydantic import BaseModel


class SensorMeasurementHistoryItem(BaseModel):

    timestamp: int

    value: float


class SensorMeasurementHistoryResponse(BaseModel):

    station_code: str

    sensor_code: str

    measurements: list[SensorMeasurementHistoryItem]