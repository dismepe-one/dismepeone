"""Positivação Geral DISMEPE ONE — módulo isolado, acesso administrativo.

A carteira é extraída do PDF Átrio; a positivação vem de uma planilha Google
com abas vendedores, televendas, diretoria e sup. Todos os indicadores usam
exatamente o mesmo mapa consolidado de códigos de clientes únicos.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import io
import hashlib
import json
import os
import re
import time
import unicodedata
import zlib
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jwt
from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .cache_reads import CacheReadError, cache_get
from .config import get_settings
from .industries_sales_sync import _read_sheet
from .industries_stock_sync import _build_drive_service
from .security import decode_session_token

router = APIRouter()
settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "positivacao-geral.html"
TZ = ZoneInfo("America/Recife")
FOLDER_ID = "1wNDrA3Ssio3Dinp8WmQcBDiVHmxtLIQi"
PDF_NAME = "Comparativo Venda_Cliente por Vendedor.pdf"
SHEET_NAME = "Positivacoes"
MODULE = "POSITIVACAO_GERAL_V1"
CONFIG_MODULE = "POSITIVACAO_META_V1"
_BUILD = "POS-GERAL-DEV2"
_TTL = 180.0
_LOCK: asyncio.Lock | None = None
_CACHE: dict[str, Any] | None = None
_CACHE_AT = 0.0
_META_CACHE: int | None = None

# A liberação operacional dependerá de uma alteração explícita posterior.
# Não basta uma permissão no JWT para acessar este módulo em desenvolvimento.
ONLY_ADMIN_DURING_DEVELOPMENT = True


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip())
    raw = "".join(x for x in raw if not unicodedata.combining(x))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", raw.upper())).strip()


def _code(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return str(int(float(text)))
    return ""


def _signed_admin(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(401, "Sessão ausente.")
    try:
        profile = decode_session_token(
            session, secret=settings.jwt_secret, issuer=settings.jwt_issuer
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sessão inválida.") from exc
    if _norm(profile.get("tipo")) not in {"ADMIN", "ADMINISTRADOR"}:
        raise HTTPException(403, "Positivação Geral em desenvolvimento: acesso exclusivo do administrador.")
    return profile


def _safe_json_response(data: dict[str, Any]) -> Response:
    return Response(
        content=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={"Cache-Control": "no-store, private", "X-DISMEPE-Module": _BUILD},
    )


async def _edge(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    async with httpx.AsyncClient(timeout=httpx.Timeout(50.0)) as client:
        response = await client.post(
            url, json={"acao": action, **payload},
            headers={
                "apikey": settings.supabase_publishable_key,
                "x-dismepe-token": settings.edge_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("A base de usuários não retornou JSON válido.") from exc
    if not isinstance(data, dict) or not response.is_success:
        message = data.get("erro") or data.get("error") if isinstance(data, dict) else ""
        raise RuntimeError(str(message or "Falha no serviço de dados."))
    if data.get("sucesso") is not True and data.get("success") is not True and data.get("ok") is not True:
        raise RuntimeError(str(data.get("erro") or data.get("error") or "A operação não foi confirmada pelo serviço de dados."))
    return data


async def _registered_users() -> tuple[dict[str, str], dict[str, str]]:
    result = await _edge("USUARIOS_LIST", {})
    vendedores: dict[str, str] = {}
    televendas: dict[str, str] = {}
    for item in result.get("usuarios") or []:
        if not isinstance(item, dict):
            continue
        if item.get("ativo") is False or _norm(item.get("status")) in {"INATIVO", "EXCLUIDO"}:
            continue
        role = _norm(item.get("tipo"))
        target = vendedores if role == "VENDEDOR" else televendas if role == "TELEVENDAS" else None
        if target is None:
            continue
        display = str(item.get("nome") or item.get("vendedor") or item.get("usuario") or "").strip()
        if not display:
            continue
        for key in ("nome", "vendedor", "usuario"):
            value = _norm(item.get(key))
            if value:
                target.setdefault(value, display)
    return vendedores, televendas


def _drive_file_list(service: Any, folder: str) -> list[dict[str, Any]]:
    # A conta de serviço reutiliza as credenciais já configuradas no Render.
    escaped = folder.replace("'", "\\'")
    token = None
    files: list[dict[str, Any]] = []
    while True:
        result = service.files().list(
            q=f"'{escaped}' in parents and trashed = false",
            fields="nextPageToken,files(id,name,mimeType,modifiedTime,size)",
            orderBy="modifiedTime desc", pageSize=100, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute(num_retries=3)
        files.extend(result.get("files") or [])
        token = result.get("nextPageToken")
        if not token:
            return files


# IDs de recuperação dos dois arquivos fornecidos pela gestão. A busca por
# nome na pasta continua prioritária para detectar substituições futuras.
_INITIAL_PDF_ID = "1LawsN3vXbRLtzXslPyHnQUvh9PtP6sCT"
_INITIAL_SHEET_ID = "1X2VODNXP-Y1a8HzuaEf7wjIzMZCynYNTSEqjs5svU5Y"
_SHEET_MIME = {
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _probe_drive_sources(service: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    folder = os.getenv("DISMEPE_POSITIVACAO_FOLDER_ID", FOLDER_ID).strip() or FOLDER_ID
    pdfname, sheetname = _norm(PDF_NAME), _norm(SHEET_NAME)
    details: dict[str, Any] = {"buscaPasta": "OK", "pdf": "NÃO LOCALIZADO", "planilha": "NÃO LOCALIZADA"}
    try:
        items = _drive_file_list(service, folder)
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        details["buscaPasta"] = f"HTTP {status}" if status in (401, 403, 404, 429) else "INDISPONÍVEL"
        items = []

    pdf = next((x for x in items if _norm(x.get("name")) == pdfname
                and x.get("mimeType") == "application/pdf"), None)
    sheet = next((x for x in items if _norm(x.get("name")) in {sheetname, sheetname + " XLSX"}
                  and x.get("mimeType") in _SHEET_MIME), None)
    if pdf: details["pdf"] = "PASTA"
    if sheet: details["planilha"] = "PASTA"

    # Pastas acessíveis por link podem não ser enumeráveis pela API de uma
    # conta de serviço. Nesse caso, tente o acesso direto aos arquivos já
    # fornecidos pela gestão; confirme tipo, nome e pasta antes de usar.
    for kind, fallback_id, expected_names, allowed_mimes in (
        ("pdf", os.getenv("DISMEPE_POSITIVACAO_PDF_ID", _INITIAL_PDF_ID).strip(),
         {pdfname}, {"application/pdf"}),
        ("planilha", os.getenv("DISMEPE_POSITIVACAO_SHEET_ID", _INITIAL_SHEET_ID).strip(),
         {sheetname, sheetname + " XLSX"}, _SHEET_MIME),
    ):
        if (kind == "pdf" and pdf) or (kind == "planilha" and sheet) or not fallback_id:
            continue
        try:
            item = service.files().get(
                fileId=fallback_id, fields="id,name,mimeType,modifiedTime,size,parents",
                supportsAllDrives=True,
            ).execute(num_retries=3)
            if (_norm(item.get("name")) not in expected_names
                    or item.get("mimeType") not in allowed_mimes
                    or (item.get("parents") and folder not in item["parents"])):
                details[kind] = "ARQUIVO DE REFERÊNCIA INCOMPATÍVEL"
                continue
            if kind == "pdf": pdf = item
            else: sheet = item
            details[kind] = "ARQUIVO DIRETO"
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            details[kind] = (f"HTTP {status}" if status in (401, 403, 404, 429)
                             else "ACESSO DIRETO INDISPONÍVEL")
    return pdf, sheet, details


def _drive_sources(service: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    pdf, sheet, check = _probe_drive_sources(service)
    if not pdf or not sheet:
        missing = ", ".join(x for x, present in (("PDF da carteira", pdf),
                                                  ("planilha Positivacoes", sheet)) if not present)
        raise RuntimeError(
            f"Fonte indisponível: {missing}. Confira o compartilhamento da pasta e "
            "dos arquivos com a conta de serviço do Render. "
            f"Busca na pasta: {check['buscaPasta']}; PDF: {check['pdf']}; planilha: {check['planilha']}."
        )
    return pdf, sheet


def _drive_bytes(service: Any, item: dict[str, Any]) -> bytes:
    fileid = item["id"]
    if item["mimeType"] == "application/vnd.google-apps.spreadsheet":
        request = service.files().export_media(
            fileId=fileid,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        request = service.files().get_media(fileId=fileid, supportsAllDrives=True)
    from googleapiclient.http import MediaIoBaseDownload
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request, chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=3)
        if output.tell() > 18 * 1024 * 1024:
            raise RuntimeError("Arquivo acima do limite de segurança (18 MB).")
    return output.getvalue()


_UF = r"(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)"
_AMOUNT = r"-?[\d.]+,\d{2}"
# Os valores monetários são delimitadores estáveis mesmo com nomes contendo espaços.
_ROW_SUFFIX = re.compile(rf"\s+(?P<uf>{_UF})\s+({_AMOUNT}\s+){{4}}{_AMOUNT}\b", re.I)
_ROW_BEGIN = re.compile(r"^\s*(\d{1,9})\s+(.+)$")
_HEADER = re.compile(r"Vendedor:\s*(\d+)\s*/\s*([^\r\n]+)", re.I)


def _split_customer_owner(prefix: str, owner_id: str, tel_names: dict[str, str]) -> tuple[str, str, bool]:
    # A coluna VND é numérica: localizar a ocorrência mais à direita cuja cauda
    # contenha Cidade UF. Nomes comerciais com o mesmo número não substituem VND.
    parts = list(re.finditer(rf"(?<!\S){re.escape(owner_id)}(?!\S)", prefix))
    if not parts:
        return "", "", False
    before = prefix[:parts[-1].start()].strip()
    if not before:
        return "", "", False
    before = re.sub(r"\s*-{5,}\s*$", "", before).strip()
    layout_columns = [part.strip() for part in re.split(r"\s{2,}", before) if part.strip()]
    if len(layout_columns) == 2 and layout_columns[-1] != before:
        candidate = layout_columns[0]
        column_tv = layout_columns[-1]
        if candidate and candidate != column_tv:
            return candidate, tel_names.get(_norm(column_tv), ""), True
    for normalized, display in sorted(tel_names.items(), key=lambda x: len(x[0]), reverse=True):
        # Mantém os limites de palavra para que JOSE não case com JOSEANE.
        if _norm(before).endswith(" " + normalized):
            tokens = re.split(r"\s+", before)
            display_tokens = re.split(r"\s+", display)
            if len(tokens) > len(display_tokens):
                name = " ".join(tokens[:-len(display_tokens)]).strip()
                if name:
                    return name, display, True
    # Se não houver correspondência na base de usuários, o nome do cliente não
    # deve ser dividido por heurísticas frágeis; conserva-se a razão inteira.
    return before, "", True


def _parse_pdf(raw: bytes, tel_names: dict[str, str]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    clients: dict[str, dict[str, Any]] = {}
    stats = Counter()
    seller_id, seller_name = "", ""
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or page.extract_text() or ""
        for line in text.splitlines():
            header = _HEADER.search(line)
            if header:
                seller_id, seller_name = header.group(1), header.group(2).strip()
                continue
            begin = _ROW_BEGIN.match(line)
            if not begin or not seller_id:
                continue
            match = _ROW_SUFFIX.search(begin.group(2))
            if not match:
                continue
            code = _code(begin.group(1))
            if not code:
                continue
            stats["linhasLidas"] += 1
            before = begin.group(2)[:match.start()].strip()
            name, tel_name, valid = _split_customer_owner(before, seller_id, tel_names)
            if not valid or not name:
                stats["linhasInvalidas"] += 1
                continue
            tail = begin.group(2)[match.end():]
            blocked = bool(re.search(r"(?i)^\s*Bloq(?:\b|(?=\d))", tail))
            old = clients.get(code)
            if not old:
                old = {"codigo": code, "cliente": name, "bloqueado": blocked,
                       "vendedoresPdf": [], "televendasPdf": [], "vinculos": []}
                clients[code] = old
            else:
                # Divergência entre linhas repetidas: nunca liberar cliente
                # caso exista uma ocorrência marcada como bloqueada.
                old["bloqueado"] = old["bloqueado"] or blocked
            if seller_name not in old["vendedoresPdf"]:
                old["vendedoresPdf"].append(seller_name)
            if tel_name and tel_name not in old["televendasPdf"]:
                old["televendasPdf"].append(tel_name)
            if not any(v["codigoVendedor"] == seller_id for v in old["vinculos"]):
                old["vinculos"].append({"codigoVendedor": seller_id,
                                        "vendedorPdf": seller_name,
                                        "televendasCad": tel_name})
    stats["paginas"] = len(reader.pages)
    stats["clientesUnicos"] = len(clients)
    stats["vinculosMultiples"] = sum(len(row["vinculos"]) > 1 for row in clients.values())
    minimum = max(100, len(reader.pages) * 20)
    if len(clients) < minimum or stats["linhasLidas"] < minimum:
        raise RuntimeError("O PDF não apresentou uma carteira válida; a última base válida será preservada.")
    return clients, dict(stats)


def _parse_sales(raw: bytes) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    sales: dict[str, dict[str, Any]] = {}
    info: dict[str, Any] = {}
    tabs = {"vendedores": "Vendedor", "televendas": "Televendas", "diretoria e sup": "Diretoria/Supervisão"}
    required = ["VENDEDOR", "CLIENTE", "COD CLIENTE", "POSITIVACAO", "CNPJ", "PEDIDOS POR"]
    for tab, origin in tabs.items():
        rows = _read_sheet(raw, tab)
        if not rows:
            raise RuntimeError(f"A aba {tab} está vazia ou indisponível.")
        header = [_norm(x) for x in rows[0][:6]]
        if header != required and not (len(header) >= 6 and header[2] in {"COD CLIENTE", "CODIGO CLIENTE"} and header[3] == "POSITIVACAO"):
            raise RuntimeError(f"Cabeçalhos inesperados na aba {tab}; importação cancelada.")
        total = 0
        for values in rows[1:]:
            if len(values) < 4 or str(values[3] or "").strip() not in {"1", "1.0"}:
                continue
            code = _code(values[2])
            if not code:
                continue
            total += 1
            row = sales.setdefault(code, {"codigo": code, "origens": [], "nomesComerciais": [], "cnpj": "", "cliente": ""})
            # A aba de diretoria tem prioridade sobre o texto 'Pedidos Por':
            # impede publicar inadvertidamente essas linhas como Vendedor.
            order_origin = _norm(values[5] if len(values) > 5 else "")
            normalized_origin = ("Diretoria/Supervisão" if tab == "diretoria e sup"
                                 else "Televendas" if tab == "televendas" or "TELEVENDAS" in order_origin
                                 else "Vendedor")
            if normalized_origin not in row["origens"]:
                row["origens"].append(normalized_origin)
            actor = str(values[0] or "").strip()
            if actor and actor not in row["nomesComerciais"]:
                row["nomesComerciais"].append(actor)
            document = re.sub(r"\D", "", str(values[4] if len(values) > 4 else ""))
            if 12 <= len(document) <= 14:
                document = document.zfill(14)
            row["cnpj"] = row["cnpj"] or document
            row["cliente"] = row["cliente"] or str(values[1] or "").strip()
        info[tab] = {"linhasPositivadas": total}
    if not sales:
        raise RuntimeError("Planilha sem clientes positivados; atualização recusada por segurança.")
    info["clientesUnicos"] = len(sales)
    return sales, info


def _consolidate(clients: dict[str, dict[str, Any]], sales: dict[str, dict[str, Any]],
                 sellers: dict[str, str], televendas: dict[str, str], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    old = {x["codigo"]: x for x in (previous or {}).get("clientes", []) if isinstance(x, dict) and x.get("codigo")}
    output: list[dict[str, Any]] = []
    by_sector: dict[str, dict[str, Any]] = {}
    changes = Counter()
    matched_codes: set[str] = set()
    for code, original in clients.items():
        entry = sales.get(code)
        if entry:
            matched_codes.add(code)
        actors = []
        teleactors = []
        for owner in original["vendedoresPdf"]:
            display = sellers.get(_norm(owner))
            if display and display not in actors:
                actors.append(display)
        for tv in original["televendasPdf"]:
            display = televendas.get(_norm(tv))
            if display and display not in teleactors:
                teleactors.append(display)
        blocked = bool(original["bloqueado"])
        if code not in old and previous:
            changes["novos"] += 1
        elif code in old:
            if not bool(old[code].get("bloqueado")) and blocked:
                changes["bloqueadosNovos"] += 1
            if bool(old[code].get("bloqueado")) and not blocked:
                changes["reativados"] += 1
        origins = list(entry["origens"]) if entry else []
        status = "Positivado" if origins else "Não positivado"
        row = {
            "codigo": code, "cliente": original["cliente"], "cnpj": (entry or {}).get("cnpj", ""),
            "vendedores": actors, "televendas": teleactors,
            "setores": actors, "bloqueado": blocked, "origens": origins,
            "status": status, "carteiraCompartilhada": len(original["vinculos"]) > 1,
        }
        output.append(row)
        for setor in actors:
            if setor not in by_sector:
                by_sector[setor] = {"setor": setor, "total": 0, "positivados": 0, "naoPositivados": 0,
                                   "bloqueados": 0, "clientesCompartilhados": 0}
            s = by_sector[setor]
            s["total"] += 1
            s["positivados"] += bool(origins)
            s["naoPositivados"] += not origins
            s["bloqueados"] += blocked
            s["clientesCompartilhados"] += row["carteiraCompartilhada"]
    if previous:
        changes["removidos"] = len(set(old) - set(clients))
    output.sort(key=lambda x: (x["status"] == "Positivado", x["cliente"], int(x["codigo"])))
    total = len(output)
    pos = sum(x["status"] == "Positivado" for x in output)
    blocked_total = sum(x["bloqueado"] for x in output)
    sectors = sorted(by_sector.values(), key=lambda x: x["setor"])
    for sector in sectors:
        sector["percentual"] = round(100 * sector["positivados"] / sector["total"], 2) if sector["total"] else 0
    origins = {"Vendedor": 0, "Televendas": 0, "Diretoria/Supervisão": 0, "Vendedor + Televendas": 0}
    for row in output:
        o = set(row["origens"])
        if "Vendedor" in o:
            origins["Vendedor"] += 1
        if "Televendas" in o:
            origins["Televendas"] += 1
        if "Diretoria/Supervisão" in o:
            origins["Diretoria/Supervisão"] += 1
        if {"Vendedor", "Televendas"}.issubset(o):
            origins["Vendedor + Televendas"] += 1
    return {
        "schema": MODULE, "competencia": datetime.now(TZ).strftime("%m/%Y"),
        "clientes": output, "setores": sectors, "origens": origins,
        "indicadores": {"carteira": total, "positivados": pos, "naoPositivados": total-pos,
                        "percentual": round(100 * pos / total, 2) if total else 0,
                        "bloqueados": blocked_total, "carteirasHabilitadas": len(sectors),
                        "positivadosForaCarteira": len(set(sales)-matched_codes),
                        "clientesVinculosMultiplos": sum(x["carteiraCompartilhada"] for x in output)},
        "movimentacao": {k: int(changes[k]) for k in ("novos", "removidos", "bloqueadosNovos", "reativados")},
    }


def _compact(data: dict[str, Any]) -> str:
    return base64.b64encode(zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 7)).decode("ascii")


def _uncompact(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("schema") != MODULE or not isinstance(data.get("zip"), str):
        return None
    compressed = base64.b64decode(data["zip"], validate=True)
    if len(compressed) > 12 * 1024 * 1024:
        raise ValueError("Snapshot muito grande.")
    decoder = zlib.decompressobj()
    unpacked = decoder.decompress(compressed, 18*1024*1024+1)
    if len(unpacked) > 18*1024*1024 or decoder.unconsumed_tail:
        raise ValueError("Snapshot descompactado excede o limite de segurança.")
    result = json.loads(unpacked)
    return result if isinstance(result, dict) and result.get("schema") == MODULE else None


async def _read_persisted() -> dict[str, Any] | None:
    try:
        data, _ = await cache_get(modulo=MODULE, settings=settings)
        return _uncompact(data)
    except (CacheReadError, ValueError, KeyError, TypeError, zlib.error):
        return None


async def _persist(data: dict[str, Any], profile: dict[str, Any]) -> None:
    zipdata = _compact(data)
    await _edge("CACHE_SET", {
        "modulo": MODULE, "payload": {"schema": MODULE, "zip": zipdata},
        "atualizado_por": str(profile.get("usuario") or ""),
        "nome": "Positivacao Geral DISMEPE", "tamanho": len(zipdata), "versao": _BUILD,
    })


def _sync_blocking(sellers: dict[str, str], televendas: dict[str, str], previous: dict[str, Any] | None,
                   refresh: bool) -> dict[str, Any]:
    service = _build_drive_service()
    pdf, sheet = _drive_sources(service)
    users_hash = hashlib.sha256(json.dumps({"v":sellers,"t":televendas}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    fingerprint = {"pdfId": pdf["id"], "pdfModified": pdf.get("modifiedTime", ""),
                   "sheetId": sheet["id"], "sheetModified": sheet.get("modifiedTime", ""),
                   "usuariosHash": users_hash}
    modified = datetime.fromisoformat(str(sheet.get("modifiedTime") or "").replace("Z", "+00:00")).astimezone(TZ)
    current = datetime.now(TZ)
    if (modified.year, modified.month) != (current.year, current.month):
        raise RuntimeError("Planilha de positivações ainda não foi atualizada na competência atual.")
    if previous and previous.get("fontes") == fingerprint and not refresh:
        return previous
    # Caso apenas a planilha seja atualizada, a carteira já validada pode ser
    # reaproveitada somente se o snapshot persistido contiver a base original.
    pdf_bytes = _drive_bytes(service, pdf)
    xlsx_bytes = _drive_bytes(service, sheet)
    portfolio, parsing = _parse_pdf(pdf_bytes, televendas)
    sales, parsing_sales = _parse_sales(xlsx_bytes)
    if previous and previous.get("indicadores", {}).get("carteira", 0) > 500:
        previous_count = previous["indicadores"]["carteira"]
        if len(portfolio) < previous_count * 0.6:
            raise RuntimeError("Carteira recebida tem menos de 60% do volume anterior; fotografia preservada para conferência.")
    data = _consolidate(portfolio, sales, sellers, televendas, previous)
    data["fontes"] = fingerprint
    data["leitura"] = {"pdf": parsing, "excel": parsing_sales}
    data["atualizadoEm"] = _now()
    return data


async def _get_data(profile: dict[str, Any], force: bool = False) -> dict[str, Any]:
    global _LOCK, _CACHE, _CACHE_AT
    if _LOCK is None:
        _LOCK = asyncio.Lock()
    if not force and _CACHE and time.monotonic() - _CACHE_AT < _TTL:
        return _CACHE
    async with _LOCK:
        if not force and _CACHE and time.monotonic() - _CACHE_AT < _TTL:
            return _CACHE
        prev = _CACHE or await _read_persisted()
        try:
            sellers, televendas = await _registered_users()
            data = await asyncio.to_thread(_sync_blocking, sellers, televendas, prev, force)
            data = copy.deepcopy(data)
            data["usuariosAtivos"] = {"vendedores": len(set(sellers.values())), "televendas": len(set(televendas.values()))}
            if data.get("fontes") != (prev or {}).get("fontes") or (prev or {}).get("persistencia") == "MEMORIA_APENAS":
                try:
                    await _persist(data, profile)
                    data["persistencia"] = "POSTGRESQL"
                except Exception:
                    # O sistema não deve afirmar que persistiu quando o banco falhou.
                    data["persistencia"] = "MEMORIA_APENAS"
            else:
                data["persistencia"] = "POSTGRESQL_OU_CACHE"
            _CACHE = data
            _CACHE_AT = time.monotonic()
            return data
        except Exception as exc:
            if prev:
                restored = copy.deepcopy(prev)
                restored["alerta"] = "Não foi possível atualizar as fontes. Exibindo a última fotografia válida."
                restored["persistencia"] = "FOTOGRAFIA_ANTERIOR"
                _CACHE = restored
                _CACHE_AT = time.monotonic()
                return restored
            raise HTTPException(503, f"Positivação ainda indisponível: {str(exc)[:180]}") from exc


async def _meta() -> int:
    global _META_CACHE
    # Leitura do PostgreSQL a cada abertura: outra instância do Render pode
    # alterar a meta. O cache local é somente contingência em falha temporária.
    try:
        result, _ = await cache_get(modulo=CONFIG_MODULE, settings=settings)
        _META_CACHE = max(0, int(result.get("meta") or 0))
    except (CacheReadError, ValueError, TypeError):
        if _META_CACHE is None:
            _META_CACHE = 0
    return _META_CACHE


class MetaRequest(BaseModel):
    meta: int = Field(ge=0, le=1000000)


@lru_cache(maxsize=1)
def _native_logo_bytes() -> bytes:
    # A mesma identidade visual da HOME, sem copiar nem modificar o HTML legado.
    portal = (ROOT / "frontend" / "portal-v2-homolog.html").read_text(encoding="utf-8")
    match = re.search(
        r'<header class="card-glass[^>]*>.*?<img\s+src="data:image/png;base64,([^"\s]+)"',
        portal, flags=re.S,
    )
    if not match:
        raise RuntimeError("Logo do cabeçalho do DISMEPE ONE não encontrado.")
    return base64.b64decode(match.group(1), validate=True)


@router.get("/positivacoes/logo.png", include_in_schema=False)
async def positivacao_native_logo(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _signed_admin(session)
    return Response(
        content=_native_logo_bytes(), media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/positivacoes", include_in_schema=False)
async def positivacao_page(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _signed_admin(session)
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store, private"})


def _source_diagnostic_blocking() -> dict[str, Any]:
    # Checa apenas metadados, sem dados pessoais.
    try:
        service = _build_drive_service()
    except Exception:
        return {"status": "CREDENCIAL_DRIVE_INDISPONIVEL", "pdf": False, "planilha": False,
                "orientacao": "A credencial de leitura do Google Drive precisa estar configurada no Render."}
    pdf, planilha, detalhes = _probe_drive_sources(service)
    encontradas = bool(pdf and planilha)
    return {"status": "FONTES_LOCALIZADAS" if encontradas else "FONTES_INDISPONIVEIS",
            "pdf": bool(pdf), "planilha": bool(planilha),
            "buscaPasta": detalhes["buscaPasta"],
            "metodoPdf": detalhes["pdf"], "metodoPlanilha": detalhes["planilha"],
            "orientacao": "Arquivos localizados. Se os indicadores ainda não carregarem, verifique o erro de importação mostrado acima."
            if encontradas else "A leitura precisa de acesso da conta de serviço do Render à pasta e aos dois arquivos. Confira o compartilhamento no Google Drive."}


@router.get("/positivacoes/api/diagnostico", include_in_schema=False)
async def positivacao_diagnostico(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _signed_admin(session)
    result = await asyncio.to_thread(_source_diagnostic_blocking)
    return _safe_json_response(result)


@router.get("/positivacoes/api/painel")
async def positivacao_panel(force: bool = Query(False), session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    profile = _signed_admin(session)
    data = await _get_data(profile, force=force)
    summary = {k: v for k, v in data.items() if k not in {"clientes"}}
    summary["meta"] = await _meta()
    summary["metaAtingimento"] = round(summary["indicadores"]["positivados"] * 100 / summary["meta"], 2) if summary["meta"] else 0
    summary["metaFaltam"] = max(0, summary["meta"] - summary["indicadores"]["positivados"])
    return _safe_json_response(summary)


def _selected(data: dict[str, Any], status: str, setor: str, search: str) -> list[dict[str, Any]]:
    if status not in {"todos", "positivados", "nao-positivados", "bloqueados"}:
        raise HTTPException(400, "Filtro inválido.")
    norm_setor = _norm(setor)
    norm_search = _norm(search)
    result = []
    for c in data["clientes"]:
        if status == "positivados" and c["status"] != "Positivado":
            continue
        if status == "nao-positivados" and c["status"] != "Não positivado":
            continue
        if status == "bloqueados" and not c["bloqueado"]:
            continue
        if norm_setor and all(_norm(x) != norm_setor for x in c["setores"]):
            continue
        if norm_search and norm_search not in _norm(" ".join([c["codigo"], c["cliente"], c["cnpj"]])):
            continue
        result.append(c)
    return result


@router.get("/positivacoes/api/clientes")
async def positivacao_clients(
    status: str = "todos", setor: str = "", busca: str = "", pagina: int = Query(1, ge=1),
    tamanho: int = Query(50, ge=1, le=100),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _signed_admin(session)
    data = await _get_data(profile)
    rows = _selected(data, status, setor, busca)
    start = (pagina-1)*tamanho
    return _safe_json_response({"total": len(rows), "pagina": pagina, "tamanho": tamanho,
                                "clientes": rows[start:start+tamanho], "atualizadoEm": data["atualizadoEm"]})


@router.post("/positivacoes/api/meta")
async def positivacao_meta(body: MetaRequest, session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    global _META_CACHE
    profile = _signed_admin(session)
    serialized = {"meta": body.meta, "alteradoEm": _now()}
    try:
        await _edge("CACHE_SET", {
            "modulo": CONFIG_MODULE, "payload": serialized,
            "atualizado_por": str(profile.get("usuario") or ""),
            "nome": "Meta Positivacao Geral", "versao": _BUILD,
            "tamanho": len(json.dumps(serialized).encode("utf-8")),
        })
    except Exception as exc:
        raise HTTPException(503, "A meta não foi salva no banco de dados.") from exc
    _META_CACHE = body.meta
    return _safe_json_response({"sucesso": True, "meta": body.meta})


def _export_fields(row: dict[str, Any]) -> list[str]:
    return [row["codigo"], row["cnpj"], row["cliente"], ", ".join(row["setores"]) or "Sem vínculo cadastrado",
            ", ".join(row["televendas"]), " + ".join(row["origens"]), row["status"],
            "Sim" if row["bloqueado"] else "Não"]


@router.get("/positivacoes/api/exportar/{kind}")
async def positivacao_export(
    kind: str, status: str = "todos", setor: str = "", busca: str = "",
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _signed_admin(session)
    data = await _get_data(profile)
    rows = _selected(data, status, setor, busca)
    headers = ["Código", "CNPJ", "Cliente", "Carteira", "Televendas Cad.", "Origem", "Status", "Bloqueado"]
    if kind == "excel":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "Positivacao Geral"
        ws.append(headers)
        for row in rows:
            ws.append(_export_fields(row))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="075548")
            cell.font = Font(color="FFFFFF", bold=True)
        for col, width in {"A":12,"B":20,"C":48,"D":43,"E":30,"F":35,"G":20,"H":13}.items():
            ws.column_dimensions[col].width=width
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment=Alignment(vertical="top", wrap_text=True)
        out = io.BytesIO(); wb.save(out)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif kind == "pdf":
        from xml.sax.saxutils import escape
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, LongTable
        out=io.BytesIO()
        doc=SimpleDocTemplate(out, pagesize=landscape(A4), rightMargin=22, leftMargin=22, topMargin=28, bottomMargin=25)
        styles=getSampleStyleSheet()
        styles.add(ParagraphStyle(name="CellTinyPos", parent=styles["Normal"], fontSize=6, leading=8))
        story=[Paragraph("DISMEPE ONE | Positivação Geral", styles["Heading2"]),
               Paragraph(f"Filtro: {escape(status)} | Setor: {escape(setor or 'Todos')} | Registros: {len(rows)} | Fonte: {escape(data.get('atualizadoEm',''))}", styles["Normal"]), Spacer(1,10)]
        table_data=[[Paragraph(escape(h),styles["CellTinyPos"]) for h in headers]]
        for row in rows:
            table_data.append([Paragraph(escape(str(x)), styles["CellTinyPos"]) for x in _export_fields(row)])
        table=LongTable(table_data, colWidths=[44,72,170,123,106,112,74,55], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#075548")),
                                   ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                                   ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#F4F8F6")]),
                                   ("VALIGN",(0,0),(-1,-1),"TOP"),
                                   ("BOTTOMPADDING",(0,0),(-1,-1),5),
                                   ("TOPPADDING",(0,0),(-1,-1),5),
                                   ("LINEBELOW",(0,0),(-1,0),.5,colors.HexColor("#075548"))]))
        story.append(table); doc.build(story)
        media="application/pdf"; ext="pdf"
    else:
        raise HTTPException(404, "Formato de exportação indisponível.")
    filename=f"POSITIVACAO_GERAL_{datetime.now(TZ).strftime('%Y%m%d')}.{ext}"
    return Response(content=out.getvalue(), media_type=media,
                    headers={"Cache-Control":"no-store, private", "Content-Disposition": f'attachment; filename="{filename}"'})
