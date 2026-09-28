from dataclasses import dataclass


@dataclass(frozen=True)
class Sensor:
    key: str            # nombre que ve el modelo (español, estable)
    db_code: str        # sensors.sensor_code en la base de datos
    label: str
    unit: str
    decimals: int
    valid_min: float    # fuera de [valid_min, valid_max] la lectura es una falla del sensor
    valid_max: float
    trend_threshold: float  # cambio mínimo para hablar de subida o bajada (si no, "estable")
    zero_suspicious: bool = False  # un 0 exacto suele indicar sensor desconectado

    def is_valid(self, value: float) -> bool:
        return self.valid_min <= value <= self.valid_max


# Los 6 sensores de clima que el chat puede consultar.
# Rangos físicos amplios: solo descartan lecturas imposibles (p. ej. −127 °C,
# el código de "sensor no encontrado" de las sondas DS18B20).
SENSORS: dict[str, Sensor] = {
    s.key: s
    for s in (
        Sensor("temperatura_ambiente", "ambient_temperature", "Temperatura ambiente", "°C", 1, -10, 50, 0.5),
        Sensor("humedad_ambiente", "ambient_humidity", "Humedad ambiente", "%", 1, 0, 100, 2),
        Sensor("presion_atmosferica", "atmospheric_pressure", "Presión atmosférica", "hPa", 1, 500, 1100, 1),
        Sensor("temperatura_suelo", "soil_temperature", "Temperatura del suelo", "°C", 1, -10, 60, 0.5),
        Sensor("humedad_suelo", "soil_moisture", "Humedad del suelo", "%", 1, 0, 100, 2, zero_suspicious=True),
        Sensor("ph_suelo", "soil_ph", "pH del suelo", "pH", 2, 0, 14, 0.1),
    )
}

SENSOR_KEYS: tuple[str, ...] = tuple(SENSORS)
