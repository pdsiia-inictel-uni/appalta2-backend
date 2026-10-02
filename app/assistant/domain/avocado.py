"""Conocimiento agronómico de palta Hass que usa el asistente para interpretar los datos.

Los umbrales los evalúa este código (no el modelo): un modelo pequeño tiende a
confundir rangos o inventarlos. El modelo recibe las conclusiones ya calculadas
("evaluacion_palta") y las explica con sus palabras, adaptadas al usuario.

Valores de referencia generales para palta Hass (costa peruana). La humedad del
suelo depende mucho del tipo de suelo y de la calibración del sensor: sus
umbrales son orientativos y así se comunica.
"""

import math
from dataclasses import dataclass

# Texto breve para el prompt del sistema. Sus números también cuentan como
# evidencia válida en la verificación de valores (chat/grounding.py).
REFERENCE_TEXT = (
    "Referencias palta Hass: temperatura del aire óptima 20–25 °C (estrés sobre 30 °C; caída de flores y "
    "frutos sobre 35 °C; bajo 13 °C baja la polinización; riesgo de daño por frío cerca de 2 °C). "
    "Humedad relativa óptima 60–80 % (bajo 50 % estrés hídrico; sobre 85 % favorece hongos como antracnosis). "
    "Temperatura del suelo óptima 18–25 °C (sobre 30 °C estrés de raíces). "
    "pH del suelo óptimo 5.5–6.5 (sobre 7.5 clorosis por falta de hierro y zinc; bajo 5.0 suelo ácido). "
    "Humedad del suelo orientativa 20–40 % (volumétrica); la palta no tolera el encharcamiento (Phytophthora)."
)

# Etapa fenológica habitual por mes en la costa peruana (referencial; varía con zona y altitud).
_PHENOLOGY = {
    1: "crecimiento del fruto y brotación de verano",
    2: "crecimiento del fruto",
    3: "maduración; inicio de cosecha en zonas tempranas",
    4: "cosecha",
    5: "cosecha",
    6: "cosecha; inducción floral por las noches frías",
    7: "cosecha tardía; diferenciación floral",
    8: "inicio de floración",
    9: "floración y cuaje",
    10: "cuaje y caída fisiológica de frutos",
    11: "crecimiento inicial del fruto",
    12: "crecimiento del fruto",
}


def phenological_stage(month: int) -> str:
    return f"{_PHENOLOGY[month]} (referencial para la costa peruana)"


@dataclass(frozen=True)
class Summary:
    """Resumen de un sensor en un periodo (o una sola lectura: avg = min = max)."""

    avg: float
    min_value: float
    max_value: float


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 15 else f"{value:.1f}"


def evaluate_sensor(sensor_key: str, s: Summary, single_reading: bool = False) -> list[str]:
    """Alertas serias de un sensor, cada una con una recomendación breve.

    Solo se alerta cuando el valor sale claramente de lo normal para la palta Hass
    (p. ej. temperatura sobre 30 °C); en condiciones normales no se recomienda nada.
    """
    fn = _EVALUATORS.get(sensor_key)
    return fn(s, single_reading) if fn else []


def _air_temperature(s: Summary, single: bool) -> list[str]:
    out = []
    what_max = "Temperatura de" if single else "Máxima de"
    what_min = "Temperatura de" if single else "Mínima de"
    if s.max_value >= 35:
        out.append(
            f"{what_max} {_fmt(s.max_value)} °C: calor extremo (sobre 35 °C), riesgo de caída de flores y frutos. "
            "Recomendación: regar en horas frescas sin encharcar."
        )
    elif s.max_value > 30:
        out.append(
            f"{what_max} {_fmt(s.max_value)} °C: sobre 30 °C, estrés por calor. "
            "Recomendación: no dejar secar el suelo en las horas de calor."
        )
    if s.min_value <= 2:
        out.append(
            f"{what_min} {_fmt(s.min_value)} °C: riesgo de helada. Recomendación: regar antes de la noche fría y "
            "proteger plantones."
        )
    return out


