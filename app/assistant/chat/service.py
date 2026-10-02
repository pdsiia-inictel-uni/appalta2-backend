"""Orquestador del chat: modelo ⇄ herramientas ⇄ base de datos.

Flujo por pregunta:
1. El servidor resuelve la estación (nunca el modelo).
2. Si la pregunta es clara (sensor, periodo o seguimiento de la consulta anterior),
   el planificador ejecuta las herramientas ANTES de llamar al modelo: el modelo
   ya no puede responder "no hay datos" sin consultar ni pedir aclaraciones.
3. Se envía al modelo: prompt del sistema (con el contexto de la última consulta)
   + historial + pregunta + datos ya consultados + herramientas.
4. Si el modelo pide más herramientas, se ejecutan contra ESA estación y el
   resultado vuelve al modelo. Máximo `chat_max_tool_rounds` rondas.
5. La respuesta final se transmite por partes (streaming).
6. Cada medición de la respuesta se verifica contra los datos consultados; si
   hay un valor no respaldado, se descarta (evento reset) y se regenera una vez.
7. Si los datos traen avisos de calidad (sensor desconectado, lecturas
   descartadas) y la respuesta no los menciona, se añaden al final.
8. Si no hay datos del periodo pedido (o las lecturas "actuales" no son de hoy),
   la herramienta trae una respuesta_directa redactada por el código y se entrega
   tal cual, sin otra llamada al modelo: siempre exacta y más rápida.
9. Se guarda qué se consultó (sensores y fechas) para las preguntas de seguimiento.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Literal
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.assistant.chat.grounding import find_unsupported_values
from app.assistant.chat.memory import ConversationStore, QueryContext
from app.assistant.chat.planner import (
    COUNT,
    DIAGNOSIS,
    LATEST,
    STATS,
    answer_from_context,
    clarification_for,
    is_meta_question,
    is_out_of_scope,
    plan_tool_calls,
    resolve_clarification,
)
from app.assistant.chat.prompts import build_system_prompt
from app.assistant.config import AssistantSettings
from app.assistant.data.repository import MeasurementRepository
from app.assistant.domain.avocado import REFERENCE_TEXT
from app.assistant.domain.dates import normalize_text
from app.assistant.domain.sensors import SENSORS
from app.assistant.llm.base import LLMClient, Message, ToolCall
from app.assistant.tools.station_tools import StationToolbox

logger = logging.getLogger(__name__)

# Afirmar que no hay datos también es un dato: sin consultar, suele ser falso.
_NO_DATA_CLAIM = re.compile(
    r"no (?:hay|existen|tengo|cuento con|dispongo de|se (?:encontraron|registraron)) "
    r"(?:datos|registros|reportes?|lecturas|informaci[oó]n)",
    re.IGNORECASE,
)
_GROUNDING_REMINDER = (
    "No inventes valores. Usa una herramienta para obtener los datos reales de la estación "
    "y luego responde la pregunta anterior."
)
_CORRECTION_TEMPLATE = (
    "Estos valores no aparecen en los datos consultados: {values}. Responde de nuevo la pregunta "
    "usando solo los valores exactos que devolvieron las herramientas."
)
# Una cifra sin consultar datos solo se acepta si es una referencia del cultivo ("óptima 20–25 °C").
_MEASUREMENT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:°|%|hpa\b|ph\b)", re.IGNORECASE)
_REFERENCE_WORDS = re.compile(
    r"[oó]ptim|ideal|referencia|rango|entre \d|sobre \d|bajo \d|superior|inferior|por encima|por debajo|m[aá]s de|menos de",
    re.IGNORECASE,
)
_EMPTY_ANSWER = "No pude generar una respuesta. ¿Puedes reformular la pregunta?"
_OUT_OF_SCOPE_TEMPLATE = (
    "No entendí tu consulta o no está relacionada con la estación. Solo respondo sobre el cultivo de palta y los "
    "datos de los sensores de {station}: temperatura y humedad ambiente, presión atmosférica, y temperatura, "
    "humedad y pH del suelo. ¿Qué dato quieres consultar y de qué periodo? Por ejemplo: "
    "\"temperatura máxima de ayer\" o \"humedad del suelo de esta semana\"."
)
# Marcas de formato Markdown que la app mostraría literalmente (** negrita, # títulos).
_MARKDOWN = str.maketrans("", "", "*#")
# Palabras que indican que la respuesta ya comunicó un aviso de calidad de datos.
_WARNING_MENTIONED = re.compile(r"sensor|descart|desconect|falla|aviso", re.IGNORECASE)
# La respuesta ya transmitió la alerta de la palta si recomienda algo.
_RECOMMENDATION_MENTIONED = re.compile(r"recomend|recomiend|conviene|se sugiere", re.IGNORECASE)


class StationNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class ToolExecution:
    name: str
    arguments: dict[str, Any]
    ok: bool
    output: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ChatEvent:
    """Evento de streaming.

    - delta: fragmento de la respuesta.
    - reset: descartar el texto recibido hasta ahora (el modelo decidió consultar datos).
    - tool:  se está consultando una herramienta (útil para mostrar "consultando...").
    - done:  fin; `result` trae la respuesta completa.
    """

    type: Literal["delta", "reset", "tool", "done"]
    text: str = ""
    tool: str = ""
    result: "ChatResult | None" = None


@dataclass
class ChatResult:
    answer: str
    station_code: str
    session_id: str
    tools: list[ToolExecution] = field(default_factory=list)
    duration_ms: int = 0


class ChatService:
    def __init__(
        self,
        settings: AssistantSettings,
        llm: LLMClient,
        repo: MeasurementRepository,
        memory: ConversationStore,
        clock: Callable[[], datetime] | None = None,
    ):
        self._settings = settings
        self._llm = llm
        self._repo = repo
        self._memory = memory
        tz = ZoneInfo(settings.timezone)
        self._clock = clock or (lambda: datetime.now(tz))

    async def ask(self, station_code: str, question: str, user_id: str, session_id: str) -> ChatResult:
        result: ChatResult | None = None
        async for event in self.ask_stream(station_code, question, user_id, session_id):
            if event.type == "done":
                result = event.result
        assert result is not None
        return result

    async def ask_stream(
        self, station_code: str, question: str, user_id: str, session_id: str
    ) -> AsyncIterator[ChatEvent]:
        started = time.perf_counter()
        station = await run_in_threadpool(self._repo.get_station, station_code)
        if station is None:
            raise StationNotFoundError(station_code)

        now = self._clock()
        memory_key = f"{user_id}:{station.code}:{session_id}"
        context = self._memory.get_context(memory_key)
        # Respuesta a "¿ambiente o del suelo?": se continúa con la pregunta pendiente, ya completa.
        question = resolve_clarification(question, context) or question
        pending: str | None = None
        toolbox = StationToolbox(self._repo, station, self._settings.timezone, clock=self._clock, question=question)

        messages: list[Message] = [
            {"role": "system", "content": build_system_prompt(station, now, context)},
            *self._memory.get(memory_key),
            {"role": "user", "content": question},
        ]
        executions: list[ToolExecution] = []
        reminded = False
        corrected = False
        answer = ""
        max_rounds = self._settings.chat_max_tool_rounds
        tool_rounds = 0

        async def run_calls(calls: list[ToolCall], text: str = "") -> AsyncIterator[ChatEvent]:
            """Ejecuta una ronda de herramientas y agrega llamadas y resultados a la conversación."""
            messages.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls],
                }
            )
            for call in calls:
                yield ChatEvent("tool", tool=call.name)
                output = await run_in_threadpool(toolbox.execute, call.name, call.arguments)
                executions.append(ToolExecution(call.name, call.arguments, "error" not in output, output))
                messages.append(
                    {"role": "tool", "tool_name": call.name, "content": json.dumps(output, ensure_ascii=False)}
                )

        def direct_answer(round_size: int) -> str:
            """Si todos los resultados de la ronda traen respuesta_directa, se entregan tal cual."""
            outputs = [e.output for e in executions[-round_size:]]
            if outputs and all("respuesta_directa" in o for o in outputs):
                return "\n\n".join(dict.fromkeys(o["respuesta_directa"] for o in outputs))
            return ""

        # Consulta planificada por código (pregunta clara o de seguimiento de la anterior).
        planned = [ToolCall(c.name, c.arguments) for c in plan_tool_calls(question, context, now.date())]
        if planned:
            tool_rounds = 1
            async for event in run_calls(planned):
                yield event
            answer = direct_answer(len(planned))
        elif ask := clarification_for(question, context):
            # "temperatura"/"humedad" sin decir si es ambiente o del suelo: se repregunta y se guarda la pregunta.
            answer, pending = ask, normalize_text(question)
        elif is_meta_question(question):
            # Pregunta sobre la respuesta anterior: se contesta con el contexto, sin consultar datos nuevos.
            answer = answer_from_context(question, context) or ""
            tool_rounds = max_rounds
        elif is_out_of_scope(question, context):
            # Ni la palta ni la estación ("¿cómo estuvo el partido?") o no se entiende: se repregunta.
            answer = _OUT_OF_SCOPE_TEMPLATE.format(station=station.name)

        # Rondas de herramientas + un posible recordatorio + una posible corrección.
        for _ in range(max_rounds + 3):
            if answer:
                yield ChatEvent("delta", text=answer)
                break
            offer_tools = tool_rounds < max_rounds
            # Mientras no haya datos consultados, no se transmite: la respuesta
            # podría ser un valor inventado que hay que descartar.
            stream_text = bool(executions)
            # Si los datos no son del periodo pedido (estación sin enviar), la nota va primero, siempre.
            prefix = _adjusted_period_note(executions)
            # "La temperatura máxima…" → "La temperatura ambiente máxima…": el sensor siempre con su nombre completo.
            label = _queried_sensor_label(executions)
            namer = _SensorNamer(label)
            shown = False
            text_parts: list[str] = []
            calls: list[ToolCall] = []

            async for chunk in self._llm.stream_chat(messages, toolbox.definitions if offer_tools else None):
                if chunk.tool_calls:
                    if text_parts and stream_text and not calls:
                        yield ChatEvent("reset")
                    calls.extend(chunk.tool_calls)
                if chunk.text:
                    piece = chunk.text.translate(_MARKDOWN)  # la app muestra texto plano
                    text_parts.append(piece)
                    if stream_text and not calls and (out := namer.feed(piece)):
                        if prefix and not shown:
                            yield ChatEvent("delta", text=prefix)
                        shown = True
                        yield ChatEvent("delta", text=out)
            if stream_text and not calls and (rest := namer.flush()):
                if prefix and not shown:
                    yield ChatEvent("delta", text=prefix)
                yield ChatEvent("delta", text=rest)

            text = name_sensor("".join(text_parts), label).strip()

            if not calls:
                if not executions and not reminded and offer_tools and _needs_data(text):
                    logger.warning("Respuesta con datos sin consultar herramientas; se pide reintento")
                    reminded = True
                    messages += [{"role": "assistant", "content": text}, {"role": "user", "content": _GROUNDING_REMINDER}]
                    continue
                evidence = [e.output for e in executions] + [REFERENCE_TEXT]
                unsupported = find_unsupported_values(text, evidence) if executions else []
                if unsupported and not corrected:
                    logger.warning("Valores no respaldados por los datos %s; se regenera la respuesta", unsupported)
                    corrected = True
                    if stream_text:
                        yield ChatEvent("reset")
                    messages += [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": _CORRECTION_TEMPLATE.format(values=", ".join(unsupported))},
                    ]
                    continue
                if unsupported:
                    logger.warning("La respuesta corregida aún contiene valores no respaldados: %s", unsupported)
                answer = prefix + text if text else _EMPTY_ANSWER
                # Una alerta seria (valor en exceso para la palta) nunca se omite, aunque el modelo la resuma.
                if alerts := _missing_alerts_note(answer, executions):
                    answer += alerts
                    if stream_text:
                        yield ChatEvent("delta", text=alerts)
                if note := _missing_quality_note(answer, executions):
                    answer += note
                    if stream_text:
                        yield ChatEvent("delta", text=note)
                if not stream_text:
                    yield ChatEvent("delta", text=answer)
                break

            tool_rounds += 1
            async for event in run_calls(calls, text):
                yield event
            answer = direct_answer(len(calls))
        else:
            answer = _EMPTY_ANSWER
            yield ChatEvent("delta", text=answer)

        new_context = _query_context(executions)
        if pending:
            new_context = replace(context or QueryContext("aclaracion"), pending_question=pending)
        elif new_context is None and context and context.pending_question:
            new_context = replace(context, pending_question=None)  # la repregunta ya no aplica
        self._memory.append(memory_key, question, answer, new_context)
        result = ChatResult(
            answer=answer,
            station_code=station.code,
            session_id=session_id,
            tools=executions,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        logger.info(
            "chat station=%s session=%s tools=%s duration_ms=%d",
            station.code,
            session_id,
            [(t.name, t.arguments, t.ok) for t in executions],
            result.duration_ms,
        )
        yield ChatEvent("done", result=result)

    async def station_exists(self, station_code: str) -> bool:
        return await run_in_threadpool(self._repo.get_station, station_code) is not None

    def reset_session(self, station_code: str, user_id: str, session_id: str) -> None:
        self._memory.clear(f"{user_id}:{station_code}:{session_id}")


# Lo que puede seguir a "temperatura"/"humedad" para indicar de cuál se habla, justo después o
# tras una o dos palabras ("humedad promedio del suelo", "temperatura máxima registrada del aire").
_PLACE = re.compile(
    r"(?:\s+[^\W\d]+){0,2}?(?P<place>\s+(?:ambient\w*|relativa|del?\s+(?:suelo|aire|ambiente)|de la tierra|en el suelo))\b",
    re.IGNORECASE,
)
# Solo se revisa la primera mención, dentro del inicio de la respuesta.
_NAMING_WINDOW = 300
_LOOKAHEAD = 40


def _queried_sensor_label(executions: list[ToolExecution]) -> str | None:
    """'temperatura ambiente' si en el turno se consultó un único sensor de temperatura o humedad."""
    keys = {
        str(e.arguments.get("sensor", "")).strip().lower()
        for e in executions
        if e.name == STATS and e.ok and not e.output.get("sin_datos")
    }
    if len(keys) != 1:
        return None
    key = keys.pop()
    if key not in SENSORS or not key.startswith(("temperatura", "humedad")):
        return None
    return SENSORS[key].label.lower()


def name_sensor(text: str, label: str | None) -> str:
    """Primera mención genérica ('la temperatura máxima') → nombre completo ('la temperatura ambiente
    máxima'); si nombra el otro sensor ('humedad del suelo' cuando era la ambiente), se corrige."""
    if not label:
        return text
    kind, place = label.split(" ", 1)  # "temperatura", "ambiente" | "del suelo"
    m = re.search(rf"\b{kind}\b", text[:_NAMING_WINDOW], re.IGNORECASE)
    if not m:
        return text
    if q := _PLACE.match(text, m.end()):
        named = q.group("place").lower()
        same = ("suelo" in named or "tierra" in named) == ("suelo" in place)
        if same:
            return text
        # Se quita el lugar equivocado y se nombra el correcto junto a "humedad"/"temperatura".
        return text[: m.end()] + " " + place + text[m.end() : q.start("place")] + text[q.end("place") :]
    return text[: m.end()] + " " + place + text[m.end() :]


class _SensorNamer:
    """Aplica `name_sensor` al texto en streaming: retiene solo el inicio hasta poder decidir."""

    def __init__(self, label: str | None):
        self._label = label
        self._buffer = ""
        self._done = label is None

    def feed(self, piece: str) -> str:
        if self._done:
            return piece
        self._buffer += piece
        m = re.search(rf"\b{self._label.split(' ')[0]}\b", self._buffer[:_NAMING_WINDOW], re.IGNORECASE)
        ready = (m and len(self._buffer) >= m.end() + _LOOKAHEAD) or (not m and len(self._buffer) >= _NAMING_WINDOW)
        return self.flush() if ready else ""

    def flush(self) -> str:
        if self._done:
            return ""
        self._done = True
        out, self._buffer = name_sensor(self._buffer, self._label), ""
        return out


def _adjusted_period_note(executions: list[ToolExecution]) -> str:
    notes = dict.fromkeys(e.output["periodo_ajustado"] for e in executions if e.output.get("periodo_ajustado"))
    return "".join(f"{n}\n\n" for n in notes)


def _needs_data(text: str) -> bool:
    """La respuesta da mediciones (que no son referencias de palta) o afirma que no hay datos."""
    if _NO_DATA_CLAIM.search(text):
        return True
    if not _MEASUREMENT.search(text):
        return False
    return not _REFERENCE_WORDS.search(text) or bool(find_unsupported_values(text, [REFERENCE_TEXT]))


def _query_context(executions: list[ToolExecution]) -> QueryContext | None:
    """Qué se consultó en este turno (la última herramienta con datos), para las preguntas de seguimiento."""
    ok = [e for e in executions if e.ok and not e.output.get("sin_datos")]
    if not ok:
        return None
    tool = ok[-1].name
    if tool not in (STATS, DIAGNOSIS, COUNT):
        return QueryContext(LATEST)
    same = [e for e in ok if e.name == tool]
    sensors = tuple(
        dict.fromkeys(str(e.arguments["sensor"]).strip().lower() for e in same if e.arguments.get("sensor"))
    )
    out = same[-1].output
    return QueryContext(tool, sensors, str(out.get("desde", ""))[:10] or None, str(out.get("hasta", ""))[:10] or None)


def _missing_alerts_note(answer: str, executions: list[ToolExecution]) -> str:
    """Alertas de la palta que la respuesta no comunicó (texto a añadir, una viñeta por alerta)."""
    alerts = list(dict.fromkeys(a for e in executions for a in e.output.get("alertas_palta", [])))
    if not alerts or _RECOMMENDATION_MENTIONED.search(answer):
        return ""
    return "\n\n" + "\n".join(f"• {a}" for a in alerts)


def _missing_quality_note(answer: str, executions: list[ToolExecution]) -> str:
    """Avisos de calidad de las herramientas que la respuesta no comunicó (texto a añadir)."""
    warnings = list(dict.fromkeys(w for e in executions for w in e.output.get("avisos", [])))
    if not warnings or _WARNING_MENTIONED.search(answer):
        return ""
    return "\n\n" + "\n".join(f"Aviso: {w}" for w in warnings)
