"""Decide por código qué datos consultar antes de llamar al modelo.

Un modelo pequeño a veces responde "no hay datos" sin consultar la base, pide
aclaraciones innecesarias ("¿qué periodo?") o pierde el hilo de la conversación.
Cuando la pregunta es clara, este planificador elige la herramienta, el sensor y
el periodo, y el servicio la ejecuta antes de que el modelo escriba: el modelo
solo redacta con datos reales ya en la mano.

Reglas (texto sin tildes y con meses mal escritos corregidos):
- Pregunta sobre la respuesta anterior ("¿a qué te refieres?", "¿la temperatura
  presentada es ambiental?") → no consulta nada; el modelo usa el contexto.
- Sensor mencionado + periodo → estadísticas de ese sensor en ese periodo.
- Sensor sin periodo → "ahora/actual" = lectura actual; "promedio/máximo…" = el
  periodo de la consulta anterior o, si no hay, los últimos 7 días.
- Sin sensor pero con "¿y el mínimo?" o "¿y en agosto?" → los sensores anteriores.
- Recomendaciones, riego, enfermedades, "¿cómo están mis paltas?" → diagnóstico.
- Cualquier otra cosa → el modelo decide (puede usar herramientas igual).
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.assistant.chat.memory import QueryContext
from app.assistant.domain.dates import extract_date_range, infer_relative_period, normalize_text
from app.assistant.domain.sensors import SENSORS

LATEST = "lecturas_actuales"
STATS = "estadisticas_sensor"
DIAGNOSIS = "diagnostico_palta"
COUNT = "conteo_lecturas"

# "¿Cuántas lecturas/registros/datos hubo…?", "número de mediciones", "cantidad de registros"
_COUNT = re.compile(
    r"cuant[oa]s (?:\w+ )?(?:lecturas|registros|datos|mediciones|medidas|envios|reportes|valores|muestras)"
    r"|(?:numero|cantidad|total) de (?:lecturas|registros|datos|mediciones|envios|reportes|muestras)"
)

# Máximo de sensores consultados de una vez (cada uno es una consulta y tokens para el modelo).
_MAX_SENSORS = 4

_TEMP = r"temperatura|temp\b"
_SOIL = r"(?:del?|en el|en la|de la)?\s*(?:suelo|tierra|raiz|raices)"
# Hasta 2 palabras entre el nombre y el lugar: "temperatura mínima del suelo", "humedad promedio ambiente".
_GAP = r"(?:\s+(?!(?:y|e|o|u)\b)\w+){0,2}?"
_AIR = r"\s+(?:del?\s+)?(?:ambiente|ambiental|relativa|aire|atmosferica)"
_SENSOR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("temperatura_suelo", re.compile(rf"(?:{_TEMP}){_GAP}\s*{_SOIL}\b|suelo (?:esta )?(?:caliente|frio)")),
    (
        "humedad_suelo",
        re.compile(
            rf"humedad{_GAP}\s*{_SOIL}\b|(?:suelo|tierra) (?:esta )?(?:sec|humed|mojad)[oa]\b|agua (?:del|en el) suelo|encharc"
        ),
    ),
    ("ph_suelo", re.compile(r"\bph\b|acidez|alcalin|\bacido\b")),
    ("presion_atmosferica", re.compile(r"presion|barometr")),
    ("humedad_ambiente", re.compile(rf"humedad{_GAP}{_AIR}|\bhr\b|humedad hace\b")),
    ("temperatura_ambiente", re.compile(rf"(?:{_TEMP}){_GAP}{_AIR}|temperatura hace\b")),
]
# Nombre genérico: "temperatura" o "humedad" sin decir de qué. Es ambiguo (aire o suelo): se repregunta.
_GENERIC = [
    ("temperatura", re.compile(rf"\b(?:{_TEMP})"), True),
    ("humedad", re.compile(r"\bhumedad\b"), True),
    # "calor", "frío", "caliente" hablan del aire (salvo "suelo caliente", que ya es del suelo).
    ("temperatura", re.compile(r"\bcalor\b|\bfrio\b|\bcaliente\b"), False),
]
# Justo después de "temperatura"/"humedad": "ambiente y del suelo", "del suelo y ambiental" → ambos sensores
_PLACE_AIR = r"(?:del?\s+)?(?:ambient\w*|aire)"
_PLACE_SOIL = r"(?:del?\s+|de la\s+)?(?:suelo|tierra)"
_BOTH_PLACES = re.compile(
    rf"\s*(?:{_PLACE_AIR}\s+(?:y|e|o|vs)\s+(?:la\s+|el\s+)?{_PLACE_SOIL}|{_PLACE_SOIL}\s+(?:y|e|o|vs)\s+(?:la\s+|el\s+)?{_PLACE_AIR})\b"
)
# Preguntas de conocimiento general ("¿cuál es la temperatura ideal para la palta?"): no son datos de la estación.
_KNOWLEDGE = re.compile(
    r"\bideal|optim|adecuad|requiere|necesita|tolera|soporta|que es\b|por que|para que sirve|como se (?:hace|aplica|controla)"
)

# Preguntas sobre lo que ya se respondió, no sobre datos nuevos.
_META = re.compile(
    r"presentad|mencionad|anterior|me diste|me dijiste|dijiste|te refieres|refieres|a que (?:dato|valor|te)"
    r"|que significa|explica(?:me)? (?:eso|mejor|la respuesta)|no entiendo|de donde sale"
)
_CURRENT = re.compile(
    r"\bahora\b|actual|en este momento|ultim[oa] (?:lectura|medicion|registro|dato|valor)"
    r"|como (?:esta|estan)\b|cuanto (?:marca|esta|hay)|que (?:temperatura|humedad) hace"
)
_STAT = re.compile(
    r"promedio|\bmedia\b|maxim|minim|mas alt|mas baj|\bmayor\b|\bmenor\b|tendencia|reporte|resumen|variacion"
    r"|vario|cambio|evolucion|historial|que dia|cuando fue|\bpico\b|extremo"
)
_ADVICE = re.compile(
    r"recomiend|recomendacion|consej|sugier|sugerencia|que (?:hago|hacer|debo|me recomiendas)|\bdebo\b|deberia"
    r"|conviene|buen momento|riesgo|peligro|helada|plaga|enfermedad|hongo|phytophthora|tristeza|antracnosis|estres"
    r"|diagnostic|salud|fertiliz|abon|\bregar\b|\briego\b|clorosis|floracion|cuaje|cosecha"
    r"|como (?:estan|esta|va|van) (?:mis|mi|el|los|la|las) (?:palt|cultivo|plant|arbol|huerto|campo|fundo)"
    r"|estado del (?:cultivo|campo|huerto|fundo)|demanda (?:hidrica|de agua)|\bdpv\b|\bvpd\b|deficit de presion"
    r"|evapotranspir"
)
_CLIMATE = re.compile(r"\bclima\b|\btiempo\b|condiciones|\bsensores\b|todos los (?:datos|valores)")
# Otras estaciones: no se consulta nada por adelantado; el modelo explica su alcance.
_OTHER_STATION = re.compile(r"\best\d{3}|todas las estaciones|otras? estacion|demas estaciones")
# Variables que la estación no mide: no se reutilizan los sensores de la consulta anterior.
_UNMEASURED = re.compile(r"llov|lluvia|precipitac|viento|radiacion|\bsolar\b|granizo|nubosidad|humedad foliar")
_FOLLOW_UP = re.compile(r"^\s*(?:y|e|tambien|ahora)\b|^\s*\W*\s*y\b")
# Vocabulario del cultivo, la estación y sus sensores: sin ninguna de estas palabras, la
# pregunta no es del ámbito del asistente ("¿cómo estuvo el partido ayer?").
_DOMAIN = re.compile(
    r"palt|aguacate|\bhass\b|cultivo|huerto|fundo|chacra|parcela|campo|\barbol|planta|fruto|fruta|\bflor|cuaje"
    r"|\bhoja|\braiz|raices|tronco|\bsuelo|tierra|\bagua\b|sequia|\bseco|\bseca|mojad|clima|estacion|sensor"
    r"|lectura|medicion|registro|\bdatos?\b|temperatura|\btemp\b|humedad|presion|\bph\b|calor|\bfrio|helada"
    r"|\bsol\b|plaga|insecto|hongo|enfermedad|fertiliz|abon|nutri|poda|cosecha|bateria"
)
# Palabras estadísticas inequívocas ("qué día" o "mayor" solos también aparecen fuera del tema).
_STAT_WORDS = re.compile(r"promedio|\bmedia\b|maxim|minim|mas alt|mas baj|tendencia|reporte|resumen|variacion|\bpico\b")
_GREETING = re.compile(r"^\W*(?:hola|buen[oa]s|gracias|muchas gracias|ok|okey|vale|chau|adios|hasta luego|hey)\b")
_WORDS = re.compile(r"[a-z0-9]+")


def is_out_of_scope(question: str, context: QueryContext | None) -> bool:
    """La pregunta no trata de la palta ni de los datos de la estación (ni sigue la conversación).

    En ese caso no se consulta nada ni se llama al modelo: se repregunta qué dato quiere el usuario.
    """
    text = normalize_text(question)
    if _GREETING.search(text) or _META.search(text) or _OTHER_STATION.search(text) or _is_sensor_clarification(text):
        return False
    if detect_sensors(text) or _DOMAIN.search(text) or _CLIMATE.search(text) or _ADVICE.search(text):
        return False
    if _COUNT.search(text) or _UNMEASURED.search(text):
        return False
    # Seguimiento de la conversación: "¿y el mínimo?", "¿y en agosto?", "el promedio?"
    return not (context and (_FOLLOW_UP.search(text) or _STAT_WORDS.search(text) or _is_short_follow_up(text)))


def _is_short_follow_up(text: str) -> bool:
    """"en agosto?", "y ayer?": pocas palabras que solo cambian el periodo de la consulta anterior."""
    return len(_WORDS.findall(text)) <= 4 and _period_from_question(text, date.today()) is not None


_WHICH_SENSOR = re.compile(
    r"(?:ambient\w*|aire)\b.*\b(?:o|u)\b.*\b(?:suelo|tierra)|(?:suelo|tierra)\b.*\b(?:o|u)\b.*(?:ambient\w*|aire)"
    r"|de que (?:sensor|tipo)|que sensor|cual (?:sensor|temperatura|humedad)"
)


# "esta/esa temperatura", "ese dato": se refiere a lo ya respondido.
_DEMONSTRATIVE = re.compile(r"\b(?:esta|esa|este|ese|eso|dicha|dicho|aquella|aquel)\b")


def _is_sensor_clarification(text: str) -> bool:
    """"¿Esta temperatura es (yes) de ambiente o de suelo?": pregunta qué sensor era, no pide datos nuevos.

    No lo es "¿cuál es mayor, la temperatura ambiente o la del suelo?" (compara, sin demostrativo).
    """
    if not _WHICH_SENSOR.search(text) or extract_date_range(text, date.today()) or infer_relative_period(text):
        return False
    return bool(_META.search(text) or _DEMONSTRATIVE.search(text) or not _STAT.search(text))


def is_meta_question(question: str) -> bool:
    """Pregunta sobre la respuesta anterior (no pide datos nuevos)."""
    text = normalize_text(question)
    return bool(_META.search(text) or _is_sensor_clarification(text))


def answer_from_context(question: str, context: QueryContext | None) -> str | None:
    """Respuesta exacta a "¿era la temperatura ambiente o la del suelo?" sobre la consulta anterior."""
    text = normalize_text(question)
    if not (context and context.tool == STATS and context.sensors and _is_sensor_clarification(text)):
        return None
    labels = [SENSORS[k].label.lower().replace("ph ", "pH ") for k in context.sensors if k in SENSORS]
    what = " y ".join(labels)
    when = ""
    if context.fecha_inicio and context.fecha_fin:
        start, end = date.fromisoformat(context.fecha_inicio), date.fromisoformat(context.fecha_fin)
        when = f" del {start:%d/%m/%Y}" if start == end else f" del {start:%d/%m/%Y} al {end:%d/%m/%Y}"
    return f"El dato que te di corresponde a la {what} (datos de la estación{when})."


@dataclass
class PlannedCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


def plan_tool_calls(question: str, context: QueryContext | None, today: date) -> list[PlannedCall]:
    """Herramientas a ejecutar antes de consultar al modelo (lista vacía = decide el modelo)."""
    text = normalize_text(question)
    if _META.search(text) or _OTHER_STATION.search(text) or _is_sensor_clarification(text):
        return []
    if is_out_of_scope(question, context) or clarification_for(question, context):
        return []

    sensors = detect_sensors(text, context)
    period = _period_from_question(text, today)
    if _COUNT.search(text):
        # Sin periodo: el de la consulta anterior o, si no hay, el mes en curso.
        period = period or (_period_from_context(context) if context and context.fecha_inicio else {"periodo": "este_mes"})
        sensor = {"sensor": sensors[0]} if len(sensors) == 1 else {}
        return [PlannedCall(COUNT, {**period, **sensor})]
    if _KNOWLEDGE.search(text) and period is None and not _CURRENT.search(text):
        return []  # el modelo responde con las referencias de palta Hass (y consulta datos si lo necesita)
    wants_stats = bool(_STAT.search(text))
    wants_advice = bool(_ADVICE.search(text))
    wants_current = bool(_CURRENT.search(text)) and period is None

    if sensors:
        if wants_current and not wants_stats:
            return [PlannedCall(LATEST)]
        if period is None:
            follows_stats = context is not None and context.tool in (STATS, DIAGNOSIS)
            if not (wants_stats or wants_advice or follows_stats):
                return [PlannedCall(LATEST)]
            period = _period_from_context(context)
        return [PlannedCall(STATS, {"sensor": s, **period}) for s in sensors[:_MAX_SENSORS]]

    if wants_advice or _CLIMATE.search(text):
        if period is None and wants_current and not wants_advice:
            return [PlannedCall(LATEST)]
        if period is None and not wants_advice and not wants_stats:
            return [PlannedCall(LATEST)]
        # Un diagnóstico sin periodo mira la última semana (más representativa que un solo día).
        return [PlannedCall(DIAGNOSIS, period or {"periodo": "ultimos_7_dias"})]

    if _UNMEASURED.search(text):
        return []  # el modelo explica que la estación no tiene ese sensor
    # "¿y la del suelo?" tras la temperatura ambiente: mismo tipo de sensor, en el otro lugar.
    if context and context.tool == STATS and context.sensors and _FOLLOW_UP.search(text):
        if (place := _PLACE_FOLLOW_UP.search(text)) and (switched := _switch_place(context.sensors, place)):
            period = period or _period_from_context(context)
            return [PlannedCall(STATS, {"sensor": s, **period}) for s in switched]
    # "¿y el mínimo?", "¿y en agosto?": mismos sensores que la consulta anterior. Un periodo solo
    # cuenta como seguimiento si la pregunta es corta ("en agosto?"), no "¿cómo estuvo X ayer?".
    if context and context.sensors and (wants_stats or _FOLLOW_UP.search(text) or _is_short_follow_up(text)):
        if context.tool == STATS:
            period = period or _period_from_context(context)
            return [PlannedCall(STATS, {"sensor": s, **period}) for s in context.sensors[:_MAX_SENSORS]]
    if context and context.tool in (DIAGNOSIS, COUNT) and period and _FOLLOW_UP.search(text):
        sensor = {"sensor": context.sensors[0]} if context.tool == COUNT and context.sensors else {}
        return [PlannedCall(context.tool, {**period, **sensor})]
    return []


def detect_sensors(text: str, context: QueryContext | None = None) -> list[str]:
    """Sensores nombrados en la pregunta (ya normalizada), en orden de aparición.

    "temperatura" o "humedad" a secas no cuentan (ver `_ambiguous_kinds`), salvo en un seguimiento
    ("¿y la temperatura?") cuando la consulta anterior fue de un solo sensor de ese tipo.
    """
    return _detect(text, context)[0]


def _detect(text: str, context: QueryContext | None) -> tuple[list[str], list[str]]:
    """(sensores identificados, tipos ambiguos: "temperatura"/"humedad" sin decir si ambiente o suelo)."""
    found: list[tuple[int, str]] = []
    covered: list[tuple[int, int]] = []
    ambiguous: list[str] = []
    for key, pattern in _SENSOR_PATTERNS:
        for m in pattern.finditer(text):
            found.append((m.start(), key))
            covered.append(m.span())

    for kind, pattern, is_ambiguous in _GENERIC:
        for m in pattern.finditer(text):
            if _BOTH_PLACES.match(text, m.end()):
                found += [(m.start(), f"{kind}_ambiente"), (m.start() + 1, f"{kind}_suelo")]
                continue
            if any(a <= m.start() < b for a, b in covered):
                continue  # ya es parte de un nombre completo ("temperatura del suelo")
            if any(k.startswith(kind) for _, k in found):
                continue
            if not is_ambiguous:
                found.append((m.start(), f"{kind}_ambiente"))
                continue
            previous = [s for s in (context.sensors if context else ()) if s.startswith(kind)]
            if len(previous) == 1 and _FOLLOW_UP.search(text):
                found.append((m.start(), previous[0]))
            elif kind not in ambiguous:
                ambiguous.append(kind)

    sensors = list(dict.fromkeys(key for _, key in sorted(found)))
    return sensors, [k for k in ambiguous if not any(s.startswith(k) for s in sensors)]


# Respuesta a la repregunta: "ambiente", "del suelo", "la del aire", "ambos".
_PLACE_REPLY = re.compile(
    r"^\W*(?:(?:la|el|las|los|de|del|en|a|es|son|me refiero a)\s+)*"
    r"(?:(?P<air>ambient\w*|aire|atmosferic\w*)|(?P<soil>suelo|tierra)|(?P<both>ambos|ambas|las dos|los dos|todas?|todos?))\b"
)
_GENERIC_NAME = re.compile(r"\b(temperatura|humedad)\b(?!\s+(?:ambient|del suelo|de suelo|relativa|del aire))")


_PLACE_FOLLOW_UP = re.compile(r"\b(?:(?P<air>ambient\w*|aire)|(?P<soil>suelo|tierra))\b")


def _switch_place(sensors: tuple[str, ...], place: re.Match) -> list[str]:
    """('temperatura_ambiente',) + "suelo" → ['temperatura_suelo']; solo temperatura y humedad."""
    suffix = "ambiente" if place.group("air") else "suelo"
    kinds = dict.fromkeys(s.split("_")[0] for s in sensors if s.startswith(("temperatura", "humedad")))
    return [f"{kind}_{suffix}" for kind in kinds]


def clarification_for(question: str, context: QueryContext | None) -> str | None:
    """Repregunta si la pregunta dice "temperatura" o "humedad" sin aclarar si es ambiente o del suelo."""
    text = normalize_text(question)
    if _META.search(text) or _OTHER_STATION.search(text) or _is_sensor_clarification(text):
        return None
    if _ADVICE.search(text) or (_KNOWLEDGE.search(text) and _period_from_question(text, date.today()) is None):
        return None  # consejo o conocimiento general: no depende de un sensor concreto
    kinds = _detect(text, context)[1]
    if not kinds:
        return None
    if len(kinds) == 2:
        return (
            "¿Te refieres a la temperatura y humedad ambiente (del aire) o a las del suelo? "
            'Responde "ambiente", "suelo" o "ambos".'
        )
    kind = kinds[0]
    return f'¿Te refieres a la {kind} ambiente (del aire) o a la {kind} del suelo? Responde "ambiente", "suelo" o "ambos".'


def resolve_clarification(question: str, context: QueryContext | None) -> str | None:
    """Si el usuario responde la repregunta ("del suelo"), devuelve la pregunta pendiente completa
    ("cual fue la temperatura del suelo maxima de ayer"); si no, None."""
    if not (context and context.pending_question):
        return None
    text = normalize_text(question)
    if len(_WORDS.findall(text)) > 6 or not (m := _PLACE_REPLY.match(text)):
        return None
    place = " ambiente" if m.group("air") else " del suelo" if m.group("soil") else " ambiente y del suelo"
    return _GENERIC_NAME.sub(lambda g: g.group(1) + place, context.pending_question)


def _period_from_question(text: str, today: date) -> dict[str, Any] | None:
    if explicit := extract_date_range(text, today):
        start, end = explicit
        return {"periodo": "rango", "fecha_inicio": start.isoformat(), "fecha_fin": end.isoformat()}
    if relative := infer_relative_period(text):
        return {"periodo": relative}
    return None


def _period_from_context(context: QueryContext | None) -> dict[str, Any]:
    if context and context.fecha_inicio and context.fecha_fin:
        return {"periodo": "rango", "fecha_inicio": context.fecha_inicio, "fecha_fin": context.fecha_fin}
    return {"periodo": "ultimos_7_dias"}
