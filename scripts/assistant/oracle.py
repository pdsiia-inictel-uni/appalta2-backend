"""Respuestas esperadas calculadas en el momento de evaluar, directamente desde la BD.

Los valores esperados escritos a mano ("la máxima de ayer fue 33.3") dejan de valer en
cuanto la estación envía datos nuevos o cambia el mes. El oráculo los calcula con SQL
propio, independiente del código del asistente (no usa sus herramientas ni su
repositorio), para el periodo del caso y la hora de la evaluación:

    "expect_db": {"sensor": "temperatura_ambiente", "period": "ayer", "metrics": ["max"]}
    "expect_db": {"sensor": "ph_suelo", "from": "2026-09-01", "to": "2026-09-30", "metrics": ["avg"]}
    "expect_db": {"latest": ["temperatura_ambiente", "humedad_ambiente"]}

Métricas: max, min, avg (valor), max_time / min_time (hora "HH:MM"), max_day / min_day
(día del valor extremo), max_avg_day / min_avg_day (día con el promedio diario más alto o
más bajo, y ese promedio) y trend (sube / baja / estable). Si el periodo no tiene datos,
se espera que el asistente diga que no hay datos.

Reglas del producto que el oráculo respeta: se descartan lecturas fuera del rango válido
del sensor, y los periodos "últimos N días/horas" sin datos se cuentan hasta el último
registro (la estación pudo dejar de enviar).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Engine, text

from app.assistant.domain.periods import Period, resolve_period
from app.assistant.domain.sensors import SENSORS, Sensor

_ANCHORABLE = {"ultimas_24_horas", "ultimos_7_dias", "ultimos_30_dias"}
_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre")  # fmt: skip

_RAW = """
    SELECT sm.sensor_value::float AS v, sm.measurement_timestamp AS ts
      FROM sensor_measurements sm
      JOIN station_measurements st ON st.id = sm.measurement_id
      JOIN sensors s ON s.id = sm.sensor_id
      JOIN stations e ON e.id = st.station_id
     WHERE e.station_code = :station AND s.sensor_code = :code
       AND sm.sensor_value BETWEEN :lo AND :hi
