from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from .industries import _edge_admin_write, _stock_update_profile, settings
from .industries_stock_sync import (
    SCHEDULE_CONFIG_KEY,
    set_stock_sync_schedules,
    stock_sync_public_status,
)


router = APIRouter()
BUILD = "PROD5.9.8.23"


class StockScheduleRequest(BaseModel):
    horarios: list[str]


def _normalize_times(values: list[Any]) -> list[str]:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if not match:
            raise HTTPException(status_code=400, detail=f"Horário inválido: {text or '(vazio)'}")
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            raise HTTPException(status_code=400, detail=f"Horário inválido: {text}")
        normalized = f"{hour:02d}:{minute:02d}"
        if normalized not in output:
            output.append(normalized)
    output.sort()
    if len(output) > 12:
        raise HTTPException(status_code=400, detail="É permitido cadastrar no máximo 12 horários por dia.")
    return output


@router.post("/admin/industries/stock-sync/schedule")
async def industries_stock_sync_schedule(
    body: StockScheduleRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _stock_update_profile(session)
    horarios = _normalize_times(body.horarios)
    usuario = str(profile.get("usuario") or profile.get("sub") or "")

    try:
        await _edge_admin_write(
            "CONFIG_SET",
            {
                "chave": SCHEDULE_CONFIG_KEY,
                "valor": {
                    "horarios": horarios,
                    "timezone": "America/Recife",
                    "schema": "INDUSTRIES_STOCK_SCHEDULE_V1",
                },
                "categoria": "INDUSTRIAS",
                "descricao": "Horários automáticos de atualização do Mapa de Estoque.",
                "atualizado_por": usuario,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível salvar os horários automáticos: {exc}",
        ) from exc

    await set_stock_sync_schedules(horarios)

    try:
        await _edge_admin_write(
            "LOG_ALTERACAO_ADD",
            {
                "registro": {
                    "id": str(uuid.uuid4()),
                    "data_hora": datetime.now(ZoneInfo("America/Recife")).isoformat(),
                    "epoch_ms": int(time.time() * 1000),
                    "usuario": usuario,
                    "nome": str(profile.get("nome") or profile.get("vendedor") or ""),
                    "cargo": str(profile.get("tipo") or ""),
                    "modulo": "INDUSTRIAS",
                    "acao": "MAPA_ESTOQUE_HORARIOS_ATUALIZADOS",
                    "entidade": "MAPA_ESTOQUE",
                    "identificador": SCHEDULE_CONFIG_KEY,
                    "detalhes": json.dumps(
                        {"horarios": horarios, "timezone": "America/Recife"},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "origem": BUILD,
                }
            },
        )
    except Exception:
        pass

    return {
        "sucesso": True,
        "horarios": horarios,
        **stock_sync_public_status(),
        "mensagem": "Horários automáticos do mapa atualizados.",
    }
