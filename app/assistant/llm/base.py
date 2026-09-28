"""Contrato del proveedor de modelo. Cambiar Ollama por vLLM u otro servicio
solo requiere una nueva implementación de `LLMClient`."""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMChunk:
    """Fragmento de una respuesta en streaming: texto y/o llamadas a herramientas."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMError(Exception):
    """Error genérico del proveedor de modelo."""


class LLMBusyError(LLMError):
    """Demasiadas peticiones simultáneas; el cliente debe reintentar más tarde."""


class LLMUnavailableError(LLMError):
    """El servicio del modelo no responde o devolvió un error."""


class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMChunk]: ...

    async def is_ready(self) -> bool: ...

    async def aclose(self) -> None: ...
