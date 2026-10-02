"""Consultas de mediciones. Todas exigen station_id: no existe forma de leer
datos sin filtrar por una estación. Las lecturas fuera del rango válido del
sensor se excluyen de todos los cálculos."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy import Engine, text

from app.assistant.domain.sensors import Sensor


@dataclass(frozen=True)
class Station:
    id: int
    code: str
    name: str


@dataclass(frozen=True)
class Reading:
    sensor_code: str
    value: float
    ts: int


@dataclass(frozen=True)
class SensorStats:
    count: int          # lecturas válidas
    discarded: int      # lecturas fuera de rango (falla del sensor)
    zeros: int          # lecturas válidas exactamente en 0
    avg: float | None = None
    min_value: float | None = None
    min_ts: int | None = None
    max_value: float | None = None
    max_ts: int | None = None
    first_value: float | None = None
    first_ts: int | None = None
    last_value: float | None = None
    last_ts: int | None = None


@dataclass(frozen=True)
class DailyStats:
    day: date
    avg: float
    min_value: float
    max_value: float


class MeasurementRepository(Protocol):
    def get_station(self, station_code: str) -> Station | None: ...

    def latest_readings(self, station_id: int, sensors: list[Sensor]) -> list[Reading]: ...

    def sensor_stats(self, station_id: int, sensor: Sensor, start_ts: int, end_ts: int) -> SensorStats: ...

    def daily_stats(
        self, station_id: int, sensor: Sensor, start_ts: int, end_ts: int, tz: str
    ) -> list[DailyStats]: ...

    def last_reading(self, station_id: int, sensor: Sensor) -> Reading | None: ...

    def count_measurements(self, station_id: int, start_ts: int, end_ts: int) -> int: ...


_BASE_FROM = """
    FROM sensor_measurements sm
    JOIN station_measurements st ON st.id = sm.measurement_id
    JOIN sensors s ON s.id = sm.sensor_id
    WHERE st.station_id = :station_id
