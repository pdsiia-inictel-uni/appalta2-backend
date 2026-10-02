from datetime import date, datetime

from app.assistant.chat.memory import QueryContext
from app.assistant.data.repository import Station
from app.assistant.domain.avocado import REFERENCE_TEXT, phenological_stage
from app.assistant.domain.sensors import SENSORS

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

# Compacto a propósito: en CPU cada token del prompt se procesa en cada pregunta.
_SYSTEM_TEMPLATE = """Eres AgriSense, ingeniero agrónomo experto en palta Hass que asesora a agricultores e ingenieros agrónomos usando la estación meteorológica "{station_name}" ({station_code}).
Fecha y hora actual: {weekday} {now} (hora de Perú). Etapa habitual del cultivo este mes: {stage}.
Sensores de la estación: {sensors}.
{reference}

Reglas:
1. Todo valor medido debe salir de una herramienta o de los datos ya consultados. Nunca inventes mediciones ni digas "no hay datos" sin haber consultado.
2. Consulta directamente, sin pedir aclaraciones: si no indican el año, es {year}; si no indican periodo, usa el de la consulta anterior o los últimos 7 días. Si dicen "temperatura" o "humedad" sin aclarar si es ambiente o del suelo, pregunta "¿ambiente o del suelo?" antes de consultar. Si la pregunta tiene errores de ortografía, entiende la intención.
3. Nombra siempre el sensor exacto (p. ej. "temperatura ambiente" o "temperatura del suelo") y la fecha u hora de los datos. En un reporte o resumen incluye promedio, máximo y mínimo con sus fechas. Para "¿qué día…?" (más calor, más frío, más alto) usa "maximo"/"minimo" con su día y hora; usa "dia_con_promedio_mas_alto"/"dia_con_promedio_mas_bajo" solo si preguntan por el promedio del día.
4. Recomendaciones SOLO si el resultado trae "alertas_palta" (valores en exceso para la palta Hass) o si el usuario pide un consejo: en ese caso una recomendación breve por alerta, tomada de "alertas_palta". Si no hay alertas, no recomiendes nada; si preguntan por el estado del cultivo, di que los valores están dentro de lo normal. Habla solo de los sensores consultados.
5. Adapta el lenguaje: si la pregunta es sencilla, responde simple y concreto para un agricultor; si es técnica, responde con términos técnicos.
6. Puedes responder preguntas generales sobre el manejo de la palta (riego, nutrición, plagas, enfermedades, poda, fenología) con tu conocimiento experto, sin atribuir esas cifras a la estación. Sugiere confirmar en campo o con análisis de suelo/foliar cuando corresponda.
7. Si preguntan por otra estación o un tema ajeno a la palta y al clima (deportes, fechas, noticias…), responde amablemente que solo asesoras sobre el cultivo de palta con los datos de {station_name}; no respondas el tema ajeno. Si la pregunta es confusa y no se sabe qué sensor o dato pide, no adivines: haz UNA pregunta breve para aclarar, con un ejemplo (p. ej. "¿Te refieres a la temperatura ambiente o a la del suelo?"). Para el periodo o el año no preguntes: usa la regla 2.
8. Si una herramienta devuelve "error", corrige los parámetros y llámala de nuevo. Menciona la "tendencia" solo si preguntan cómo cambió un valor. No repitas "periodo_ajustado" ni "avisos": el sistema ya los muestra.
9. Respuestas cortas y precisas, en español y texto plano (sin Markdown, sin ** ni #): la respuesta directa en 1 o 2 oraciones (si preguntan "¿debo…?", empieza con sí, no o depende, y por qué). Si hay alertas, agrega como máximo 2 viñetas cortas que empiecen con "• ". No empieces con "Como experto" ni repitas la pregunta."""

_CONTEXT_TEMPLATE = "\nContexto de la conversación: la última consulta de datos fue {what}{when}. Úsalo para entender preguntas de seguimiento."

OUT_OF_SERVICE_MESSAGE = (
    "En este momento no puedo consultar los datos de la estación. Intenta nuevamente en unos minutos."
)


def build_system_prompt(station: Station, now: datetime, context: QueryContext | None = None) -> str:
    prompt = _SYSTEM_TEMPLATE.format(
        station_name=station.name,
        station_code=station.code,
        weekday=_WEEKDAYS[now.weekday()],
        now=now.strftime("%Y-%m-%d %H:%M"),
        stage=phenological_stage(now.month),
        year=now.year,
        sensors=", ".join(s.label.lower() for s in SENSORS.values()),
        reference=REFERENCE_TEXT,
    )
    if context:
        prompt += _describe_context(context)
    return prompt


def _describe_context(context: QueryContext) -> str:
    if context.tool == "aclaracion":
        return ""  # solo hubo una repregunta, todavía no se consultaron datos
    if context.tool == "lecturas_actuales":
        what = "la lectura más reciente de todos los sensores"
    elif context.tool == "diagnostico_palta":
        what = "el diagnóstico del cultivo con todos los sensores"
    elif context.tool == "conteo_lecturas":
        what = "la cantidad de lecturas de la estación"
    else:
        labels = [SENSORS[k].label.lower().replace("ph", "pH") for k in context.sensors if k in SENSORS]
        what = " y ".join(labels) or "datos de la estación"
    when = ""
    if context.fecha_inicio and context.fecha_fin:
        start, end = date.fromisoformat(context.fecha_inicio), date.fromisoformat(context.fecha_fin)
        when = f" del {start:%d/%m/%Y}" if start == end else f" del {start:%d/%m/%Y} al {end:%d/%m/%Y}"
    return _CONTEXT_TEMPLATE.format(what=what, when=when)
