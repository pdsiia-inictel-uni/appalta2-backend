"""Historial de conversación por (usuario, estación, sesión).

Solo se guardan preguntas y respuestas finales, no los datos crudos de las
herramientas: mantiene el contexto pequeño (importante en CPU).

La implementación en memoria sirve para un solo proceso. Con varios workers
o réplicas, implementar `ConversationStore` sobre Redis.
"""

import threading
import time
from collections import OrderedDict
from typing import Protocol

from app.assistant.llm.base import Message


class ConversationStore(Protocol):
    def get(self, key: str) -> list[Message]: ...

    def append(self, key: str, question: str, answer: str) -> None: ...

    def clear(self, key: str) -> None: ...


class InMemoryConversationStore:
    def __init__(self, max_turns: int, ttl_seconds: int, max_sessions: int):
        self._max_messages = max_turns * 2
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._data: OrderedDict[str, tuple[float, list[Message]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> list[Message]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return []
            updated_at, messages = entry
            if time.monotonic() - updated_at > self._ttl:
                del self._data[key]
                return []
            return list(messages)

    def append(self, key: str, question: str, answer: str) -> None:
        with self._lock:
            _, messages = self._data.pop(key, (0.0, []))
            messages = (
                messages + [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
            )[-self._max_messages :]
            self._data[key] = (time.monotonic(), messages)
            while len(self._data) > self._max_sessions:
                self._data.popitem(last=False)  # descarta la sesión menos reciente

    def clear(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
