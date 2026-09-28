import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.assistant.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.assistant.chat.prompts import OUT_OF_SERVICE_MESSAGE
from app.assistant.chat.service import ChatResult, ChatService, StationNotFoundError
from app.assistant.container import get_container, shutdown_container
from app.assistant.llm.base import LLMBusyError, LLMError
from app.services.auth import ALGORITHM, SECRET_KEY

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    # Las dependencias se crean en la primera consulta; aquí solo se liberan al apagar.
    yield
    await shutdown_container()


router = APIRouter(tags=["Assistant"], lifespan=lifespan)

StationCode = Path(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
_bearer = HTTPBearer(auto_error=False)


def get_chat_service() -> ChatService:
    return get_container().chat_service


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> str:
    """Valida el access token emitido por el backend (misma SECRET_KEY) y devuelve el email.

    Se valida aquí en lugar de usar app.services.auth.verify_token porque esa
    función devuelve (no lanza) la excepción cuando el token es inválido.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise unauthorized
    subject = payload.get("sub")
    if not subject:
        raise unauthorized
    return subject


@router.post("/chat/{station_code}", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    station_code: str = StationCode,
    user: str = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """Respuesta completa del asistente en JSON."""
    try:
        result = await service.ask(station_code, body.question, user, body.session_id)
    except StationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estación no encontrada")
    except LLMBusyError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Asistente ocupado, intenta en unos segundos")
    except LLMError:
        logger.exception("Fallo del modelo")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, OUT_OF_SERVICE_MESSAGE)
    return _to_response(result)


@router.post("/chat/{station_code}/stream")
async def chat_stream(
    body: ChatRequest,
    station_code: str = StationCode,
    user: str = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Respuesta en streaming (Server-Sent Events): `tool`, `delta`, `reset`, `done` y `error`."""
    # La estación se valida antes de abrir el stream para responder 404 normal.
    if not await service.station_exists(station_code):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estación no encontrada")

    async def events() -> AsyncIterator[str]:
        try:
            async for event in service.ask_stream(station_code, body.question, user, body.session_id):
                if event.type == "done":
                    yield _sse("done", _to_response(event.result).model_dump())
                elif event.type == "tool":
                    yield _sse("tool", {"name": event.tool})
                elif event.type == "reset":
                    yield _sse("reset", {})
                else:
                    yield _sse("delta", {"text": event.text})
        except LLMBusyError:
            yield _sse("error", {"message": "Asistente ocupado, intenta en unos segundos"})
        except LLMError:
            logger.exception("Fallo del modelo (stream)")
            yield _sse("error", {"message": OUT_OF_SERVICE_MESSAGE})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/chat/{station_code}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_session(
    session_id: str,
    station_code: str = StationCode,
    user: str = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> None:
    """Reinicia la conversación de una sesión."""
    service.reset_session(station_code, user, session_id)


@router.get("/assistant/health", response_model=HealthResponse)
async def assistant_health() -> HealthResponse:
    """Estado del asistente: base de datos accesible y modelo descargado en Ollama."""
    container = get_container()
    db_ok = await run_in_threadpool(_check_db, container.engine)
    model_ok = await container.llm.is_ready()
    if not (db_ok and model_ok):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            HealthResponse(status="unavailable", database=db_ok, model=model_ok).model_dump(),
        )
    return HealthResponse(status="ok", database=db_ok, model=model_ok)


def _check_db(engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Base de datos no disponible para el asistente")
        return False


def _to_response(result: ChatResult) -> ChatResponse:
    return ChatResponse(
        answer=result.answer,
        station_code=result.station_code,
        session_id=result.session_id,
        tools=[asdict(t) for t in result.tools],
        duration_ms=result.duration_ms,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
