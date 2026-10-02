"""Registro de usuarios: DNI de 8 dígitos (único) y celular de 9 dígitos.

No toca la BD: la sesión y las consultas de usuarios se reemplazan por dobles en memoria.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.database.connection import get_db
from app.routes import user as user_routes
from app.schemas.user import UserCreate

VALID = {
    "email": "agricultor@test.pe",
    "password": "Clave#2026",
    "firstname": "Juan",
    "father_lastname": "Pérez",
    "mother_lastname": "Quispe",
    "document_of_identity": "12345678",
    "cellphone": "987654321",
}


class FakeUser:
    def __init__(self, data):
        self.id = 1
        self.email = data.email
        self.firstname = data.firstname
        self.document_of_identity = data.document_of_identity
        self.is_verified = False


class FakeSession:
    def commit(self):
        pass

    def refresh(self, _):
        pass

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def users(monkeypatch):
    """Usuarios ya registrados (por correo y por DNI)."""
    registered: list[FakeUser] = []
    monkeypatch.setattr(user_routes.user_db, "get_user_by_email", lambda db, e: next((u for u in registered if u.email == e), None))
    monkeypatch.setattr(
        user_routes.user_db, "get_user_by_document",
        lambda db, d: next((u for u in registered if u.document_of_identity == d), None),
    )  # fmt: skip

    def create_user(db, data, token):
        u = FakeUser(data)
        registered.append(u)
        return u

    monkeypatch.setattr(user_routes.user_db, "create_user", create_user)
    return registered


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    """Correos de verificación "enviados" (sin conectarse a Gmail)."""
    sent: list[tuple[str, str]] = []

    async def fake_send(to, link):
        sent.append((to, link))

    monkeypatch.setattr(user_routes, "send_verification_email_gmail", fake_send)
    return sent


@pytest.fixture
def client(users):
    app = FastAPI()
    app.include_router(user_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: FakeSession()
    with TestClient(app) as c:
        yield c


URL = "/api/v1/user/register"


def test_valid_registration_sends_verification_email(client, users, sent_emails):
    resp = client.post(URL, json=VALID)
    assert resp.status_code == 200
    assert users[0].document_of_identity == "12345678"
    [(to, link)] = sent_emails
    assert to == "agricultor@test.pe"
    assert link.startswith(f"{user_routes.BACKEND_URL}/v1/user/verify/")


def test_rejected_registration_sends_no_email(client, sent_emails):
    client.post(URL, json={**VALID, "document_of_identity": "123"})
    assert sent_emails == []


@pytest.mark.parametrize("verified, status", [(False, 403), (True, 200)])
def test_login_requires_verified_email(monkeypatch, verified, status):
    user = FakeUser(UserCreate(**VALID))
    user.is_verified = verified
    user.father_lastname, user.mother_lastname = "Pérez", "Quispe"
    monkeypatch.setattr(user_routes.user_db, "autenticate_user", lambda db, e, p: user)
    app = FastAPI()
    app.include_router(user_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: FakeSession()
    with TestClient(app) as c:
        resp = c.post("/api/v1/user/login", json={"email": VALID["email"], "password": VALID["password"]})
    assert resp.status_code == status
    if not verified:
        assert resp.json()["detail"] == "Correo no verificado"


@pytest.mark.parametrize("dni", ["1234567", "123456789", "1234567a", "", "12 345 678"])
def test_dni_must_have_exactly_8_digits(client, dni):
    resp = client.post(URL, json={**VALID, "document_of_identity": dni})
    assert resp.status_code == 422
    assert "El número de DNI debe tener exactamente 8 dígitos" in resp.text


@pytest.mark.parametrize("cellphone", ["98765432", "9876543210", "98765432a", "", "+51987654321"])
def test_cellphone_must_have_exactly_9_digits(client, cellphone):
    resp = client.post(URL, json={**VALID, "cellphone": cellphone})
    assert resp.status_code == 422
    assert "El número de celular debe tener exactamente 9 dígitos" in resp.text


def test_surrounding_spaces_are_ignored():
    user = UserCreate(**{**VALID, "document_of_identity": " 12345678 ", "cellphone": "987654321 "})
    assert (user.document_of_identity, user.cellphone) == ("12345678", "987654321")


def test_dni_can_only_be_registered_once(client):
    assert client.post(URL, json=VALID).status_code == 200
    resp = client.post(URL, json={**VALID, "email": "otro@test.pe"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "El número de DNI ya está registrado"


def test_concurrent_duplicate_is_stopped_by_the_database(client, monkeypatch):
    # Dos registros a la vez: ambos pasan la consulta previa y la restricción UNIQUE de la BD rechaza el segundo.
    def create_user(db, data, token):
        raise IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint"))

    monkeypatch.setattr(user_routes.user_db, "create_user", create_user)
    resp = client.post(URL, json=VALID)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "El número de DNI o el correo ya está registrado"


def test_schema_rejects_invalid_values_directly():
    with pytest.raises(ValidationError):
        UserCreate(**{**VALID, "document_of_identity": "1234"})