"""

_SENSOR_FILTER = " AND s.sensor_code = :sensor_code"
_VALID_FILTER = " AND sm.sensor_value BETWEEN :valid_min AND :valid_max"
_RANGE_FILTER = " AND sm.measurement_timestamp >= :start_ts AND sm.measurement_timestamp < :end_ts"


def _sensor_params(sensor: Sensor) -> dict:
    return {"sensor_code": sensor.db_code, "valid_min": sensor.valid_min, "valid_max": sensor.valid_max}


class SqlMeasurementRepository:
    def __init__(self, engine: Engine):
        self._engine = engine

    def get_station(self, station_code: str) -> Station | None:
        sql = text("SELECT id, station_code, name FROM stations WHERE station_code = :code")
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"code": station_code}).first()
        return Station(row.id, row.station_code, row.name) if row else None

    def latest_readings(self, station_id: int, sensors: list[Sensor]) -> list[Reading]:
        # Una fila (código, mín, máx) por sensor; los nombres de parámetros los genera el código.
        values = ", ".join(f"(:c{i}, :lo{i}, :hi{i})" for i in range(len(sensors)))
        params: dict = {"station_id": station_id}
        for i, s in enumerate(sensors):
            params |= {f"c{i}": s.db_code, f"lo{i}": s.valid_min, f"hi{i}": s.valid_max}
        sql = text(
            "SELECT DISTINCT ON (s.sensor_code) s.sensor_code, sm.sensor_value, sm.measurement_timestamp"
            f"    FROM (VALUES {values}) AS r(code, lo, hi)"
            "    JOIN sensors s ON s.sensor_code = r.code"
            "    JOIN sensor_measurements sm ON sm.sensor_id = s.id"
            "    JOIN station_measurements st ON st.id = sm.measurement_id"
            "   WHERE st.station_id = :station_id"
            "     AND sm.sensor_value BETWEEN CAST(r.lo AS numeric) AND CAST(r.hi AS numeric)"
            " ORDER BY s.sensor_code, sm.measurement_timestamp DESC"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).all()
        return [Reading(r.sensor_code, float(r.sensor_value), r.measurement_timestamp) for r in rows]

    def sensor_stats(self, station_id: int, sensor: Sensor, start_ts: int, end_ts: int) -> SensorStats:
        sql = text(
            "WITH raw AS (SELECT sm.sensor_value AS v, sm.measurement_timestamp AS ts"
            + _BASE_FROM
            + _SENSOR_FILTER
            + _RANGE_FILTER
            + """),
            data AS (SELECT * FROM raw WHERE v BETWEEN :valid_min AND :valid_max)
            SELECT count(*) AS n,
                   (SELECT count(*) FROM raw) - count(*) AS discarded,
                   count(*) FILTER (WHERE v = 0) AS zeros,
                   avg(v) AS avg_v,
                   min(v) AS min_v, (array_agg(ts ORDER BY v ASC, ts))[1] AS min_ts,
                   max(v) AS max_v, (array_agg(ts ORDER BY v DESC, ts))[1] AS max_ts,
                   (array_agg(v ORDER BY ts))[1] AS first_v, min(ts) AS first_ts,
                   (array_agg(v ORDER BY ts DESC))[1] AS last_v, max(ts) AS last_ts
            FROM data
            """
        )
        params = {"station_id": station_id, "start_ts": start_ts, "end_ts": end_ts} | _sensor_params(sensor)
        with self._engine.connect() as conn:
            r = conn.execute(sql, params).one()
        if not r.n:
            return SensorStats(count=0, discarded=r.discarded, zeros=0)
        return SensorStats(
            count=r.n,
            discarded=r.discarded,
            zeros=r.zeros,
            avg=float(r.avg_v),
            min_value=float(r.min_v),
            min_ts=r.min_ts,
            max_value=float(r.max_v),
            max_ts=r.max_ts,
            first_value=float(r.first_v),
            first_ts=r.first_ts,
            last_value=float(r.last_v),
            last_ts=r.last_ts,
        )

    def daily_stats(
        self, station_id: int, sensor: Sensor, start_ts: int, end_ts: int, tz: str
    ) -> list[DailyStats]:
        sql = text(
            "SELECT (to_timestamp(sm.measurement_timestamp) AT TIME ZONE :tz)::date AS day,"
            " avg(sm.sensor_value) AS avg_v, min(sm.sensor_value) AS min_v, max(sm.sensor_value) AS max_v"
            + _BASE_FROM
            + _SENSOR_FILTER
            + _VALID_FILTER
            + _RANGE_FILTER
            + " GROUP BY day ORDER BY day"
        )
        params = {"station_id": station_id, "start_ts": start_ts, "end_ts": end_ts, "tz": tz} | _sensor_params(sensor)
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).all()
        return [DailyStats(r.day, float(r.avg_v), float(r.min_v), float(r.max_v)) for r in rows]

    def last_reading(self, station_id: int, sensor: Sensor) -> Reading | None:
        """Última lectura válida del sensor (valor y fecha), sin importar el periodo."""
        sql = text(
            "SELECT sm.sensor_value, sm.measurement_timestamp"
            + _BASE_FROM
            + _SENSOR_FILTER
            + _VALID_FILTER
            + " ORDER BY sm.measurement_timestamp DESC LIMIT 1"
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"station_id": station_id} | _sensor_params(sensor)).first()
        return Reading(sensor.db_code, float(row.sensor_value), row.measurement_timestamp) if row else None

    def count_measurements(self, station_id: int, start_ts: int, end_ts: int) -> int:
        """Envíos de la estación en el rango (cada envío trae una lectura de cada sensor)."""
        sql = text(
            "SELECT count(*) FROM station_measurements"
            " WHERE station_id = :station_id AND measurement_timestamp >= :start_ts AND measurement_timestamp < :end_ts"
        )
        with self._engine.connect() as conn:
            return conn.execute(sql, {"station_id": station_id, "start_ts": start_ts, "end_ts": end_ts}).scalar_one()
