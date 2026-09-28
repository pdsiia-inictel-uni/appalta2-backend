"""Herramientas que el modelo puede invocar.

Aislamiento por estación: cada `StationToolbox` se construye con UNA estación
resuelta por el servidor. Ninguna herramienta acepta un parámetro de estación,
así que el modelo no puede consultar datos de otra estación aunque lo intente.
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.assistant.data.repository import MeasurementRepository, SensorStats, Station
from app.assistant.domain.dates import extract_date_range
from app.assistant.domain.periods import Period, PeriodError, resolve_period
from app.assistant.domain.sensors import SENSOR_KEYS, SENSORS, Sensor

logger = logging.getLogger(__name__)

# Más días que esto y el detalle diario se omite: en CPU cada token de entrada cuesta.
MAX_DAILY_ROWS = 31

SensorKey = Literal[SENSOR_KEYS]  # type: ignore[valid-type]


class StatsArgs(BaseModel):
    # extra="ignore": si el modelo inventa parámetros (p. ej. "estacion"), se descartan.
    model_config = ConfigDict(extra="ignore")

    sensor: SensorKey
    periodo: Period
    fecha_inicio: date | None = None
    fecha_fin: date | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _normalize(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v.lower() if v else None
        return v


def build_tool_definitions(year: int) -> list[dict[str, Any]]:
    """Definiciones que ve el modelo. Incluyen el año actual para completar fechas sin año."""
    return [
        {
            "type": "function",
            "function": {
                "name": "lecturas_actuales",
                "description": (
                    "Devuelve la lectura más reciente de los 6 sensores de la estación. "
                    "Úsala para preguntas sobre el clima o las condiciones actuales."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "estadisticas_sensor",
                "description": (
                    "Devuelve promedio, máximo, mínimo (con fecha y hora), variación y resumen diario "
                    "de un sensor en un periodo. Úsala para preguntas sobre máximos, mínimos, promedios "
                    "o tendencias en el tiempo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor": {"type": "string", "enum": list(SENSOR_KEYS)},
                        "periodo": {
                            "type": "string",
                            "enum": [p.value for p in Period],
                            "description": (
                                "Usa 'rango' cuando el usuario menciona fechas concretas (p. ej. 'el 12 de "
                                "septiembre', 'del 10 al 18'), y completa fecha_inicio y fecha_fin."
                            ),
                        },
                        "fecha_inicio": {
                            "type": "string",
                            "description": f"Fecha inicial YYYY-MM-DD, obligatoria con 'rango'. Sin año indicado, usa {year}.",
                        },
                        "fecha_fin": {
                            "type": "string",
                            "description": f"Fecha final YYYY-MM-DD (igual a fecha_inicio si es un solo día). Sin año, usa {year}.",
                        },
                    },
                    "required": ["sensor", "periodo"],
                },
            },
        },
    ]


TOOL_DEFINITIONS = build_tool_definitions(datetime.now().year)


class StationToolbox:
    def __init__(
        self,
        repo: MeasurementRepository,
        station: Station,
        timezone: str,
        clock: Callable[[], datetime] | None = None,
        question: str | None = None,
    ):
        self._repo = repo
        # Pregunta original: respaldo para extraer fechas si el modelo no las completa.
        self._question = question
        self._station = station
        self._tz_name = timezone
        self._tz = ZoneInfo(timezone)
        self._clock = clock or (lambda: datetime.now(self._tz))
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "lecturas_actuales": self._latest_readings,
            "estadisticas_sensor": self._sensor_stats,
        }

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return build_tool_definitions(self._clock().year)

    def execute(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Nunca lanza excepciones: los errores vuelven al modelo como datos."""
        handler = self._handlers.get(name)
        if handler is None:
            return {"error": f"Herramienta desconocida: {name}"}
        try:
            return handler(arguments or {})
        except ValidationError as e:
            fields = ", ".join(str(err["loc"][0]) for err in e.errors() if err["loc"])
            return {"error": f"Parámetros inválidos ({fields}). Revisa los valores permitidos."}
        except PeriodError as e:
            return {"error": str(e)}
        except Exception:
            logger.exception("Error ejecutando herramienta %s", name)
            return {"error": "No se pudo consultar la base de datos en este momento."}

    # --- handlers -------------------------------------------------------

    def _latest_readings(self, _: dict[str, Any]) -> dict[str, Any]:
        by_code = {s.db_code: s for s in SENSORS.values()}
        readings = self._repo.latest_readings(self._station.id, list(by_code.values()))
        if not readings:
            return {
                "estacion": self._station.name,
                "sin_datos": True,
                "mensaje": "Esta estación todavía no ha enviado ningún registro de sus sensores.",
            }
        readings.sort(key=lambda r: list(by_code).index(r.sensor_code))
        warnings = [
            f"{by_code[r.sensor_code].label} marca 0 {by_code[r.sensor_code].unit}; "
            "puede indicar que el sensor está desconectado o fuera del suelo."
            for r in readings
            if by_code[r.sensor_code].zero_suspicious and r.value == 0
        ]
        return _with_warnings(
            {
                "estacion": self._station.name,
                "lecturas": [
                    {
                        "sensor": by_code[r.sensor_code].label,
                        "valor": _round(r.value, by_code[r.sensor_code]),
                        "unidad": by_code[r.sensor_code].unit,
                        "fecha": self._fmt(r.ts),
                    }
                    for r in readings
                ],
            },
            warnings,
        )

    def _sensor_stats(self, raw: dict[str, Any]) -> dict[str, Any]:
        args = StatsArgs.model_validate(raw)
        sensor = SENSORS[args.sensor]
        now = self._clock()
        start_date, end_date = args.fecha_inicio, args.fecha_fin
        if args.periodo == Period.RANGO and start_date is None and self._question:
            extracted = extract_date_range(self._question, now.date())
            if extracted:
                start_date, end_date = extracted
        rng = resolve_period(args.periodo, now, start_date, end_date)

        base = {
            "estacion": self._station.name,
            "sensor": sensor.label,
            "unidad": sensor.unit,
            "periodo": args.periodo.value,
            "desde": rng.start.strftime("%Y-%m-%d %H:%M"),
            # Fin inclusivo para el modelo: un día completo termina a las 23:59, no a las 00:00 del siguiente.
            "hasta": (rng.end - timedelta(minutes=1) if rng.end.time() == time.min else rng.end).strftime("%Y-%m-%d %H:%M"),
        }

        stats = self._repo.sensor_stats(self._station.id, sensor, rng.start_ts, rng.end_ts)
        warnings = _quality_warnings(sensor, stats)
        if stats.count == 0:
            last = self._repo.last_reading(self._station.id, sensor)
            # Se entrega el valor real del último registro: si solo se diera la fecha,
            # el modelo tiende a inventar el valor.
            last_info = (
                {"valor": _round(last.value, sensor), "unidad": sensor.unit, "fecha": self._fmt(last.ts)}
                if last
                else "no existe ningún registro de este sensor"
            )
            return _with_warnings(base | {"sin_datos": True, "ultimo_registro_disponible": last_info}, warnings)

        result = base | {
            "cantidad_registros": stats.count,
            "promedio": _round(stats.avg, sensor),
            "maximo": {"valor": _round(stats.max_value, sensor), "fecha": self._fmt(stats.max_ts)},
            "minimo": {"valor": _round(stats.min_value, sensor), "fecha": self._fmt(stats.min_ts)},
            "primer_valor": {"valor": _round(stats.first_value, sensor), "fecha": self._fmt(stats.first_ts)},
            "ultimo_valor": {"valor": _round(stats.last_value, sensor), "fecha": self._fmt(stats.last_ts)},
            "variacion": _round(stats.last_value - stats.first_value, sensor),
        }

        if 1 < rng.days <= MAX_DAILY_ROWS:
            daily = self._repo.daily_stats(self._station.id, sensor, rng.start_ts, rng.end_ts, self._tz_name)
            # Formato compacto: reduce tokens de entrada para el modelo.
            result["resumen_diario"] = [
                f"{d.day.isoformat()}: prom {_round(d.avg, sensor)}, "
                f"min {_round(d.min_value, sensor)}, max {_round(d.max_value, sensor)}"
                for d in daily
            ]
            if len(daily) >= 2:
                result["tendencia"] = _trend(daily[0].avg, daily[-1].avg, sensor, "promedio diario")
        if "tendencia" not in result:
            result["tendencia"] = _trend(stats.first_value, stats.last_value, sensor, "primera y última lectura")
        return _with_warnings(result, warnings)

    def _fmt(self, ts: int) -> str:
        return datetime.fromtimestamp(ts, self._tz).strftime("%Y-%m-%d %H:%M")


def _round(value: float, sensor: Sensor) -> float:
    return round(value, sensor.decimals)


def _trend(start: float, end: float, sensor: Sensor, basis: str) -> str:
    """Tendencia calculada por el código (el modelo solo la narra)."""
    delta = end - start
    values = f"de {_round(start, sensor)} a {_round(end, sensor)} {sensor.unit} ({basis})"
    if abs(delta) < sensor.trend_threshold:
        return f"estable: {values}"
    return f"{'ascendente (subió)' if delta > 0 else 'descendente (bajó)'}: {values}"


def _quality_warnings(sensor: Sensor, stats: SensorStats) -> list[str]:
    warnings = []
    if stats.discarded:
        warnings.append(
            f"Se descartaron {stats.discarded} lecturas con valores imposibles (falla del sensor); "
            "no se incluyen en los cálculos."
        )
    if sensor.zero_suspicious and stats.zeros:
        warnings.append(
            f"{stats.zeros} de {stats.count} lecturas marcan exactamente 0 {sensor.unit}; "
            "puede indicar que el sensor estuvo desconectado o fuera del suelo."
        )
    return warnings


def _with_warnings(result: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return result | {"avisos": warnings} if warnings else result
