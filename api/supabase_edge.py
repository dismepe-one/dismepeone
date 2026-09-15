from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .security import normalizar, senha_interna


class InvalidCredentials(Exception):
    pass


class UpstreamUnavailable(Exception):
    pass


async def login_via_edge(
    *,
    usuario: str,
    senha: str,
    settings: Settings,
) -> dict[str, Any]:
    """
    Fase 1 segura:
    chama DIRETAMENTE a Edge Function dismepe-admin, eliminando:
      browser -> dismepe-gateway -> Apps Script -> dismepe-admin

    Novo caminho:
      browser -> FastAPI -> dismepe-admin

    Isso preserva a regra de autenticação já existente no Supabase.
    """
    endpoint = (
        settings.supabase_url.rstrip("/")
        + "/functions/v1/dismepe-admin"
    )

    payload = {
        "acao": "LOGIN",
        "usuario_norm": normalizar(usuario),
        "senha_interna": senha_interna(
            usuario,
            senha,
            settings.auth_pepper,
        ),
    }

    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }

    # G9D1 — a autenticação pode coincidir com as leituras iniciais de snapshot
    # na mesma Edge Function. Falhas transitórias (5xx/408/429/rede) recebem
    # poucas tentativas curtas; 401/credencial inválida nunca é repetido.
    retry_delays = (0.0, 0.18, 0.45)
    last_exc: Exception | None = None
    response = None
    data: dict[str, Any] = {}

    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds
    ) as client:
        for attempt, delay in enumerate(retry_delays, start=1):
            if delay:
                import asyncio
                await asyncio.sleep(delay)

            try:
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < len(retry_delays):
                    continue
                raise UpstreamUnavailable(
                    "Serviço de autenticação temporariamente indisponível."
                ) from exc

            data = {}
            try:
                data = response.json()
            except ValueError:
                data = {}

            if (
                response.status_code == 401
                and data.get("credencialInvalida") is True
            ):
                raise InvalidCredentials("Usuário ou senha incorretos.")

            transient_status = (
                response.status_code in {408, 429}
                or 500 <= response.status_code <= 599
            )
            if transient_status and attempt < len(retry_delays):
                print(
                    "[G9D1 AUTH] upstream transitório",
                    response.status_code,
                    f"tentativa {attempt}/{len(retry_delays)}",
                )
                continue

            break

    if response is None:
        raise UpstreamUnavailable(
            "Serviço de autenticação temporariamente indisponível."
        ) from last_exc

    if response.status_code < 200 or response.status_code >= 300:
        raise UpstreamUnavailable(
            f"Autenticação upstream respondeu HTTP {response.status_code}."
        )

    if data.get("sucesso") is not True or not isinstance(
        data.get("usuario"), dict
    ):
        raise UpstreamUnavailable(
            "Resposta inválida do serviço de autenticação."
        )

    return data["usuario"]