"""


@dataclass(frozen=True)
class Reading:
    value: float
    ts: int


def day_keywords(d: date) -> list[str]:
    """Formas en que la respuesta puede nombrar un día: '12 de septiembre', '12 de setiembre', '2026-09-12', '12/09'."""
    month = _MONTHS[d.month - 1]
    words = [f"{d.day} de {month}", d.isoformat(), f"{d:%d/%m}", f"{d.day}/{d.month}"]
    if d.month == 9:
        words.append(f"{d.day} de setiembre")
    return words


class Oracle:
    def __init__(self, engine: Engine, tz):
        self._engine = engine
        self._tz = tz

    def expectations(self, case: dict, now: datetime) -> dict[str, Any]:
        """Campos esperados (expect_values, expect_keywords_any, expect_no_data, expect_trend) del caso."""
        spec = case.get("expect_db")
        if not spec:
            return {}
        if "latest" in spec:
            values = []
            for key in spec["latest"]:
                last = self._last(case["station"], SENSORS[key], int(now.timestamp()))
                if last:
                    values.append(_fmt(last.value, SENSORS[key]))
            return {"expect_values": values} if values else {"expect_no_data": True}

        sensor = SENSORS[spec["sensor"]]
        start, end = self._range(case["station"], sensor, spec, now)
        readings = self._readings(case["station"], sensor, start, end)
        if not readings:
            return {"expect_no_data": True}

        out: dict[str, Any] = {"expect_values": [], "expect_keywords_any": []}
        for metric in spec.get("metrics", []):
            self._apply(metric, readings, sensor, out)
        return {k: v for k, v in out.items() if v}

    # --- consultas propias (independientes del asistente) ------------------

    def _readings(self, station: str, sensor: Sensor, start: int, end: int) -> list[Reading]:
        sql = text(_RAW + " AND sm.measurement_timestamp >= :start AND sm.measurement_timestamp < :end ORDER BY ts")
        with self._engine.connect() as conn:
            rows = conn.execute(sql, _params(station, sensor) | {"start": start, "end": end}).all()
        return [Reading(r.v, r.ts) for r in rows]

    def _last(self, station: str, sensor: Sensor, until: int) -> Reading | None:
        sql = text(_RAW + " AND sm.measurement_timestamp <= :until ORDER BY ts DESC LIMIT 1")
        with self._engine.connect() as conn:
            r = conn.execute(sql, _params(station, sensor) | {"until": until}).first()
        return Reading(r.v, r.ts) if r else None

    def _range(self, station: str, sensor: Sensor, spec: dict, now: datetime) -> tuple[int, int]:
        if "from" in spec:
            start = datetime.combine(date.fromisoformat(spec["from"]), time.min, tzinfo=self._tz)
            end = datetime.combine(date.fromisoformat(spec["to"]) + timedelta(days=1), time.min, tzinfo=self._tz)
            return int(start.timestamp()), int(min(end, now).timestamp())
        rng = resolve_period(Period(spec["period"]), now)
        start, end = int(rng.start.timestamp()), int(rng.end.timestamp())
        if spec["period"] in _ANCHORABLE and not self._readings(station, sensor, start, end):
            # La estación dejó de enviar: la misma ventana, terminando en su último registro.
            if last := self._last(station, sensor, end):
                anchored = resolve_period(Period(spec["period"]), datetime.fromtimestamp(last.ts, self._tz) + timedelta(minutes=1))
                return int(anchored.start.timestamp()), int(anchored.end.timestamp())
        return start, end

    # --- métricas ------------------------------------------------------------

    def _apply(self, metric: str, rs: list[Reading], sensor: Sensor, out: dict) -> None:
        local = lambda ts: datetime.fromtimestamp(ts, self._tz)  # noqa: E731
        if metric in ("max", "min", "max_time", "min_time", "max_day", "min_day"):
            pick = max if metric.startswith("max") else min
            # Primer instante del extremo (igual criterio que "a qué hora" para el usuario)
            best = pick(rs, key=lambda r: (r.value, -r.ts) if pick is max else (r.value, r.ts))
            if metric in ("max", "min"):
                out["expect_values"].append(_fmt(best.value, sensor))
            elif metric.endswith("_time"):
                out["expect_values"].append(local(best.ts).strftime("%H:%M"))
            else:
                out["expect_keywords_any"] += day_keywords(local(best.ts).date())
        elif metric == "avg":
            out["expect_values"].append(_fmt(sum(r.value for r in rs) / len(rs), sensor))
        elif metric in ("max_avg_day", "min_avg_day"):
            daily = _daily_avgs(rs, local)
            day, _ = (max if metric.startswith("max") else min)(daily.items(), key=lambda kv: kv[1])
            out["expect_keywords_any"] += day_keywords(day)
        elif metric == "trend":
            daily = list(_daily_avgs(rs, local).values())
            first, last = (daily[0], daily[-1]) if len(daily) >= 2 else (rs[0].value, rs[-1].value)
            delta = last - first
            out["expect_trend"] = "stable" if abs(delta) < sensor.trend_threshold else ("up" if delta > 0 else "down")
        else:
            raise ValueError(f"Métrica desconocida: {metric}")


def _daily_avgs(rs: list[Reading], local) -> dict[date, float]:
    sums: dict[date, list[float]] = {}
    for r in rs:
        sums.setdefault(local(r.ts).date(), []).append(r.value)
    return {d: sum(v) / len(v) for d, v in sorted(sums.items())}


def _params(station: str, sensor: Sensor) -> dict:
    return {"station": station, "code": sensor.db_code, "lo": sensor.valid_min, "hi": sensor.valid_max}


def _fmt(value: float, sensor: Sensor) -> str:
    """Mismo redondeo que muestra el asistente: 8.3 (no 8.30), 22.0, 7.98."""
    return str(round(value, sensor.decimals))
