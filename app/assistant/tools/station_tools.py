"""Herramientas que el modelo puede invocar.

Aislamiento por estación: cada `StationToolbox` se construye con UNA estación
resuelta por el servidor. Ninguna herramienta acepta un parámetro de estación,
así que el modelo no puede consultar datos de otra estación aunque lo intente.
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.assistant.data.repository import MeasurementRepository, SensorStats, Station
from app.assistant.domain.avocado import (
    Summary,
    evaluate_combined,
    evaluate_sensor,
    phenological_stage,
    vapor_pressure_deficit,
)
from app.assistant.domain.dates import (
    extract_date_range,
    format_date_es,
    format_month_es,
    infer_relative_period,
    normalize_text,
)
from app.assistant.domain.periods import Period, PeriodError, TimeRange, resolve_period
from app.assistant.domain.sensors import SENSOR_KEYS, SENSORS, Sensor

logger = logging.getLogger(__name__)

# Más días que esto y el detalle diario se omite: en CPU cada token de entrada cuesta.
MAX_DAILY_ROWS = 31

# Periodos relativos a "ahora": si no tienen datos (estación sin enviar), se usa la
# misma ventana terminando en el último registro ("últimos 7 días con datos").
_ANCHORABLE = {Period.ULTIMAS_24_HORAS, Period.ULTIMOS_7_DIAS, Period.ULTIMOS_30_DIAS}
# "la última semana registrada", "últimos 7 días con datos", "los datos disponibles"
_ANCHOR_WORDS = re.compile(r"registrad|con datos|disponible|ultimos datos|ultimo registro")
_WHICH_DAY = re.compile(r"que dia|cual dia|en que fecha|cuando (?:fue|hizo|hubo)")
_AVERAGE = re.compile(r"promedio|\bmedia\b|en promedio")

SensorKey = Literal[SENSOR_KEYS]  # type: ignore[valid-type]


class PeriodArgs(BaseModel):
    # extra="ignore": si el modelo inventa parámetros (p. ej. "estacion"), se descartan.
    model_config = ConfigDict(extra="ignore")

    periodo: Period = Period.ULTIMOS_7_DIAS
    fecha_inicio: date | None = None
    fecha_fin: date | None = None

    @field_validator("periodo", mode="before")
    @classmethod
    def _normalize_period(cls, v: Any) -> Any:
        return _normalize_choice(v)

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


class StatsArgs(PeriodArgs):
    sensor: SensorKey
    periodo: Period

    @field_validator("sensor", mode="before")
    @classmethod
    def _normalize_sensor(cls, v: Any) -> Any:
        return _normalize_choice(v)


class CountArgs(PeriodArgs):
    sensor: SensorKey | None = None

    @field_validator("sensor", mode="before")
    @classmethod
    def _normalize_sensor(cls, v: Any) -> Any:
        return _normalize_choice(v)


def _normalize_choice(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        return v.lower() if v else None
    return v


def effective_range(args: PeriodArgs, question: str | None, now: datetime) -> tuple[Period, TimeRange]:
    """Intervalo que realmente se consulta.

    Manda lo que escribió el usuario: si la pregunta trae fechas o meses explícitos ("en
    setiembre", "del 10 al 18"), se usan aunque el modelo haya elegido otro periodo (p. ej.
    'este_mes' en octubre para "todo el mes de setiembre"). Si el modelo eligió 'rango' y la
    pregunta solo trae una expresión relativa ("últimos 7 días", "mes pasado"), se usa esa.
    Solo si la pregunta no trae nada de eso se usan las fechas del modelo.
    """
    period, start, end = args.periodo, args.fecha_inicio, args.fecha_fin
    if question:
        if explicit := extract_date_range(question, now.date()):
            period, (start, end) = Period.RANGO, explicit
        elif period == Period.RANGO and (relative := infer_relative_period(question)):
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
        {
            "type": "function",
            "function": {
                "name": "diagnostico_palta",
                "description": (
                    "Diagnóstico agronómico del cultivo de palta con los 6 sensores en un periodo: resumen de "
                    "cada sensor, evaluación frente a los rangos de la palta Hass, riesgos (calor, frío, hongos, "
                    "Phytophthora, pH) y etapa fenológica. Úsala para '¿cómo están mis paltas?', recomendaciones, "
                    "riego, fertilización, plagas o enfermedades, o '¿cómo estuvo el clima?' en un periodo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "periodo": {"type": "string", "enum": [p.value for p in Period]},
                        "fecha_inicio": {"type": "string", "description": f"YYYY-MM-DD, solo con 'rango'. Sin año, usa {year}."},
                        "fecha_fin": {"type": "string", "description": f"YYYY-MM-DD, solo con 'rango'. Sin año, usa {year}."},
                    },
                    "required": ["periodo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "conteo_lecturas",
                "description": (
                    "Cuántas lecturas o registros envió la estación en un periodo (en total y por sensor, con las "
                    "descartadas por falla). Úsala para '¿cuántas lecturas/registros/datos hay…?'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "periodo": {"type": "string", "enum": [p.value for p in Period]},
                        "fecha_inicio": {"type": "string", "description": f"YYYY-MM-DD, solo con 'rango'. Sin año, usa {year}."},
                        "fecha_fin": {"type": "string", "description": f"YYYY-MM-DD, solo con 'rango'. Sin año, usa {year}."},
                        "sensor": {"type": "string", "enum": list(SENSOR_KEYS), "description": "Opcional: un solo sensor."},
                    },
                    "required": ["periodo"],
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
            "diagnostico_palta": self._diagnosis,
            "conteo_lecturas": self._count,
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
        now = self._clock()
        today = now.date()
        last_ts = max(r.ts for r in readings)
        last_dt = datetime.fromtimestamp(last_ts, self._tz)
        warnings = [
            f"{by_code[r.sensor_code].label} marca 0 {by_code[r.sensor_code].unit}; "
            "puede indicar que el sensor está desconectado o fuera del suelo."
            for r in readings
            if by_code[r.sensor_code].zero_suspicious and r.value == 0
        ]
        evaluation = [
            finding
            for r in readings
            for finding in evaluate_sensor(
                by_code[r.sensor_code].key, Summary(r.value, r.value, r.value), single_reading=True
            )
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
            "etapa_fenologica": phenological_stage(last_dt.month),
        }
        if evaluation:
            result["alertas_palta"] = evaluation
        if last_dt.date() < today:
            # Las "lecturas actuales" no son de hoy: se responde con texto fijo para que
            # nunca se presenten datos antiguos como si fueran del momento.
            values = ", ".join(_with_unit(r.value, by_code[r.sensor_code]) for r in readings)
            answer = (
                f"No hay reporte de hoy ({format_date_es(today)}) en {self._station.name}"
                f"{_silence_note(last_dt, now)}. "
                f"El último registro disponible es del {format_date_es(last_dt.date())} a las {last_dt:%H:%M}: {values}."
            )
            answer += "".join(f" Aviso: {w}" for w in warnings)
            if evaluation:
                answer += "\n\nAlertas para la palta:\n" + "\n".join(f"• {f}" for f in evaluation)
            result["respuesta_directa"] = answer
        return _with_warnings(result, warnings)

    def _sensor_stats(self, raw: dict[str, Any]) -> dict[str, Any]:
        args = StatsArgs.model_validate(raw)
        sensor = SENSORS[args.sensor]
        period, rng = effective_range(args, self._question, self._clock())
        stats, rng, adjusted = self._stats_with_fallback(sensor, period, rng)
        end_shown = _end_shown(rng)

        base = {
            "estacion": self._station.name,
            "sensor": sensor.label,
            "unidad": sensor.unit,
            "periodo": period.value,
            "desde": rng.start.strftime("%Y-%m-%d %H:%M"),
            # Fin inclusivo para el modelo: un día completo termina a las 23:59, no a las 00:00 del siguiente.
            "hasta": end_shown.strftime("%Y-%m-%d %H:%M"),
        }
        if adjusted:
            base["periodo_ajustado"] = adjusted

        warnings = _quality_warnings(sensor, stats)
        if stats.count == 0:
            return self._no_data(sensor, period, rng, base, warnings)

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
                # "¿Qué día hizo más calor?" se responde con el máximo (y su fecha); el día con el promedio
                # más alto solo se entrega si preguntan por el promedio, para que el modelo no los confunda.
                if not self._asks_extreme_day():
                    warmest = max(daily, key=lambda d: d.avg)
                    coolest = min(daily, key=lambda d: d.avg)
                    result["dia_con_promedio_mas_alto"] = {"fecha": warmest.day.isoformat(), "promedio": _round(warmest.avg, sensor)}
                    result["dia_con_promedio_mas_bajo"] = {"fecha": coolest.day.isoformat(), "promedio": _round(coolest.avg, sensor)}
                result["dias_con_datos"] = len(daily)
        if "tendencia" not in result:
            result["tendencia"] = _trend(stats.first_value, stats.last_value, sensor, "primera y última lectura")
        if alerts := evaluate_sensor(sensor.key, _summary(stats, sensor)):
            result["alertas_palta"] = alerts
        return _with_warnings(result, warnings)

    def _count(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Cantidad de lecturas: la respuesta la redacta el código (contar es donde el modelo se confunde)."""
        args = CountArgs.model_validate(raw)
        period, rng = effective_range(args, self._question, self._clock())
        end_shown = _end_shown(rng)
        phrase = _period_phrase(period, rng.start.date(), end_shown.date())
        sensors = [SENSORS[args.sensor]] if args.sensor else list(SENSORS.values())
        base = {
            "estacion": self._station.name,
            "periodo": period.value,
            "desde": rng.start.strftime("%Y-%m-%d %H:%M"),
            "hasta": end_shown.strftime("%Y-%m-%d %H:%M"),
        }

        sends = self._repo.count_measurements(self._station.id, rng.start_ts, rng.end_ts)
        if sends == 0:
            message = f"No hay lecturas {phrase} en {self._station.name}."
            if last := self._repo.last_reading(self._station.id, sensors[0]):
                last_dt = datetime.fromtimestamp(last.ts, self._tz)
                message += f" El último registro es del {format_date_es(last_dt.date())} a las {last_dt:%H:%M}."
            return base | {"sin_datos": True, "envios": 0, "respuesta_directa": message}

        per_sensor, details, span = {}, [], None
        for sensor in sensors:
            stats = self._repo.sensor_stats(self._station.id, sensor, rng.start_ts, rng.end_ts)
            per_sensor[sensor.label] = {"validas": stats.count, "descartadas": stats.discarded}
            notes = []
            if stats.discarded:
                plural = "s" if stats.discarded != 1 else ""
                notes.append(f"{stats.discarded} descartada{plural} por falla del sensor")
            if sensor.zero_suspicious and stats.zeros:
                notes.append(f"{stats.zeros} en 0 {sensor.unit}")
            details.append((stats.count, _in_sentence(sensor.label), f" ({', '.join(notes)})" if notes else ""))
            if span is None and stats.count:
                span = (stats.first_ts, stats.last_ts)

        when = ""
        if span:
            first, last = (datetime.fromtimestamp(ts, self._tz).date() for ts in span)
            when = f" Hay datos desde el {format_date_es(first)} hasta el {format_date_es(last)}."
        if args.sensor:
            count, label, notes = details[0]
            answer = f"Lecturas {phrase} en {self._station.name}: {count} lecturas válidas de {label}{notes}.{when}"
        else:
            answer = (
                f"Lecturas {phrase} en {self._station.name}: {sends} envíos de la estación, cada uno con los "
                f"{len(sensors)} sensores ({sends * len(sensors)} lecturas en total).{when}\n"
                f"Lecturas válidas por sensor: {', '.join(f'{label} {count}{notes}' for count, label, notes in details)}."
            )
        return base | {"envios": sends, "lecturas_por_sensor": per_sensor, "respuesta_directa": answer}

    def _diagnosis(self, raw: dict[str, Any]) -> dict[str, Any]:
        args = PeriodArgs.model_validate(raw)
        period, rng = effective_range(args, self._question, self._clock())
        # La ventana se ajusta una vez (con la temperatura) y se usa igual para todos los sensores.
        probe = SENSORS["temperatura_ambiente"]
        # Para aconsejar "hoy" sin datos de hoy, sirven las últimas 24 horas con datos.
        _, rng, adjusted = self._stats_with_fallback(probe, period, rng, include_days=True)
        end_shown = _end_shown(rng)

        lines, summaries, warnings, evaluation = [], {}, [], []
        for sensor in SENSORS.values():
            stats = self._repo.sensor_stats(self._station.id, sensor, rng.start_ts, rng.end_ts)
            warnings += _quality_warnings(sensor, stats, prefix=f"{sensor.label}: ")
            if stats.count == 0:
                lines.append(f"{sensor.label}: sin datos")
                continue
            summaries[sensor.key] = _summary(stats, sensor)
            lines.append(
                f"{sensor.label}: prom {_round(stats.avg, sensor)} {sensor.unit}, "
                f"min {_round(stats.min_value, sensor)} ({self._fmt(stats.min_ts)}), "
                f"max {_round(stats.max_value, sensor)} ({self._fmt(stats.max_ts)})"
            )
            evaluation += evaluate_sensor(sensor.key, summaries[sensor.key])

        base = {
            "estacion": self._station.name,
            "periodo": period.value,
            "desde": rng.start.strftime("%Y-%m-%d %H:%M"),
            "hasta": end_shown.strftime("%Y-%m-%d %H:%M"),
        }
        if adjusted:
            base["periodo_ajustado"] = adjusted
        if not summaries:
            message = f"No hay datos de los sensores {_period_phrase(period, rng.start.date(), end_shown.date())}."
            last = self._repo.last_reading(self._station.id, probe)
            if last:
                last_dt = datetime.fromtimestamp(last.ts, self._tz)
                message += f" El último registro de la estación es del {format_date_es(last_dt.date())} a las {last_dt:%H:%M}."
            return base | {"sin_datos": True, "mensaje": message, "respuesta_directa": message}

        result = base | {"etapa_fenologica": phenological_stage(end_shown.month), "sensores": lines}
        if dpv := vapor_pressure_deficit(summaries.get("temperatura_ambiente"), summaries.get("humedad_ambiente")):
            result["dpv"] = dpv
        # Sin alertas no hay campo: el modelo informa que las condiciones son normales y no recomienda.
        if alerts := evaluation + evaluate_combined(summaries):
            result["alertas_palta"] = alerts
        return _with_warnings(result, warnings)

    # --- apoyo ----------------------------------------------------------

    def _stats_with_fallback(
        self, sensor: Sensor, period: Period, rng: TimeRange, include_days: bool = False
    ) -> tuple[SensorStats, TimeRange, str | None]:
        """Estadísticas del rango; si es relativo a hoy y la estación dejó de enviar datos,
        usa la misma ventana terminando en el último registro (y lo explica)."""
        anchor_requested = bool(self._question and _ANCHOR_WORDS.search(normalize_text(self._question)))
        stats = self._repo.sensor_stats(self._station.id, sensor, rng.start_ts, rng.end_ts)
        anchorable = _ANCHORABLE | ({Period.HOY, Period.AYER} if include_days else set())
        if period not in anchorable or not (stats.count == 0 or anchor_requested):
            return stats, rng, None
        window = period if period in _ANCHORABLE else Period.ULTIMAS_24_HORAS
        last = self._repo.last_reading(self._station.id, sensor)
        if last is None or last.ts >= rng.end_ts - 3600:
            return stats, rng, None  # sin registros o los datos ya llegan hasta ahora
        last_dt = datetime.fromtimestamp(last.ts, self._tz)
        anchored = resolve_period(window, last_dt + timedelta(minutes=1))
        anchored_stats = self._repo.sensor_stats(self._station.id, sensor, anchored.start_ts, anchored.end_ts)
        if anchored_stats.count == 0:
            return stats, rng, None
        span = _period_phrase(window, anchored.start.date(), anchored.end.date())
        if stats.count:
            note = f"Se usan los datos {span} hasta el último registro ({format_date_es(last_dt.date())} {last_dt:%H:%M})."
        else:
            note = (
                f"La estación no tiene datos {_period_phrase(period, rng.start.date(), _end_shown(rng).date())}: "
                f"su último registro es del {format_date_es(last_dt.date())} a las {last_dt:%H:%M}. Se usan los "
                f"datos {span} hasta ese registro ({format_date_es(anchored.start.date())} al "
                f"{format_date_es(last_dt.date())})."
            )
        return anchored_stats, anchored, note

    def _no_data(
        self, sensor: Sensor, period: Period, rng: TimeRange, base: dict[str, Any], warnings: list[str]
    ) -> dict[str, Any]:
        end_shown = _end_shown(rng)
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
                f"a las {last_dt:%H:%M}: {_with_unit(last.value, sensor)}."
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

    def _asks_extreme_day(self) -> bool:
        """"¿Qué día hizo más calor / fue más frío?" (extremo), no "¿qué día tuvo el promedio más alto?"."""
        text = normalize_text(self._question or "")
        return bool(_WHICH_DAY.search(text)) and not _AVERAGE.search(text)

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
    if start.day == 1 and (start.year, start.month) == (end.year, end.month):
        return f"de {format_month_es(start)} (hasta el {end.day})"  # mes en curso
    return f"entre el {format_date_es(start)} y el {format_date_es(end)}"


