import asyncio
from types import SimpleNamespace

import httpx
import pytest

from api import supabase_edge


class _FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _settings():
    return SimpleNamespace(
        supabase_url='https://example.supabase.co',
        supabase_publishable_key='pub',
        edge_token='edge',
        auth_pepper='pepper',
        request_timeout_seconds=1.0,
    )


@pytest.mark.asyncio
async def test_auth_retries_http_500_then_succeeds(monkeypatch):
    client = _FakeClient([
        _FakeResponse(500, {'erro': 'transient'}),
        _FakeResponse(200, {'sucesso': True, 'usuario': {'usuario': 'teste'}}),
    ])
    monkeypatch.setattr(supabase_edge.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr(supabase_edge, 'senha_interna', lambda *args: 'hash')
    profile = await supabase_edge.login_via_edge(usuario='teste', senha='x', settings=_settings())
    assert profile['usuario'] == 'teste'
    assert client.calls == 2


@pytest.mark.asyncio
async def test_auth_does_not_retry_invalid_credentials(monkeypatch):
    client = _FakeClient([
        _FakeResponse(401, {'credencialInvalida': True}),
        _FakeResponse(200, {'sucesso': True, 'usuario': {'usuario': 'nao-deve'}}),
    ])
    monkeypatch.setattr(supabase_edge.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr(supabase_edge, 'senha_interna', lambda *args: 'hash')
    with pytest.raises(supabase_edge.InvalidCredentials):
        await supabase_edge.login_via_edge(usuario='teste', senha='errada', settings=_settings())
    assert client.calls == 1


@pytest.mark.asyncio
async def test_auth_stops_after_three_500s(monkeypatch):
    client = _FakeClient([
        _FakeResponse(500, {}),
        _FakeResponse(502, {}),
        _FakeResponse(500, {}),
    ])
    monkeypatch.setattr(supabase_edge.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr(supabase_edge, 'senha_interna', lambda *args: 'hash')
    with pytest.raises(supabase_edge.UpstreamUnavailable, match='HTTP 500'):
        await supabase_edge.login_via_edge(usuario='teste', senha='x', settings=_settings())
    assert client.calls == 3
