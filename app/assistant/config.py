from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    """Configuración del asistente, leída del mismo .env del backend.

    DATABASE_URL y la clave JWT se reutilizan del backend (app.database.connection
    y app.services.auth); aquí solo va lo propio del asistente. Todo tiene valores
    por defecto, así que el .env no necesita cambios para desarrollo local.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    timezone: str = "America/Lima"

    # Conexiones de solo lectura propias del asistente (aisladas del pool de la API)
    assistant_db_pool_size: int = 3
    assistant_db_max_overflow: int = 2
    assistant_db_statement_timeout_ms: int = 5000

    # Modelo de lenguaje (Ollama)
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e2b"
    llm_think: bool = False
    llm_temperature: float = 0.1
    llm_max_tokens: int = 400
    llm_context_tokens: int = 8192
    llm_keep_alive: str = "30m"
    llm_timeout_seconds: float = 180
    # En CPU conviene atender pocas generaciones a la vez; el resto espera en cola.
    llm_max_concurrency: int = 2
    llm_queue_timeout_seconds: float = 60

    # Chat
    chat_max_question_chars: int = 500
    chat_history_turns: int = 4
    chat_session_ttl_seconds: int = 1800
    chat_max_sessions: int = 5000
    chat_max_tool_rounds: int = 3


@lru_cache
def get_settings() -> AssistantSettings:
    return AssistantSettings()
