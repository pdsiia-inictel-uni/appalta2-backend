"""Composición de dependencias del asistente.

Se construyen de forma perezosa (en la primera consulta) para que el backend
arranque igual aunque Ollama no esté disponible, y se liberan al apagar.
"""

import logging
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import Engine

from app.assistant.chat.memory import InMemoryConversationStore
from app.assistant.chat.service import ChatService
from app.assistant.config import AssistantSettings, get_settings
from app.assistant.data.db import create_db_engine
from app.assistant.data.repository import SqlMeasurementRepository
from app.assistant.llm.ollama import OllamaClient

logger = logging.getLogger(__name__)


class AssistantContainer:
    def __init__(self, settings: AssistantSettings, clock: Optional[Callable[[], datetime]] = None):
        self.settings = settings
        self.engine: Engine = create_db_engine(settings)
        self.llm = OllamaClient(settings)
        memory = InMemoryConversationStore(
            max_turns=settings.chat_history_turns,
            ttl_seconds=settings.chat_session_ttl_seconds,
            max_sessions=settings.chat_max_sessions,
        )
        self.chat_service = ChatService(settings, self.llm, SqlMeasurementRepository(self.engine), memory, clock=clock)
        logger.info("Asistente IA inicializado (modelo=%s, ollama=%s)", settings.llm_model, settings.llm_base_url)

    async def aclose(self) -> None:
        await self.llm.aclose()
        self.engine.dispose()


_container: Optional[AssistantContainer] = None


def get_container() -> AssistantContainer:
    global _container
    if _container is None:
        _container = AssistantContainer(get_settings())
    return _container


async def shutdown_container() -> None:
    global _container
    if _container is not None:
        await _container.aclose()
        _container = None
