"""Resumo de positivacoes exclusivo do laboratorio Globo no portal Industrias.

Somente dados agregados de GLOBO_CLIENTES e metas de METRICA_GLOBO;
nenhuma linha de cliente nem dados de outros laboratorios sao devolvidos.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import FileResponse

from .config import get_settings
from .industries_stock_sync import _service_account_info

router = APIRouter()
settings = get_settings()
_JS_FILE = Path(__file__).resolve().parents[1] / "frontend" / "globo-positivacoes-industrias.js"
_SOURCE_FILE_ID = "1P2NgRBt9e3MnMQD1K-O42Pv8tN6wPkpK2GcL9FFpNsM"
_TTL_SECONDS = 180
_CACHE: tuple[float, dict[str, list[list[Any]]]] | None = None
_LOCK = asyncio.Lock()


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.upper().split())


def _read_globo_sheets() -> dict[str, list[list[Any]]]:
    """Uma leitura das duas abas; conta de servico ja configurada no Render."""
    info = _service_account_info()
    if not info:
        raise RuntimeError("Conta de servico Google indisponivel")
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_info(info, scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ])
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    spreadsheet_id = os.getenv("DISMEPE_GLOBO_SHEET_ID", _SOURCE_FILE_ID).strip() or _SOURCE_FILE_ID
    result = sheets.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id,
        ranges=["'GLOBO_CLIENTES'!A1:F5000", "'METRICA_GLOBO'!A1:D500"],
        valueRenderOption="FORMATTED_VALUE",
    ).execute(num_retries=2)
    ranges = result.get("valueRanges") or []
    if len(ranges) != 2:
        raise ValueError("Abas Globo indisponiveis")
    clients = ranges[0].get("values") or []
    metrics = ranges[1].get("values") or []
    if not clients or [_norm(x) for x in clients[0][:6]] != [
        "VENDEDOR", "COD. CLIENTE", "CLIENTE", "PEDIDOS POR", "POSITIVACAO", "DATA",
    ]:
        raise ValueError("Cabecalho GLOBO_CLIENTES inesperado")
    if not metrics or [_norm(x) for x in metrics[0][:3]] != [
        "VENDEDOR_TELEVENDAS", "TIPO", "META_CLIENTES",
    ]:
        raise ValueError("Cabecalho METRICA_GLOBO inesperado")
    return {"clientes": clients, "metas": metrics}


async def _source() -> dict[str, list[list[Any]]]:
    global _CACHE
    now = time.monotonic()
    if _CACHE and now - _CACHE[0] < _TTL_SECONDS:
        return _CACHE[1]
    async with _LOCK:
        now = time.monotonic()
        if _CACHE and now - _CACHE[0] < _TTL_SECONDS:
            return _CACHE[1]
        try:
            data = await asyncio.wait_for(asyncio.to_thread(_read_globo_sheets), timeout=25.0)
        except Exception as exc:
            # Nenhum token, ID de cliente ou detalhe da fonte externa na resposta.
            raise HTTPException(
                503, "A base de positivacoes Globo nao pode ser lida. Confira o acesso da conta de servico a planilha BASES DISMEPE ONE.",
            ) from exc
        _CACHE = (time.monotonic(), data)
        return data


def _parse_month(value: str) -> str:
    if not re.fullmatch(r"(?:0[1-9]|1[0-2])/20\d{2}", value):
        raise HTTPException(400, "Competencia invalida.")
    return value


def _aggregate(source: dict[str, list[list[Any]]], competence: str) -> dict[str, Any]:
    groups: dict[str, dict[str, dict[str, Any]]] = {"VENDEDORES": {}, "TELEVENDAS": {}}
    for row in source["metas"][1:]:
        if len(row) < 3:
            continue
        name = " ".join(str(row[0] or "").split())[:160]
        kind = _norm(row[1])
        if not name or kind not in groups:
            continue
        raw_goal = str(row[2] or "").strip()
        try:
            goal = int(raw_goal) if re.fullmatch(r"\d+", raw_goal) else None
        except ValueError:
            goal = None
        groups[kind][_norm(name)] = {"profissional": name, "meta": goal, "codigos": set()}

    entries_in_month = 0
    latest: datetime | None = None
    for row in source["clientes"][1:]:
        if len(row) < 6:
            continue
        name = " ".join(str(row[0] or "").split())[:160]
        code = str(row[1] or "").strip()
        origin = _norm(row[3])
        positive = str(row[4] or "").strip() in {"1", "1.0"}
        try:
            date = datetime.strptime(str(row[5] or "").strip(), "%d/%m/%Y")
        except (ValueError, TypeError):
            continue
        if not name or not re.fullmatch(r"\d{1,12}", code) or not positive or date.strftime("%m/%Y") != competence:
            continue
        kind = "TELEVENDAS" if origin == "TELEVENDAS" else "VENDEDORES" if origin in {"ELETRONICO", "VENDEDOR", "VENDEDORES"} else None
        if kind is None:
            continue
        entries_in_month += 1
        latest = max(latest, date) if latest else date
        key = _norm(name)
        record = groups[kind].setdefault(key, {"profissional": name, "meta": None, "codigos": set()})
        record["codigos"].add(code)

    if not entries_in_month:
        return {"sucesso": True, "laboratorio": "GLOBO", "competencia": competence,
                "disponivel": False, "vendedores": [], "televendas": [], "ultimaVenda": None}

    def clean(kind: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in groups[kind].values():
            quantity = len(row["codigos"])
            goal = row["meta"]
            out.append({"profissional": row["profissional"], "positivados": quantity, "meta": goal,
                        "atingimento": round(100 * quantity / goal, 2) if goal and goal > 0 else None})
        return sorted(out, key=lambda row: _norm(row["profissional"]))

    return {"sucesso": True, "laboratorio": "GLOBO", "competencia": competence,
            "disponivel": True, "vendedores": clean("VENDEDORES"),
            "televendas": clean("TELEVENDAS"), "ultimaVenda": latest.strftime("%d/%m/%Y") if latest else None}


@router.get("/industrias/globo-positivacoes.js", include_in_schema=False)
async def globo_positivacoes_script():
    return FileResponse(_JS_FILE, media_type="application/javascript",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@router.get("/industrias/globo-positivacoes")
async def globo_positivacoes(
    competencia: str = Query(..., min_length=7, max_length=7),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    # Revalidar em cada requisicao; a selecao visual nunca autoriza o acesso.
    from . import industries
    profile = await industries._industry_profile(session, require_password_changed=True)
    lab = industries._choose_lab(profile, "GLOBO")
    if industries._lab_key(lab) != "GLOBO":
        raise HTTPException(403, "Laboratorio nao autorizado.")
    month = _parse_month(competencia)
    return _aggregate(await _source(), month)
