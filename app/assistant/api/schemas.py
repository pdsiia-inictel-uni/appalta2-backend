import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.assistant.config import get_settings


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, examples=["¿Cuál fue la temperatura máxima de ayer?"])
    # La app genera un id por conversación; si no lo envía, se crea uno nuevo.
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=64)

    @field_validator("question")
    @classmethod
    def _check_length(cls, v: str) -> str:
        v = v.strip()
        limit = get_settings().chat_max_question_chars
        if not v:
            raise ValueError("La pregunta no puede estar vacía")
        if len(v) > limit:
            raise ValueError(f"La pregunta no puede superar {limit} caracteres")
        return v


class ToolUsage(BaseModel):
    name: str
    arguments: dict[str, Any]
    ok: bool


class ChatResponse(BaseModel):
    answer: str
    station_code: str
    session_id: str
    tools: list[ToolUsage]
    duration_ms: int


class HealthResponse(BaseModel):
    status: str
    database: bool | None = None
    model: bool | None = None
