from __future__ import annotations

import json
from typing import Any

import httpx


APPS_SCRIPT_UPDATE_CENTER_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbzqE0yKDkJKMI33nON2w4YywrVXu-5KZFPBfiCxIjvqiG1NQY-qiLK-4EiT5_ncbd0IPA/exec"
)
_ALLOWED_ACTIONS = {"OPCACHE_STATUS", "OPCACHE_ATUALIZAR"}


class UpdateCenterBridgeError(Exception):
    pass


async def call_update_center_legacy(
    *,
    action: str,
    payload: dict[str, Any],
    legacy_token: str,
) -> dict[str, Any]:
    """Transporta exclusivamente a Central para o Apps Script existente.

    OPCACHE_ATUALIZAR é enviado uma única vez. Não existe retry de escrita,
    evitando duplicidade quando uma resposta de rede for ambígua.
    """
    action = str(action or "").strip().upper()
    if action not in _ALLOWED_ACTIONS:
        raise UpdateCenterBridgeError("Ação não autorizada na Central de Atualizações.")

    token = str(legacy_token or "").strip()
    if not token:
        raise UpdateCenterBridgeError(
            "A sessão de compatibilidade ainda não está pronta. Saia e entre novamente no sistema."
        )

    body = dict(payload or {})
    body["acao"] = action
    body["token"] = token
    timeout_seconds = 210.0 if action == "OPCACHE_ATUALIZAR" else 45.0

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
        ) as client:
            response = await client.post(
                APPS_SCRIPT_UPDATE_CENTER_URL,
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "text/plain;charset=utf-8",
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise UpdateCenterBridgeError(
            "Falha temporária na comunicação com o servidor de atualizações."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise UpdateCenterBridgeError(
            f"O servidor de atualizações respondeu em formato inválido (HTTP {response.status_code})."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise UpdateCenterBridgeError(
            str(
                data.get("erro")
                or data.get("error")
                or f"Servidor de atualizações HTTP {response.status_code}."
            )
        )
    if not isinstance(data, dict):
        raise UpdateCenterBridgeError("Resposta inválida do servidor de atualizações.")
    return data
