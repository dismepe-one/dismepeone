"""Leitura dos indicadores manuais de HERBAMED no PostgreSQL via Edge.

O Apps Script faz CONFIG_GET para estas mesmas chaves. Este modulo realiza
somente leitura e rejeita indicadores ausentes; nunca assume valor zero.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .config import Settings

KEYS = ("FATURAMENTO_GERAL_MANUAL", "POSITIVACAO_GERAL_MANUAL")


class MonthlyManualIndicatorError(RuntimeError):
    pass


def parse_manual_indicators(result: dict[str, Any]) -> dict[str, Decimal]:
    if not isinstance(result, dict) or result.get("sucesso") is not True:
        raise MonthlyManualIndicatorError("Indicadores manuais nao confirmados pelo SQL.")
    vals = result.get("valores")
    if not isinstance(vals, dict) or any(key not in vals or vals[key] is None for key in KEYS):
        raise MonthlyManualIndicatorError("Falta indicador manual obrigatorio no PostgreSQL.")
    parsed = {}
    for key in KEYS:
        raw = vals[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)) or str(raw).strip() == "":
            raise MonthlyManualIndicatorError("Indicador manual invalido no SQL.")
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise MonthlyManualIndicatorError("Indicador manual nao numerico.") from exc
        if not value.is_finite() or value < 0:
            raise MonthlyManualIndicatorError("Indicador manual invalido ou negativo.")
        parsed[key] = value
    return parsed


async def read_manual_indicators(settings: Settings) -> dict[str, Decimal]:
    if not settings.edge_token or not settings.supabase_publishable_key:
        raise MonthlyManualIndicatorError("Credenciais da Edge nao configuradas no Render.")
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json={"acao": "CONFIG_GET", "chaves": list(KEYS)},
            )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MonthlyManualIndicatorError("Falha na leitura dos indicadores do SQL.") from exc
    return parse_manual_indicators(result)
