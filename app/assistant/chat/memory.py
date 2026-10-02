"""Historial de conversación por (usuario, estación, sesión).

Solo se guardan preguntas y respuestas finales, no los datos crudos de las
herramientas: mantiene el contexto pequeño (importante en CPU). Además se guarda
qué se consultó por última vez (sensores y fechas), para que las preguntas de
seguimiento ("¿y el mínimo?", "¿es ambiental o de suelo?") sigan la secuencia.

La implementación en memoria sirve para un solo proceso. Con varios workers
o réplicas, implementar `ConversationStore` sobre Redis.
"""

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Protocol

from app.assistant.llm.base import Message


@dataclass(frozen=True)
class QueryContext:
    """Última consulta de datos de la conversación."""

    tool: str                       # lecturas_actuales | estadisticas_sensor | diagnostico_palta
    sensors: tuple[str, ...] = ()   # claves de sensor (vacío = todos)
    fecha_inicio: Optional[str] = None  # YYYY-MM-DD del rango consultado
    fecha_fin: Optional[str] = None
    # Pregunta que espera "¿ambiente o del suelo?": se completa con la respuesta del usuario.
    pending_question: Optional[str] = None


class ConversationStore(Protocol):
    def get(self, key: str) -> list[Message]: ...

    def get_context(self, key: str) -> QueryContext | None: ...

    def append(self, key: str, question: str, answer: str, context: QueryContext | None = None) -> None: ...

    def clear(self, key: str) -> None: ...


class InMemoryConversationStore:
    def __init__(self, max_turns: int, ttl_seconds: int, max_sessions: int):
        self._max_messages = max_turns * 2
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._data: OrderedDict[str, tuple[float, list[Message], QueryContext | None]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> list[Message]:
        with self._lock:
            entry = self._live_entry(key)
            return list(entry[1]) if entry else []

    def get_context(self, key: str) -> QueryContext | None:
        with self._lock:
            entry = self._live_entry(key)
            return entry[2] if entry else None

    def append(self, key: str, question: str, answer: str, context: QueryContext | None = None) -> None:
        """Guarda el turno; sin `context` se conserva el de la consulta anterior."""
        with self._lock:
            _, messages, previous = self._data.pop(key, (0.0, [], None))
            messages = (
                messages + [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
            )[-self._max_messages :]
            self._data[key] = (time.monotonic(), messages, context or previous)
            while len(self._data) > self._max_sessions:
                self._data.popitem(last=False)  # descarta la sesión menos reciente

    def clear(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def _live_entry(self, key: str):
        entry = self._data.get(key)
        if entry is not None and time.monotonic() - entry[0] > self._ttl:
            del self._data[key]
            return None
        return entry
