from pydantic import BaseModel, model_validator
from typing import Optional

class StationMeasurementRequest(BaseModel):
    timestamp: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    battery_level: Optional[float] = None
    ambient_temperature: Optional[float] = None
    ambient_humidity: Optional[float] = None
    atmospheric_pressure: Optional[float] = None
    soil_temperature: Optional[float] = None
    soil_moisture: Optional[float] = None
    soil_ph: Optional[float] = None

    @model_validator(mode="after")
    def validate_at_least_one_value(self):
        if (
            self.ambient_temperature is None and
            self.ambient_humidity is None and
            self.atmospheric_pressure is None and
            self.soil_temperature is None and
            self.soil_moisture is None and
            self.soil_ph is None and
            self.battery_level is None
        ):
            raise ValueError(
                "Debe enviar al menos una medición"
            )
        return self

class StationMeasurementEvent(BaseModel):

    station_code: str

    measurement_timestamp: int

    latitude: float | None
    longitude: float | None

    battery_level: float | None

    ambient_temperature: float | None
    ambient_humidity: float | None
    atmospheric_pressure: float | None

    soil_temperature: float | None
    soil_moisture: float | None
    soil_ph: float | None