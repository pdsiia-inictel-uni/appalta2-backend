import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from app.assistant.config import AssistantSettings
from app.assistant.llm.base import LLMBusyError, LLMChunk, LLMUnavailableError, Message, ToolCall

logger = logging.getLogger(__name__)


class OllamaClient:
    """Cliente asíncrono para la API /api/chat de Ollama.

    Un semáforo limita cuántas generaciones corren a la vez: en un servidor
    sin GPU, lanzar muchas en paralelo las vuelve lentas a todas. Las demás
    esperan en cola hasta `llm_queue_timeout_seconds` y luego fallan con
    LLMBusyError (HTTP 503 para la app).
    """

    def __init__(self, settings: AssistantSettings):
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=5.0),
        )
        self._slots = asyncio.Semaphore(settings.llm_max_concurrency)

    async def stream_chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMChunk]:
        s = self._settings
        payload: dict[str, Any] = {
            "model": s.llm_model,
            "messages": messages,
            "stream": True,
            "think": s.llm_think,
            "keep_alive": s.llm_keep_alive,
            "options": {
                "temperature": s.llm_temperature,
                "num_predict": s.llm_max_tokens,
                "num_ctx": s.llm_context_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=s.llm_queue_timeout_seconds)
        except asyncio.TimeoutError as e:  # en Python 3.10 no es el TimeoutError nativo
            raise LLMBusyError("El asistente está atendiendo muchas consultas") from e

        try:
            async with self._http.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")[:300]
                    raise LLMUnavailableError(f"Ollama respondió {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMUnavailableError(f"Ollama: {data['error']}")
                    msg = data.get("message") or {}
                    chunk = LLMChunk(
                        text=msg.get("content") or "",
                        tool_calls=[_parse_tool_call(tc) for tc in msg.get("tool_calls") or []],
                    )
                    if chunk.text or chunk.tool_calls:
                        yield chunk
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"No se pudo conectar con Ollama: {e}") from e
        finally:
            self._slots.release()

    async def is_ready(self) -> bool:
        """True si Ollama responde y el modelo configurado está descargado."""
        try:
            resp = await self._http.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
        except httpx.HTTPError:
            return False
        names = {m.get("name") for m in resp.json().get("models", [])}
        return self._settings.llm_model in names

    async def aclose(self) -> None:
        await self._http.aclose()


def _parse_tool_call(raw: dict[str, Any]) -> ToolCall:
    fn = raw.get("function") or {}
    args = fn.get("arguments") or {}
    if isinstance(args, str):  # algunos modelos devuelven los argumentos como texto JSON
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return ToolCall(name=fn.get("name", ""), arguments=args if isinstance(args, dict) else {})
