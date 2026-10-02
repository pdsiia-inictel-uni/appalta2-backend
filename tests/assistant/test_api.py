from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.assistant import assistant_router
from app.assistant.api.router import get_chat_service
from app.assistant.chat.memory import InMemoryConversationStore
from app.assistant.chat.service import ChatService
from app.assistant.config import get_settings
from app.assistant.llm.base import LLMChunk
from app.services.auth import ALGORITHM, SECRET_KEY, create_access_token
from tests.assistant.conftest import NOW, FakeRepository, ScriptedLLM, tool_call


@pytest.fixture
def client():
    # App mínima con el router montado igual que en app/main.py
    app = FastAPI()
    app.include_router(assistant_router, prefix="/api/v1")

    llm = ScriptedLLM([tool_call("lecturas_actuales"), LLMChunk(text="Hace 20.0 °C.")])
    service = ChatService(get_settings(), llm, FakeRepository(), InMemoryConversationStore(4, 60, 10), clock=lambda: NOW)
    app.dependency_overrides[get_chat_service] = lambda: service

    with TestClient(app) as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def backend_token(sub="agricultor@test.pe"):
    # Mismo token que emite /api/v1/user/login
    return auth(create_access_token({"sub": sub}))


URL = "/api/v1/chat/EST001-PALTAS"


def test_requires_token(client):
    assert client.post(URL, json={"question": "hola"}).status_code == 401


def test_rejects_token_signed_with_other_key(client):
    fake = jwt.encode({"sub": "x@test.pe"}, "otra-clave", algorithm=ALGORITHM)
    assert client.post(URL, json={"question": "hola"}, headers=auth(fake)).status_code == 401


def test_rejects_expired_token(client):
    expired = jwt.encode(
        {"sub": "x@test.pe", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, SECRET_KEY, algorithm=ALGORITHM
    )
    assert client.post(URL, json={"question": "hola"}, headers=auth(expired)).status_code == 401


def test_chat_with_backend_token(client):
    resp = client.post(URL, json={"question": "¿Clima?", "session_id": "abc"}, headers=backend_token())
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Hace 20.0 °C."
    assert body["session_id"] == "abc"
    assert body["tools"][0]["name"] == "lecturas_actuales"


def test_unknown_station_404(client):
    assert client.post("/api/v1/chat/EST999", json={"question": "hola"}, headers=backend_token()).status_code == 404


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_question_validation(client, question):
    assert client.post(URL, json={"question": question}, headers=backend_token()).status_code == 422


def test_stream_sse(client):
    with client.stream("POST", f"{URL}/stream", json={"question": "¿Clima?"}, headers=backend_token()) as resp:
        body = "".join(resp.iter_text())
    assert resp.status_code == 200
    assert "event: tool" in body and "event: delta" in body and "event: done" in body
