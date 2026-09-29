"""Orquestador del chat: modelo ⇄ herramientas ⇄ base de datos.

Flujo por pregunta:
1. El servidor resuelve la estación (nunca el modelo).
2. Se envía al modelo: prompt del sistema + historial + pregunta + herramientas.
3. Si el modelo pide herramientas, se ejecutan contra ESA estación y el
   resultado vuelve al modelo. Máximo `chat_max_tool_rounds` rondas.
4. La respuesta final se transmite por partes (streaming).
5. Cada medición de la respuesta se verifica contra los datos consultados; si
   hay un valor no respaldado, se descarta (evento reset) y se regenera una vez.
6. Si los datos traen avisos de calidad (sensor desconectado, lecturas
   descartadas) y la respuesta no los menciona, se añaden al final.
7. Si no hay datos del periodo pedido (o las lecturas "actuales" no son de hoy),
   la herramienta trae una respuesta_directa redactada por el código y se entrega
   tal cual, sin otra llamada al modelo: siempre exacta y más rápida.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Literal
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.assistant.chat.grounding import find_unsupported_values
from app.assistant.chat.memory import ConversationStore
from app.assistant.chat.prompts import build_system_prompt
from app.assistant.config import AssistantSettings
from app.assistant.data.repository import MeasurementRepository
from app.assistant.llm.base import LLMClient, Message, ToolCall
from app.assistant.tools.station_tools import StationToolbox

logger = logging.getLogger(__name__)

# Un número seguido de una unidad de sensor: señal de que el modelo está dando un dato.
_MEASUREMENT_PATTERN = re.compile(r"\d+(?:[.,]\d+)?\s*(?:°|%|hpa\b|ph\b)", re.IGNORECASE)
_GROUNDING_REMINDER = (
    "No inventes valores. Usa una herramienta para obtener los datos reales de la estación "
    "y luego responde la pregunta anterior."
)
_CORRECTION_TEMPLATE = (
    "Estos valores no aparecen en los datos consultados: {values}. Responde de nuevo la pregunta "
    "usando solo los valores exactos que devolvieron las herramientas."
)
_EMPTY_ANSWER = "No pude generar una respuesta. ¿Puedes reformular la pregunta?"
# Preguntas que piden un consejo: la respuesta directa aclara primero que no se dan recomendaciones.
_ADVICE_QUESTION = re.compile(
    r"\b(?:debo|deber[ií]a|deber[ií]amos|recomienda[sn]?|recomiendas|me aconsejas|conviene|qu[eé] hago|"
    r"es buen momento|necesito)\b",
    re.IGNORECASE,
)
_NO_ADVICE_PREFIX = "No doy recomendaciones agronómicas; solo informo los datos de la estación. "
# Palabras que indican que la respuesta ya comunicó un aviso de calidad de datos.
_WARNING_MENTIONED = re.compile(r"sensor|descart|desconect|falla|aviso", re.IGNORECASE)


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
        toolbox = StationToolbox(self._repo, station, self._settings.timezone, clock=self._clock, question=question)
        memory_key = f"{user_id}:{station.code}:{session_id}"

        messages: list[Message] = [
            {"role": "system", "content": build_system_prompt(station, now)},
            *self._memory.get(memory_key),
            {"role": "user", "content": question},
        ]
        executions: list[ToolExecution] = []
        reminded = False
        corrected = False
        answer = ""
        max_rounds = self._settings.chat_max_tool_rounds
        tool_rounds = 0

        # Rondas de herramientas + un posible recordatorio + una posible corrección.
        for _ in range(max_rounds + 3):
            offer_tools = tool_rounds < max_rounds
            # Mientras no haya datos consultados, no se transmite: la respuesta
            # podría ser un valor inventado que hay que descartar.
            stream_text = bool(executions)
            text_parts: list[str] = []
            calls: list[ToolCall] = []

            async for chunk in self._llm.stream_chat(messages, toolbox.definitions if offer_tools else None):
                if chunk.tool_calls:
                    if text_parts and stream_text and not calls:
                        yield ChatEvent("reset")
                    calls.extend(chunk.tool_calls)
                if chunk.text:
                    text_parts.append(chunk.text)
                    if stream_text and not calls:
                        yield ChatEvent("delta", text=chunk.text)

            text = "".join(text_parts).strip()

            if not calls:
                if not executions and not reminded and offer_tools and _MEASUREMENT_PATTERN.search(text):
                    logger.warning("Respuesta con datos sin consultar herramientas; se pide reintento")
                    reminded = True
                    messages += [{"role": "assistant", "content": text}, {"role": "user", "content": _GROUNDING_REMINDER}]
                    continue
                unsupported = find_unsupported_values(text, [e.output for e in executions]) if executions else []
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
                answer = text or _EMPTY_ANSWER
                if note := _missing_quality_note(answer, executions):
                    answer += note
                    if stream_text:
                        yield ChatEvent("delta", text=note)
                if not stream_text:
                    yield ChatEvent("delta", text=answer)
                break

            tool_rounds += 1
            messages.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls],
                }
            )
            round_outputs = []
            for call in calls:
                yield ChatEvent("tool", tool=call.name)
                output = await run_in_threadpool(toolbox.execute, call.name, call.arguments)
                round_outputs.append(output)
                executions.append(ToolExecution(call.name, call.arguments, "error" not in output, output))
                messages.append(
                    {"role": "tool", "tool_name": call.name, "content": json.dumps(output, ensure_ascii=False)}
                )
            if all("respuesta_directa" in o for o in round_outputs):
                answer = " ".join(dict.fromkeys(o["respuesta_directa"] for o in round_outputs))
                if _ADVICE_QUESTION.search(question):
                    answer = _NO_ADVICE_PREFIX + answer
                yield ChatEvent("delta", text=answer)
                break
        else:
            answer = _EMPTY_ANSWER
            yield ChatEvent("delta", text=answer)

        self._memory.append(memory_key, question, answer)
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


def _missing_quality_note(answer: str, executions: list[ToolExecution]) -> str:
    """Avisos de calidad de las herramientas que la respuesta no comunicó (texto a añadir)."""
    warnings = list(dict.fromkeys(w for e in executions for w in e.output.get("avisos", [])))
    if not warnings or _WARNING_MENTIONED.search(answer):
        return ""
    return "".join(f" Aviso: {w}" for w in warnings)
