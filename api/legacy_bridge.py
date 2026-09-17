from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import Settings


_STATE: dict[str, dict[str, Any]] = {}
_LOCK = asyncio.Lock()

LEGACY_TTL_SECONDS = 3 * 60 * 60


def _now() -> float:
    return time.time()


async def _cleanup() -> None:
    limite = _now() - LEGACY_TTL_SECONDS
    async with _LOCK:
        expiradas = [
            key
            for key, value in _STATE.items()
            if float(value.get("updated_at") or 0) < limite
        ]
        for key in expiradas:
            _STATE.pop(key, None)


async def mark_pending(session_key: str) -> None:
    await _cleanup()
    async with _LOCK:
        _STATE[session_key] = {
            "status": "PENDING",
            "token": "",
            "error": "",
            "started_at": _now(),
            "updated_at": _now(),
        }


async def get_state(session_key: str) -> dict[str, Any]:
    await _cleanup()
    async with _LOCK:
        state = dict(_STATE.get(session_key) or {})
    if not state:
        return {
            "status": "MISSING",
            "token": "",
            "error": "",
        }
    return state


async def clear_state(session_key: str) -> None:
    async with _LOCK:
        _STATE.pop(session_key, None)


async def run_legacy_login(
    *,
    session_key: str,
    usuario: str,
    senha: str,
    settings: Settings,
) -> None:
    """
    Ponte temporária da Fase 1B.

    O login 2.0 já foi concluído antes desta função começar.
    Esta rotina obtém, em segundo plano, o token legado necessário
    apenas para os módulos 1.x que ainda não foram migrados.

    A senha existe apenas como argumento em memória durante esta chamada.
    Ela não é gravada no estado.
    """
    endpoint = (
        settings.supabase_url.rstrip("/")
        + "/functions/v1/dismepe-gateway"
    )

    payload = {
        "acao": "login",
        "usuario": usuario,
        "senha": senha,
    }

    try:
        async with httpx.AsyncClient(timeout=70.0) as client:
            response = await client.post(
                endpoint,
                json=payload,
                headers={
                    "content-type": "application/json",
                    "accept": "application/json",
                },
            )

        data: dict[str, Any] = {}
        try:
            data = response.json()
        except ValueError:
            data = {}

        # O frontend legado já reconhece estes formatos de resposta.
        # A ponte 2.0 precisa aceitar exatamente os mesmos aliases; antes ela
        # aceitava apenas data["token"], deixando a sessão presa em ERROR.
        legacy_token = str(
            data.get("token")
            or data.get("authToken")
            or data.get("sessionToken")
            or data.get("sessao")
            or data.get("session")
            or ""
        ).strip()

        ok = (
            response.status_code >= 200
            and response.status_code < 300
            and (
                data.get("sucesso") is True
                or data.get("success") is True
                or data.get("ok") is True
                or str(data.get("status") or "").strip().upper() == "OK"
            )
            and bool(legacy_token)
        )

        if not ok:
            message = str(
                data.get("erro")
                or data.get("error")
                or f"HTTP {response.status_code}"
            )
            async with _LOCK:
                _STATE[session_key] = {
                    "status": "ERROR",
                    "token": "",
                    "error": message[:500],
                    "updated_at": _now(),
                }
            return

        async with _LOCK:
            _STATE[session_key] = {
                "status": "READY",
                "token": legacy_token,
                "error": "",
                "updated_at": _now(),
            }

    except Exception as exc:
        async with _LOCK:
            _STATE[session_key] = {
                "status": "ERROR",
                "token": "",
                "error": str(exc)[:500],
                "updated_at": _now(),
            }