def _air_humidity(s: Summary, single: bool) -> list[str]:
    if s.avg > 85:
        what = "Humedad de" if single else "Promedio de"
        return [
            f"{what} {_fmt(s.avg)} %: humedad muy alta (sobre 85 %), favorece hongos como antracnosis. "
            "Recomendación: podas de aireación y vigilar manchas en hojas y frutos."
        ]
    return []


def _soil_temperature(s: Summary, single: bool) -> list[str]:
    if s.max_value > 30:
        what = "Temperatura de" if single else "Máxima de"
        return [
            f"{what} {_fmt(s.max_value)} °C en el suelo: sobre 30 °C, estrés de raíces. "
            "Recomendación: cobertura orgánica (mulch) sobre el suelo."
        ]
    return []


def _soil_moisture(s: Summary, single: bool) -> list[str]:
    what = "Humedad del suelo de" if single else "Promedio de"
    if s.avg < 20:
        return [
            f"{what} {_fmt(s.avg)} %: suelo seco (bajo 20 %), riesgo de estrés hídrico. "
            "Recomendación: revisar el riego y confirmar en campo."
        ]
    if s.avg > 50:
        return [
            f"{what} {_fmt(s.avg)} %: suelo encharcado (sobre 50 %), riesgo de Phytophthora. "
            "Recomendación: espaciar riegos y revisar el drenaje."
        ]
    return []


def _soil_ph(s: Summary, single: bool) -> list[str]:
    what = "pH de" if single else "pH promedio de"
    if s.avg > 7.5:
        return [
            f"{what} {_fmt(s.avg)}: muy alcalino (óptimo 5.5–6.5), causa clorosis por falta de hierro y zinc. "
            "Recomendación: acidificar el agua de riego y aplicar quelatos de hierro."
        ]
    if s.avg < 5.0:
        return [
            f"{what} {_fmt(s.avg)}: suelo ácido (bajo 5.0). Recomendación: encalado según análisis de suelo."
        ]
    return []


_EVALUATORS = {
    "temperatura_ambiente": _air_temperature,
    "humedad_ambiente": _air_humidity,
    "temperatura_suelo": _soil_temperature,
    "humedad_suelo": _soil_moisture,
    "ph_suelo": _soil_ph,
}


def _saturation_kpa(t: float) -> float:
    """Presión de vapor de saturación (Tetens, FAO-56), en kPa."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def _vpd(air_t: Summary, air_h: Summary) -> tuple[float, float]:
    """DPV medio (con promedios) y máximo (máxima de temperatura con mínima de humedad), en kPa."""
    mean = _saturation_kpa(air_t.avg) * (1 - air_h.avg / 100)
    peak = _saturation_kpa(air_t.max_value) * (1 - air_h.min_value / 100)
    return mean, peak


def vapor_pressure_deficit(air_t: Summary | None, air_h: Summary | None) -> str:
    """DPV (déficit de presión de vapor) como dato para preguntas técnicas; vacío sin datos."""
    if not (air_t and air_h):
        return ""
    mean, peak = _vpd(air_t, air_h)
    return f"DPV medio aprox. {mean:.2f} kPa; DPV máximo aprox. {peak:.2f} kPa (máxima de temperatura con mínima de humedad)."


def evaluate_combined(summaries: dict[str, Summary]) -> list[str]:
    """Alerta seria que surge de combinar sensores (solo en el diagnóstico general)."""
    air_t, air_h = summaries.get("temperatura_ambiente"), summaries.get("humedad_ambiente")
    if not (air_t and air_h):
        return []
    _, peak = _vpd(air_t, air_h)
    if peak > 2.0 or (air_t.max_value > 30 and air_h.min_value < 50):
        return [
            f"Calor con aire seco (DPV máximo aprox. {peak:.2f} kPa): alta demanda de agua y riesgo de caída de "
            "frutos. Recomendación: priorizar el riego antes del mediodía."
        ]
    return []
