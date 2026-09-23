"""Testes isolados: biometria nunca substitui a verificacao criptografica no servidor."""
import os
from types import SimpleNamespace

os.environ.setdefault("DISMEPE_SUPABASE_PUBLISHABLE_KEY", "pk_test")
os.environ.setdefault("DISMEPE_EDGE_TOKEN", "edge_test")
os.environ.setdefault("DISMEPE_AUTH_PEPPER", "pepper_test")
os.environ.setdefault("DISMEPE_JWT_SECRET", "x" * 48)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import passkeys


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(passkeys.router)
    return TestClient(app, base_url="https://dismepeone.com.br")


def test_somente_dominio_oficial():
    app = FastAPI()
    app.include_router(passkeys.router)
    external = TestClient(app, base_url="https://dismepeone.onrender.com")
    assert external.get("/passkeys/availability").status_code == 403
    assert TestClient(app, base_url="https://dismepeone.com.br").get("/passkeys/availability").json()["escopo"] == "INDUSTRIA"


def test_cadastro_nao_inicia_sem_confirmar_senha(client, monkeypatch):
    async def user(_session):
        return {"usuario": "industria.teste", "nome": "Teste"}
    async def bad_password(**kwargs):
        raise passkeys.InvalidCredentials("senha errada")
    calls = []
    async def edge(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Nao deve criar desafio com senha incorreta.")
    monkeypatch.setattr(passkeys, "logged_industry", user)
    monkeypatch.setattr(passkeys, "login_via_edge", bad_password)
    monkeypatch.setattr(passkeys, "edge", edge)
    response = client.post(
        "/passkeys/register/options",
        json={"senha": "incorreta"},
        headers={"Origin": passkeys.ORIGIN},
        cookies={passkeys.COOKIE: "sessao.fake"},
    )
    assert response.status_code == 401
    assert not calls


def test_login_nao_cria_sessao_sem_assinatura_verificada(client, monkeypatch):
    actions = []
    credential_id = passkeys.b64(b"test-credential-0000001")
    async def fake_edge(action, **kwargs):
        actions.append(action)
        if action == "CREDENTIAL_GET":
            return {"sucesso": True, "usuario": {"usuario": "industria.teste", "tipo": "INDUSTRIA"},
                    "credencial": {"public_key": passkeys.b64(b"testkey" * 20), "sign_count": 0}}
        if action == "CHALLENGE_CONSUME":
            return {"sucesso": True, "desafio": passkeys.b64(b"challenge" * 4)}
        raise AssertionError("A sessao nao pode ser emitida sem assinatura.")
    def invalid_signature(**kwargs):
        raise ValueError("signature check failed")
    monkeypatch.setattr(passkeys, "edge", fake_edge)
    monkeypatch.setattr(passkeys, "verify_authentication_response", invalid_signature)
    response = client.post(
        "/passkeys/login/verify",
        json={"id": "00000000-0000-0000-0000-000000000001",
              "usuario": "industria.teste",
              "credencial": {"id": credential_id, "response": {}}},
        headers={"Origin": passkeys.ORIGIN},
    )
    assert response.status_code == 401
    assert "CREDENTIAL_TOUCH" not in actions
    assert passkeys.COOKIE not in response.cookies


def test_login_exige_origin_canonica(client):
    response = client.post(
        "/passkeys/login/options",
        json={"usuario": "industria.teste"},
        headers={"Origin": "https://dismepeone.onrender.com"},
    )
    assert response.status_code == 403
