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
from app.assistant.domain.dates import extract_date_range, format_date_es, format_month_es, infer_relative_period
from app.assistant.domain.periods import Period, PeriodError, TimeRange, resolve_period
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

    @field_validator("sensor", "periodo", mode="before")
    @classmethod
    def _normalize(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v.lower() if v else None
        return v

    @field_validator("fecha_inicio", "fecha_fin", mode="before")
    @classmethod
    def _lenient_date(cls, v: Any) -> Any:
        # Una fecha mal escrita por el modelo (p. ej. "rango") se ignora en lugar de fallar:
        # el rango se toma entonces de la pregunta.
        if isinstance(v, str):
            try:
                return date.fromisoformat(v.strip()[:10])
            except ValueError:
                return None
        return v


def effective_range(args: StatsArgs, question: str | None, now: datetime) -> tuple[Period, TimeRange]:
    """Intervalo que realmente se consulta.

    Si el modelo eligió 'rango', manda lo que escribió el usuario: primero fechas o meses
    explícitos ("del 10 al 18 de septiembre"), luego expresiones relativas ("últimos 7 días",
    "mes pasado"). Solo si la pregunta no trae nada de eso se usan las fechas del modelo.
    """
    period, start, end = args.periodo, args.fecha_inicio, args.fecha_fin
    if period == Period.RANGO and question:
        if explicit := extract_date_range(question, now.date()):
            start, end = explicit
        elif relative := infer_relative_period(question):
            period, start, end = Period(relative), None, None
    return period, resolve_period(period, now, start, end)


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
                    "Reporte de un sensor en un periodo: promedio, valor máximo y mínimo (con día y hora), "
                    "día con el promedio más alto y más bajo, tendencia y resumen diario. Úsala para "
                    "preguntas sobre máximos, mínimos, promedios, '¿qué día…?', reportes o tendencias."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor": {"type": "string", "enum": list(SENSOR_KEYS)},
                        "periodo": {
                            "type": "string",
                            "enum": [p.value for p in Period],
                            "description": (
                                "'este_mes' para 'este mes' o 'del mes'; 'mes_anterior' para el mes pasado; "
                                "'rango' cuando el usuario menciona fechas o un mes concreto (p. ej. 'el 12 de "
                                "septiembre', 'del 10 al 18', 'en agosto'), completando fecha_inicio y fecha_fin."
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
            message = f"No hay datos de {self._station.name}: todavía no ha enviado ningún registro de sus sensores."
            return {"estacion": self._station.name, "sin_datos": True, "mensaje": message, "respuesta_directa": message}
        readings.sort(key=lambda r: list(by_code).index(r.sensor_code))
        today = self._clock().date()
        last_ts = max(r.ts for r in readings)
        last_dt = datetime.fromtimestamp(last_ts, self._tz)
        warnings = [
            f"{by_code[r.sensor_code].label} marca 0 {by_code[r.sensor_code].unit}; "
            "puede indicar que el sensor está desconectado o fuera del suelo."
            for r in readings
            if by_code[r.sensor_code].zero_suspicious and r.value == 0
        ]
        result = {
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
        }
        if last_dt.date() < today:
            # Las "lecturas actuales" no son de hoy: se responde con texto fijo para que
            # nunca se presenten datos antiguos como si fueran del momento.
            values = ", ".join(
                f"{_in_sentence(by_code[r.sensor_code].label)} {_round(r.value, by_code[r.sensor_code])} "
                f"{by_code[r.sensor_code].unit}"
                for r in readings
            )
            result["respuesta_directa"] = (
                f"No hay reporte de hoy ({format_date_es(today)}) en {self._station.name}. "
                f"El último registro disponible es del {format_date_es(last_dt.date())} a las {last_dt:%H:%M}: {values}."
                + "".join(f" Aviso: {w}" for w in warnings)
            )
        return _with_warnings(result, warnings)

    def _sensor_stats(self, raw: dict[str, Any]) -> dict[str, Any]:
        args = StatsArgs.model_validate(raw)
        sensor = SENSORS[args.sensor]
        period, rng = effective_range(args, self._question, self._clock())
        end_shown = rng.end - timedelta(minutes=1) if rng.end.time() == time.min else rng.end

        base = {
            "estacion": self._station.name,
            "sensor": sensor.label,
            "unidad": sensor.unit,
            "periodo": period.value,
            "desde": rng.start.strftime("%Y-%m-%d %H:%M"),
            # Fin inclusivo para el modelo: un día completo termina a las 23:59, no a las 00:00 del siguiente.
            "hasta": end_shown.strftime("%Y-%m-%d %H:%M"),
        }

        stats = self._repo.sensor_stats(self._station.id, sensor, rng.start_ts, rng.end_ts)
        warnings = _quality_warnings(sensor, stats)
        if stats.count == 0:
            last = self._repo.last_reading(self._station.id, sensor)
            # Se entrega el valor real del último registro: si solo se diera la fecha,
            # el modelo tiende a inventar el valor.
            last_info = (
                {
                    "valor": _round(last.value, sensor),
                    "unidad": sensor.unit,
                    "fecha": self._fmt(last.ts),
                    "nota": "fuera del periodo consultado",
                }
                if last
                else "no existe ningún registro de este sensor"
            )
            message = f"No hay reporte de {_in_sentence(sensor.label)} {_period_phrase(period, rng.start.date(), end_shown.date())}."
            if last:
                last_dt = datetime.fromtimestamp(last.ts, self._tz)
                answer = (
                    f"{message} El último registro disponible es del {format_date_es(last_dt.date())} "
                    f"a las {last_dt:%H:%M}: {_round(last.value, sensor)} {sensor.unit}."
                )
            else:
                answer = f"{message} Esta estación todavía no tiene ningún registro de este sensor."
            answer += "".join(f" Aviso: {w}" for w in warnings)
            return _with_warnings(
                base
                | {
                    "sin_datos": True,
                    "mensaje": message,
                    "ultimo_registro_disponible": last_info,
                    "respuesta_directa": answer,
                },
                warnings,
            )

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
                # Ranking por día calculado aquí: comparar la lista es donde el modelo pequeño se equivoca.
                warmest = max(daily, key=lambda d: d.avg)
                coolest = min(daily, key=lambda d: d.avg)
                result["dia_con_promedio_mas_alto"] = {"fecha": warmest.day.isoformat(), "promedio": _round(warmest.avg, sensor)}
                result["dia_con_promedio_mas_bajo"] = {"fecha": coolest.day.isoformat(), "promedio": _round(coolest.avg, sensor)}
                result["dias_con_datos"] = len(daily)
        if "tendencia" not in result:
            result["tendencia"] = _trend(stats.first_value, stats.last_value, sensor, "primera y última lectura")
        return _with_warnings(result, warnings)

    def _fmt(self, ts: int) -> str:
        return datetime.fromtimestamp(ts, self._tz).strftime("%Y-%m-%d %H:%M")


def _period_phrase(period: Period, start: date, end: date) -> str:
    """Cómo se nombra el periodo en una respuesta: 'de hoy (29 de setiembre de 2026)'."""
    match period:
        case Period.HOY:
            return f"de hoy ({format_date_es(start)})"
        case Period.AYER:
            return f"de ayer ({format_date_es(start)})"
        case Period.ULTIMAS_24_HORAS:
            return "de las últimas 24 horas"
        case Period.ULTIMOS_7_DIAS:
            return "de los últimos 7 días"
        case Period.ULTIMOS_30_DIAS:
            return "de los últimos 30 días"
        case Period.ESTE_MES:
            return f"de este mes ({format_month_es(start)})"
        case Period.MES_ANTERIOR:
            return f"del mes pasado ({format_month_es(start)})"
    if start == end:
        return f"del {format_date_es(start)}"
    if start.day == 1 and (end + timedelta(days=1)).day == 1 and (start.year, start.month) == (end.year, end.month):
        return f"de {format_month_es(start)}"  # mes completo
    return f"entre el {format_date_es(start)} y el {format_date_es(end)}"


def _in_sentence(label: str) -> str:
    """'Temperatura ambiente' → 'temperatura ambiente'; conserva 'pH del suelo'."""
    return label if label.startswith("pH") else label[0].lower() + label[1:]


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