def _in_sentence(label: str) -> str:
    """'Temperatura ambiente' → 'temperatura ambiente'; conserva 'pH del suelo'."""
    return label if label.startswith("pH") else label[0].lower() + label[1:]


def _round(value: float, sensor: Sensor) -> float:
    return round(value, sensor.decimals)


def _with_unit(value: float, sensor: Sensor) -> str:
    """'temperatura ambiente 31.9 °C'; el pH va sin unidad repetida: 'pH del suelo 7.7'."""
    unit = "" if sensor.unit == "pH" else f" {sensor.unit}"
    return f"{_in_sentence(sensor.label)} {_round(value, sensor)}{unit}"


def _end_shown(rng: TimeRange) -> datetime:
    return rng.end - timedelta(minutes=1) if rng.end.time() == time.min else rng.end


def _summary(stats: SensorStats, sensor: Sensor) -> Summary:
    return Summary(_round(stats.avg, sensor), _round(stats.min_value, sensor), _round(stats.max_value, sensor))


def _silence_note(last: datetime, now: datetime) -> str:
    """': la estación no envía datos desde hace 12 días (conviene revisar…)'; vacío si es reciente."""
    days = (now.date() - last.date()).days
    if days < 2:
        return ""
    return f": la estación no envía datos desde hace {days} días (conviene revisar su energía y conexión)"


def _trend(start: float, end: float, sensor: Sensor, basis: str) -> str:
    """Tendencia calculada por el código (el modelo solo la narra)."""
    delta = end - start
    values = f"de {_round(start, sensor)} a {_round(end, sensor)} {sensor.unit} ({basis})"
    if abs(delta) < sensor.trend_threshold:
        return f"estable: {values}"
    return f"{'ascendente (subió)' if delta > 0 else 'descendente (bajó)'}: {values}"


def _quality_warnings(sensor: Sensor, stats: SensorStats, prefix: str = "") -> list[str]:
    warnings = []
    if stats.discarded:
        warnings.append(
            f"{prefix}Se descartaron {stats.discarded} lecturas con valores imposibles (falla del sensor); "
            "no se incluyen en los cálculos."
        )
    if sensor.zero_suspicious and stats.zeros:
        warnings.append(
            f"{prefix}{stats.zeros} de {stats.count} lecturas marcan exactamente 0 {sensor.unit}; "
            "puede indicar que el sensor estuvo desconectado o fuera del suelo."
        )
    return warnings


def _with_warnings(result: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return result | {"avisos": warnings} if warnings else result
