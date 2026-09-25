"""Live monthly commercial source, isolated from legacy financial calculations."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

from .cache_reads import CacheReadError, cache_get
from .industries_stock_sync import _service_account_info
from .monthly_source_normalization import candidate_from_sheets, normalized

CHANNELS = ("dadosVendedores", "dadosTelevendas")
SYNC_LOCK = asyncio.Lock()


class CommercialSyncError(RuntimeError):
    pass


def current_source(snapshot):
    active = [x for x in snapshot.get("competencias", [])
              if isinstance(x, dict) and str(x.get("status", "")).upper() == "ATUAL"]
    if len(active) != 1 or active[0].get("fechada") is True or active[0].get("congelada") is True:
        raise CommercialSyncError("Competencia atual unica e aberta nao confirmada.")
    comp = str(active[0].get("competencia") or "")
    url = urlparse(str(active[0].get("linkDrive") or ""))
    match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]{15,120})/?.*", url.path)
    if not re.fullmatch(r"(0[1-9]|1[0-2])/20\d{2}", comp) or url.scheme != "https" or url.hostname != "docs.google.com" or not match:
        raise CommercialSyncError("Fonte Google da competencia invalida.")
    return comp, match.group(1)


def _credentials():
    info = None
    raw = os.getenv("DISMEPE_MONTHLY_GOOGLE_READER_B64", "").strip()
    if raw:
        try:
            info = json.loads(base64.b64decode(raw, validate=True).decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise CommercialSyncError("Credencial Google mensal invalida.") from exc
    else:
        info = _service_account_info()
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise CommercialSyncError("Conta de servico Google nao configurada no Render original.")
    expected = os.getenv("DISMEPE_MONTHLY_GOOGLE_READER_EMAIL", "").strip().lower()
    if expected and str(info.get("client_email") or "").strip().lower() != expected:
        raise CommercialSyncError("Identidade da conta de leitura nao confere.")
    return info


def _read_sheets(sheet_id, comp):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    credentials = Credentials.from_service_account_info(
        _credentials(), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    client = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    ranges = ["'CAMPANHA VEND'!A1:AZ6000", "'CAMPANHAS TLVS'!A1:AZ6000"]
    data = client.spreadsheets().values().batchGet(
        spreadsheetId=sheet_id, ranges=ranges, valueRenderOption="UNFORMATTED_VALUE",
    ).execute(num_retries=2)
    matrices = data.get("valueRanges") or []
    if len(matrices) != 2 or any(not isinstance(x.get("values"), list) for x in matrices):
        raise CommercialSyncError("Abas comerciais nao encontradas ou vazias.")
    candidate = candidate_from_sheets(matrices[0]["values"], matrices[1]["values"], comp)
    # No financial cell from the source is trusted in the commercial-only transport.
    for key in CHANNELS:
        if not candidate[key] or len(candidate[key]) >= 6000:
            raise CommercialSyncError("Linhas comerciais incompletas.")
        for row in candidate[key]:
            row.pop("Premiação", None)
            for field, value in list(row.items()):
                if isinstance(value, Decimal):
                    row[field] = float(value)
    return candidate


def commercial_identity(row, channel, comp):
    """Identidade de negócio estável mesmo após inserir ou ordenar linhas."""
    if str(row.get("__COMPETENCIA") or row.get("competencia") or "") != comp:
        raise CommercialSyncError("Competencia comercial divergente.")
    employee = normalized(" ".join(str(row.get("__COLABORADOR") or "").split()))
    lab = normalized(" ".join(str(row.get("__LAB") or "").split()))
    focus_code = normalized(row.get("__CODIGO_FOCO") or "")
    if not employee or not lab:
        raise CommercialSyncError("Registro comercial sem colaborador ou laboratorio.")
    return comp, channel, employee, lab, focus_code


def commercial_identity_map(rows, channel, comp):
    result = {}
    for row in rows:
        identity = commercial_identity(row, channel, comp)
        if identity in result:
            raise CommercialSyncError(
                "Registros comerciais duplicados para o mesmo colaborador, "
                "laboratorio e produto foco. Revise a planilha antes de publicar."
            )
        result[identity] = row
    return result


def _commercial_signature(rows, channel, comp):
    mapped = commercial_identity_map(rows, channel, comp)
    return sorted(
        (identity, row.get("__OBJETIVO"), row.get("__VENDA"),
         row.get("__TEM_FOCO"), row.get("__CODIGO_FOCO"))
        for identity, row in mapped.items()
    )


def _current_rows(snapshot, key, comp):
    values = snapshot.get(key)
    if not isinstance(values, list):
        raise CommercialSyncError("Base SQL mensal incompleta.")
    return [r for r in values if isinstance(r, dict)
            and str(r.get("__COMPETENCIA") or r.get("competencia") or "") == comp]


async def sync_commercial(*, settings, profile, persist):
    """Separate SQL module: never writes MENSAL, history, awards or financial rules."""
    async with SYNC_LOCK:
        original, baseline = await cache_get(modulo="MENSAL", settings=settings)
        comp, sheet_id = current_source(original)
        configured = os.getenv("DISMEPE_MONTHLY_CURRENT_SHEET_ID", "").strip()
        if configured and configured != sheet_id:
            raise CommercialSyncError("ID da planilha difere da competencia atual.")
        candidate = await asyncio.to_thread(_read_sheets, sheet_id, comp)
        for key in CHANNELS:
            old_rows = _current_rows(original, key, comp)
            if not old_rows:
                raise CommercialSyncError("Base SQL sem registros comerciais da competencia.")
            # Nunca comparar __linha: inserir um produto foco desloca linhas
            # validas. Identidades de negocio repetidas seguem bloqueadas.
            commercial_identity_map(old_rows, key, comp)
            commercial_identity_map(candidate[key], key, comp)
        # A read after Sheets prevents publishing over a new legacy calculation.
        confirmed, confirmed_row = await cache_get(modulo="MENSAL", settings=settings)
        initial_time = str(baseline.get("atualizado_em") or "")
        if str(confirmed_row.get("atualizado_em") or "") != initial_time:
            raise CommercialSyncError("Base mensal mudou durante a leitura; tente novamente.")
        differences = any(
            _commercial_signature(candidate[key], key, comp)
            != _commercial_signature(_current_rows(confirmed, key, comp), key, comp)
            for key in CHANNELS
        )
        previous_commercial = None
        try:
            previous_commercial, _ = await cache_get(modulo="MENSAL_COMERCIAL", settings=settings)
        except CacheReadError:
            pass  # A primeira publicação não tem módulo independente ainda.
        if (not differences or (
                isinstance(previous_commercial, dict)
                and previous_commercial.get("competencia") == comp
                and previous_commercial.get("sheetId") == sheet_id
                and previous_commercial.get("baseAtualizadoEm") == initial_time
                and all(_commercial_signature(previous_commercial.get(key, []), key, comp)
                        == _commercial_signature(candidate[key], key, comp) for key in CHANNELS))):
            return {"sucesso": True, "resultado": "SEM_ALTERACAO", "competencia": comp,
                    "vendedores": len(candidate["dadosVendedores"]), "televendas": len(candidate["dadosTelevendas"]),
                    "atualizadoEm": initial_time, "financeiro": "LEGADO_PRESERVADO"}
        payload = {"competencia": comp, "sheetId": sheet_id, "baseAtualizadoEm": initial_time,
                   "fonteLidaEm": datetime.now(timezone.utc).isoformat(),
                   "temDivergenciaComercial": differences,
                   "dadosVendedores": candidate["dadosVendedores"],
                   "dadosTelevendas": candidate["dadosTelevendas"]}
        display, iso = await persist(modulo="MENSAL_COMERCIAL", payload=payload, profile=profile,
                                     version="MENSAL_COMERCIAL_SQL_V1")
        return {"sucesso": True, "resultado": "COMERCIAL_SQL_PUBLICADO", "competencia": comp,
                "vendedores": len(candidate["dadosVendedores"]), "televendas": len(candidate["dadosTelevendas"]),
                "atualizadoEm": iso, "financeiro": "LEGADO_PRESERVADO"}
