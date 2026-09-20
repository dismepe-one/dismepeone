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
_BUILD = "POS-GERAL-DEV10-7-SINO-INATIVIDADE"
_TTL = 600.0
_CACHE: dict[str, Any] | None = None
_CACHE_AT = 0.0
_META_CACHE: int | None = None
# Nenhuma leitura de PDF/planilha ocorre na requisicao que abre o painel.
_SYNC_TASK: asyncio.Task | None = None
_SYNC_ERROR = ""
_SYNC_LAST_STARTED = 0.0
_SYNC_LAST_FINISHED = ""
_DB_CHECK_AT = 0.0
_DB_ERROR = ""

# DEV9: somente vendedores e televendas ativos tem visao individual.
# Consolidado e publicacao continuam exclusivos de administradores.
ONLY_ADMIN_DURING_DEVELOPMENT = False
_ROSTER_AT = 0.0
_ROSTER: list[dict[str, Any]] = []
_SQL_RELOAD_TASK: asyncio.Task | None = None
_SYNC_RESULT = ""


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


def _page_profile(session: str | None) -> dict[str, Any]:
    """Apenas valida sessao para entregar HTML/logo sem aguardar consulta ao banco.

    Nenhum dado de carteira e entregue aqui; TODAS as APIs revalidam o cadastro.
    """
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
    if _norm(profile.get("tipo")) not in {"ADMIN", "ADMINISTRADOR", "VENDEDOR", "TELEVENDAS"}:
        raise HTTPException(403, "Perfil sem acesso ao módulo Positivações.")
    return profile


async def _viewer_context(session: str | None) -> dict[str, Any]:
    """Resolve usuario, cargo e carteira no cadastro ATIVO, jamais por filtro da URL."""
    profile = _page_profile(session)
    role = _norm(profile.get("tipo"))
    if role in {"ADMIN", "ADMINISTRADOR"}:
        return {"admin": True, "profile": profile, "setor": "", "pessoa": "", "canal": ""}
    if role not in {"VENDEDOR", "TELEVENDAS"}:
        raise HTTPException(403, "Este perfil não possui carteira individual de Positivações.")
    login = _norm(profile.get("usuario"))
    if not login:
        raise HTTPException(403, "Usuário sem identificação de carteira.")
    global _ROSTER, _ROSTER_AT
    if not _ROSTER or time.monotonic() - _ROSTER_AT >= 30:
        try:
            result = await asyncio.wait_for(_edge("USUARIOS_LIST", {}), timeout=8.0)
            users = result.get("usuarios")
            if not isinstance(users, list):
                raise ValueError("Lista de usuários não disponível.")
            _ROSTER = [u for u in users if isinstance(u, dict)]
            _ROSTER_AT = time.monotonic()
        except Exception as exc:
            # Cadastro inacessivel => negar individual, sem recorrer a claims antigos.
            raise HTTPException(503, "Não foi possível confirmar o cadastro ativo. Tente novamente.") from exc
    matching = [u for u in _ROSTER if _norm(u.get("usuario")) == login]
    if len(matching) != 1:
        raise HTTPException(403, "Carteira individual não encontrada no cadastro atual.")
    user = matching[0]
    if (user.get("ativo") is not True or _norm(user.get("status")) != "ATIVO"
            or _norm(user.get("tipo")) != role):
        raise HTTPException(403, "Carteira indisponível para este usuário.")
    person = str(user.get("nome") or user.get("vendedor") or user.get("usuario") or "").strip()
    if not person:
        raise HTTPException(403, "Usuário sem carteira cadastrada.")
    sector = "TV:" + person if role == "TELEVENDAS" else person
    return {"admin": False, "profile": profile, "setor": sector,
            "pessoa": person, "canal": "Televendas" if role == "TELEVENDAS" else "Vendedor"}


async def _registered_users() -> tuple[dict[str, str], dict[str, str]]:
    result = await _edge("USUARIOS_LIST", {})
    vendedores: dict[str, str] = {}
    televendas: dict[str, str] = {}
    for item in result.get("usuarios") or []:
        if not isinstance(item, dict):
            continue
        if item.get("ativo") is False or item.get("ativo") == 0 or _norm(item.get("ativo")) in {"FALSE", "0", "NAO", "N"} or _norm(item.get("status")) in {"INATIVO", "EXCLUIDO", "DESATIVADO", "BLOQUEADO", "SUSPENSO"}:
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
    # No PDF do Átrio a coluna VND pode estar colada à coluna Televenda:
    # "... CAVALCANTI58 RECIFE". O código VND é o último número ANTES da cidade.
    # Não basta exigir espaços de ambos os lados: isso perde clientes válidos.
    parts = list(re.finditer(rf"(?<!\d){re.escape(owner_id)}(?=\s+[^\d]+$)", prefix))
    if not parts:
        return "", "", False
    before = prefix[:parts[-1].start()].strip()
    if not before:
        return "", "", False
    before = re.sub(r"\s*-{5,}\s*$", "", before).strip()
    # A correspondência por nome completo vem ANTES de dividir por espaços
    # duplos: algumas teclistas possuem espaços duplos no próprio nome.
    for normalized, display in sorted(tel_names.items(), key=lambda x: len(x[0]), reverse=True):
        # Mantém os limites de palavra para que JOSE não case com JOSEANE.
        if _norm(before).endswith(" " + normalized):
            tokens = re.split(r"\s+", before)
            display_tokens = re.split(r"\s+", display)
            if len(tokens) > len(display_tokens):
                name = " ".join(tokens[:-len(display_tokens)]).strip()
                if name:
                    return name, display, True
    layout_columns = [part.strip() for part in re.split(r"\s{2,}", before) if part.strip()]
    if len(layout_columns) == 2:
        candidate, column_tv = layout_columns
        # Nomes que não pertencem a televendas atuais não geram vínculo.
        tv = tel_names.get(_norm(column_tv), "")
        if candidate and tv:
            return candidate, tv, True
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
        # O modo layout de certas versões do pypdf não extrai as colunas
        # do relatório Átrio; o texto padrão preserva suas linhas de clientes.
        text = page.extract_text() or page.extract_text(extraction_mode="layout") or ""
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
            row = sales.setdefault(code, {"codigo": code, "origens": [], "nomesComerciais": [],
                                          "atoresPorOrigem": {}, "cnpj": "", "cliente": ""})
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
            # Diretoria/Supervisão continua no consolidado, nunca como crédito
            # individual de vendedor ou televendas.
            if actor and tab in {"vendedores", "televendas"}:
                by_origin = row["atoresPorOrigem"].setdefault(normalized_origin, [])
                if actor not in by_origin:
                    by_origin.append(actor)
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
    by_televendas: dict[str, dict[str, Any]] = {}
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
        credited = (entry or {}).get("atoresPorOrigem", {})
        credited_sellers = {
            sellers[_norm(name)] for name in credited.get("Vendedor", []) if _norm(name) in sellers
        }
        credited_tele = {
            televendas[_norm(name)] for name in credited.get("Televendas", []) if _norm(name) in televendas
        }
        # Um cliente positivado na empresa não concede crédito individual
        # à carteira de outro profissional, ativo ou inativo.
        seller_positive = sorted(set(actors) & credited_sellers)
        tele_positive = sorted(set(teleactors) & credited_tele)
        status = "Positivado" if origins else "Não positivado"
        row = {
            "codigo": code, "cliente": original["cliente"], "cnpj": (entry or {}).get("cnpj", ""),
            "televendasQuePositivaram": list(dict.fromkeys(credited.get("Televendas", []))),
            "vendedores": actors, "televendas": teleactors,
            "setores": actors, "bloqueado": blocked, "origens": origins,
            "status": status, "carteiraCompartilhada": len(original["vinculos"]) > 1,
            "positivacoesVendedor": seller_positive, "positivacoesTelevendas": tele_positive,
        }
        output.append(row)
        for setor in actors:
            if setor not in by_sector:
                by_sector[setor] = {"setor": setor, "total": 0, "positivados": 0, "naoPositivados": 0,
                                   "bloqueados": 0, "clientesCompartilhados": 0}
            s = by_sector[setor]
            s["total"] += 1
            s["positivados"] += setor in seller_positive
            s["naoPositivados"] += setor not in seller_positive
            s["bloqueados"] += blocked
            s["clientesCompartilhados"] += row["carteiraCompartilhada"]
        for televendedor in teleactors:
            t = by_televendas.setdefault(televendedor, {"televendas": televendedor,
                "total": 0, "positivados": 0, "naoPositivados": 0, "bloqueados": 0})
            t["total"] += 1
            t["positivados"] += televendedor in tele_positive
            t["naoPositivados"] += televendedor not in tele_positive
            t["bloqueados"] += blocked
    if previous:
        changes["removidos"] = len(set(old) - set(clients))
    output.sort(key=lambda x: (x["status"] == "Positivado", x["cliente"], int(x["codigo"])))
    total = len(output)
    pos = sum(x["status"] == "Positivado" for x in output)
    blocked_total = sum(x["bloqueado"] for x in output)
    sectors = sorted(by_sector.values(), key=lambda x: x["setor"])
    for sector in sectors:
        sector["percentual"] = round(100 * sector["positivados"] / sector["total"], 2) if sector["total"] else 0
    tele_sectors = sorted(by_televendas.values(), key=lambda x: x["televendas"])
    for tele_sector in tele_sectors:
        tele_sector["percentual"] = (round(100 * tele_sector["positivados"] / tele_sector["total"], 2)
                                      if tele_sector["total"] else 0)
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
        "clientes": output, "setores": sectors, "carteirasTelevendas": tele_sectors, "origens": origins,
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
                   "usuariosHash": users_hash, "regraCarteiras": "usuarios-ativos-v2"}
    modified = datetime.fromisoformat(str(sheet.get("modifiedTime") or "").replace("Z", "+00:00")).astimezone(TZ)
    current = datetime.now(TZ)
    if (modified.year, modified.month) != (current.year, current.month):
        raise RuntimeError("Planilha de positivações ainda não foi atualizada na competência atual.")
    if previous and previous.get("fontes") == fingerprint:
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


async def _reload_cached_sql() -> None:
    global _CACHE, _CACHE_AT, _DB_ERROR
    try:
        persisted = await asyncio.wait_for(_read_persisted(), timeout=8.0)
        if persisted is not None:
            def timestamp(snapshot: dict[str, Any]) -> float:
                try:
                    value = str(snapshot.get("atualizadoEm") or "").replace("Z", "+00:00")
                    return datetime.fromisoformat(value).timestamp()
                except (ValueError, TypeError):
                    return 0.0
            if _CACHE is None or timestamp(persisted) > timestamp(_CACHE):
                _CACHE = persisted
            _DB_ERROR = ""
    except Exception:
        _DB_ERROR = "Falha temporária ao conferir a fotografia no Supabase."
    finally:
        _CACHE_AT = time.monotonic()


async def _snapshot_fast() -> dict[str, Any] | None:
    """Uma leitura breve do Supabase; nunca importa arquivos durante o GET."""
    global _CACHE, _CACHE_AT, _DB_CHECK_AT, _DB_ERROR
    global _SQL_RELOAD_TASK
    if _CACHE is not None:
        if (time.monotonic() - _CACHE_AT >= 30
                and (_SQL_RELOAD_TASK is None or _SQL_RELOAD_TASK.done())):
            _SQL_RELOAD_TASK = asyncio.create_task(_reload_cached_sql())
        return _CACHE
    # A primeira base pode ainda nao existir: nao consultar PostgreSQL a cada polling.
    if _DB_CHECK_AT and time.monotonic() - _DB_CHECK_AT < 30:
        return None
    _DB_CHECK_AT = time.monotonic()
    try:
        persisted = await asyncio.wait_for(_read_persisted(), timeout=8.0)
        _DB_ERROR = ""
    except (asyncio.TimeoutError, Exception):
        persisted = None
        _DB_ERROR = "A consulta do snapshot no Supabase nao respondeu."
    if persisted is not None:
        _CACHE = persisted
        _CACHE_AT = time.monotonic()
    return _CACHE


def _same_sources(previous: dict[str, Any] | None, pdf: dict[str, Any], sheet: dict[str, Any]) -> bool:
    if not previous or previous.get("competencia") != datetime.now(TZ).strftime("%m/%Y"):
        return False
    old = previous.get("fontes") or {}
    def modified(value: Any) -> str:
        return str(value or "").replace(".000Z", "Z")
    return bool(old.get("pdfModified") and old.get("sheetModified")
                and old.get("pdfId") == pdf.get("id")
                and old.get("sheetId") == sheet.get("id")
                and modified(old.get("pdfModified")) == modified(pdf.get("modifiedTime"))
                and modified(old.get("sheetModified")) == modified(sheet.get("modifiedTime")))


def _sources_changed_blocking(previous: dict[str, Any] | None) -> bool:
    service = _build_drive_service()
    pdf, sheet = _drive_sources(service)
    return not _same_sources(previous, pdf, sheet)


async def _refresh_job(profile: dict[str, Any], force: bool) -> None:
    """Trabalho desacoplado da requisicao HTTP: baixa, consolida e grava uma fotografia validada."""
    global _CACHE, _CACHE_AT, _SYNC_ERROR, _SYNC_LAST_FINISHED, _SYNC_RESULT
    _SYNC_RESULT = "PROCESSANDO"
    previous: dict[str, Any] | None = _CACHE
    try:
        if previous is None:
            previous = await _read_persisted()
        vendedores, televendas = await _registered_users()
        data = await asyncio.to_thread(_sync_blocking, vendedores, televendas, previous, force)
        data = copy.deepcopy(data)
        data["usuariosAtivos"] = {
            "vendedores": len(set(vendedores.values())),
            "televendas": len(set(televendas.values())),
        }
        # Persistir ANTES de publicar a nova fotografia como fonte principal.
        # Um banco indisponivel nao deve fazer o painel afirmar que esta sincronizado.
        if (previous is None or data.get("fontes") != previous.get("fontes")
                or previous.get("persistencia") == "MEMORIA_APENAS"):
            try:
                _SYNC_RESULT = "PUBLICANDO"
                await _persist(data, profile)
                data["persistencia"] = "POSTGRESQL"
            except Exception as exc:
                raise RuntimeError("A nova base foi processada, mas não foi publicada no Supabase; a base anterior foi preservada.") from exc
            _SYNC_RESULT = "PUBLICADA"
        else:
            data["persistencia"] = "POSTGRESQL_OU_CACHE"
            _SYNC_RESULT = "SEM_ALTERACAO"
        _CACHE = data
        _CACHE_AT = time.monotonic()
        _SYNC_ERROR = ""
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Mensagem apenas a administradores, sem exposicao de credenciais nem tracebacks.
        _SYNC_ERROR = str(exc)[:280] or "A importacao nao foi concluida."
        _SYNC_RESULT = "ERRO"
        if previous is not None and _CACHE is None:
            _CACHE = previous
            _CACHE_AT = time.monotonic()
    finally:
        _SYNC_LAST_FINISHED = _now()


def _start_sync(profile: dict[str, Any], *, force: bool = False) -> None:
    """No maximo um trabalho por processo; verificacao automatica espaçada."""
    global _SYNC_TASK, _SYNC_ERROR, _SYNC_LAST_STARTED
    if _SYNC_TASK is not None and not _SYNC_TASK.done():
        return
    if not force and _SYNC_LAST_STARTED and time.monotonic() - _SYNC_LAST_STARTED < _TTL:
        return
    _SYNC_LAST_STARTED = time.monotonic()
    _SYNC_ERROR = ""
    _SYNC_TASK = asyncio.create_task(_refresh_job(profile, force), name="positivacoes-refresh-drive")


def _sync_status() -> dict[str, Any]:
    return {
        "emAndamento": bool(_SYNC_TASK is not None and not _SYNC_TASK.done()),
        "erro": _SYNC_ERROR,
        "ultimaConclusao": _SYNC_LAST_FINISHED,
        "erroConsultaBanco": _DB_ERROR,
        "resultado": _SYNC_RESULT,
    }


async def _get_data(profile: dict[str, Any]) -> dict[str, Any]:
    data = await _snapshot_fast()
    if data is None and _norm(profile.get("tipo")) in {"ADMIN", "ADMINISTRADOR"}:
        _start_sync(profile)
    if data is None:
        raise HTTPException(503, "A fotografia das Positivações ainda não foi publicada no Supabase.")
    return await _inat_enrich(data)

async def _meta() -> int:
    global _META_CACHE, _META_CACHE_AT
    if _META_CACHE is not None and time.monotonic() - _META_CACHE_AT < 600:
        return _META_CACHE
    try:
        result, _ = await cache_get(modulo=CONFIG_MODULE, settings=settings)
        _META_CACHE = max(0, int(result.get("meta") or 0))
        _META_CACHE_AT = time.monotonic()
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
    _page_profile(session)
    return Response(
        content=_native_logo_bytes(), media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/positivacoes", include_in_schema=False)
async def positivacao_page(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _page_profile(session)
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
    context = await _viewer_context(session)
    profile = context["profile"]
    if force and not context["admin"]:
        raise HTTPException(403, "A atualização das bases é exclusiva da administração.")
    data = await _snapshot_fast()
    if context["admin"] and (force or data is None):
        _start_sync(profile, force=force)
    state = _sync_status() if context["admin"] else {"emAndamento": False, "erro": ""}
    if data is None:
        return _safe_json_response({"carregando": state["emAndamento"], "semFotografia": True,
                                    "statusAtualizacao": state, "sucesso": True})
    data = await _inat_enrich(data)
    visible = _visible_data(data, context)
    summary = {k: v for k, v in visible.items() if k not in {"clientes"}}
    try:
        summary["meta"] = await asyncio.wait_for(_meta(), timeout=5.0)
    except Exception:
        summary["meta"] = _META_CACHE or 0
        summary["metaLeituraIndisponivel"] = True
    company = data["indicadores"] if not context["admin"] else summary["indicadores"]
    summary["metaAtingimento"] = round(company["positivados"] * 100 / summary["meta"], 2) if summary["meta"] else 0
    summary["metaFaltam"] = max(0, summary["meta"] - company["positivados"])
    summary["statusAtualizacao"] = state
    return _safe_json_response(summary)


async def _manual_check_and_refresh(profile: dict[str, Any]) -> None:
    """Confere metadados fora da requisição HTTP e só importa se necessário."""
    global _SYNC_ERROR, _SYNC_RESULT, _SYNC_LAST_FINISHED
    try:
        previous = await _snapshot_fast()
        # Uma fotografia apenas em memória ainda precisa ser persistida.
        if previous is not None and previous.get("persistencia") != "MEMORIA_APENAS":
            changed = await asyncio.wait_for(
                asyncio.to_thread(_sources_changed_blocking, previous), timeout=35.0)
            if not changed:
                _SYNC_ERROR = ""
                _SYNC_RESULT = "SEM_ALTERACAO"
                return
        await _refresh_job(profile, True)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Sem confirmação dos metadados, nunca alegar que a base está atualizada.
        _SYNC_ERROR = "Não foi possível conferir as atualizações no Drive. A última base válida foi preservada."
        _SYNC_RESULT = "ERRO"
    finally:
        _SYNC_LAST_FINISHED = _now()


@router.get("/positivacoes/api/atualizacao-status")
async def positivacao_atualizacao_status(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _signed_admin(session)
    return _safe_json_response({"sucesso": True, "statusAtualizacao": _sync_status()})


@router.post("/positivacoes/api/atualizar")
async def positivacao_refresh(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    profile = _signed_admin(session)
    global _SYNC_TASK, _SYNC_ERROR, _SYNC_RESULT, _SYNC_LAST_STARTED
    if _SYNC_TASK is not None and not _SYNC_TASK.done():
        return _safe_json_response({"sucesso": True, "emAndamento": True,
                                    "statusAtualizacao": _sync_status()})
    _SYNC_ERROR = ""
    _SYNC_RESULT = "VERIFICANDO"
    _SYNC_LAST_STARTED = time.monotonic()
    # A resposta ao clique é imediata; o trabalho roda sob a tarefa já
    # utilizada pelo módulo e a UI consulta somente o status leve.
    _SYNC_TASK = asyncio.create_task(
        _manual_check_and_refresh(profile), name="positivacoes-verificar-e-publicar")
    return _safe_json_response({"sucesso": True, "emAndamento": True,
                                "statusAtualizacao": _sync_status()})


def _selected(data: dict[str, Any], status: str, setor: str, search: str,
              nao_bloqueados: bool = False) -> list[dict[str, Any]]:
    if status not in {"todos", "positivados", "nao-positivados", "bloqueados", "inativos"}:
        raise HTTPException(400, "Filtro inválido.")
    is_tv = setor.startswith("TV:")
    person = _norm(setor[3:] if is_tv else setor)
    norm_search = _norm(search)
    result = []
    for c in data["clientes"]:
        if person:
            wallet = c["televendas"] if is_tv else c["setores"]
            if all(_norm(x) != person for x in wallet):
                continue
            # A carteira e positivada pela venda de qualquer canal nesse cliente.
            # O credito individual permanece separado em positivacoesVendedor/
            # positivacoesTelevendas, sem sobrescrever o status global.
        if status == "inativos" and not c.get("inativo"):
            continue
        if status not in {"todos", "inativos"} and c.get("inativo"):
            continue
        if status == "positivados" and c["status"] != "Positivado":
            continue
        if status == "nao-positivados" and c["status"] != "Não positivado":
            continue
        if status == "bloqueados" and not c["bloqueado"]:
            continue
        if nao_bloqueados and c["bloqueado"]:
            continue
        if norm_search and norm_search not in _norm(" ".join([c["codigo"], c["cliente"], c["cnpj"]])):
            continue
        result.append(c)
    return result


def _enforced_sector(sector: str, context: dict[str, Any]) -> str:
    if context["admin"]:
        return sector
    own = context["setor"]
    if sector and sector != own:
        raise HTTPException(403, "Não é permitido consultar outra carteira.")
    return own


def _origins_for_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("Vendedor", "Televendas", "Diretoria/Supervisão", "Vendedor + Televendas")
    result = {key: 0 for key in keys}
    for row in rows:
        if row.get("inativo"):
            continue
        origin = set(row.get("origens") or [])
        for name in keys[:3]:
            if name in origin:
                result[name] += 1
        if "Vendedor" in origin and "Televendas" in origin:
            result["Vendedor + Televendas"] += 1
    return result


def _visible_data(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if context["admin"]:
        return data
    person = context["pessoa"]
    channel = context["canal"]
    owner_seller = channel == "Vendedor"
    mine = _selected(data, "todos", context["setor"], "")
    # A carteira foi delimitada por _selected ANTES de associar nomes/origens.
    # Nenhum cliente de outra carteira sera enviado ao usuario.
    source_by_code = {row["codigo"]: row for row in data["clientes"]}
    rows: list[dict[str, Any]] = []
    for original in mine:
        source = source_by_code.get(original["codigo"], {})
        origens = list(source.get("origens") or [])
        is_inactive = bool(source.get("inativo"))
        positive = bool(origens) and not is_inactive
        direct_key = "positivacoesVendedor" if owner_seller else "positivacoesTelevendas"
        direct = (not is_inactive) and any(_norm(name) == _norm(person) for name in source.get(direct_key, []))
        tv_cadastrados = list(source.get("televendas") or [])
        tv_que_venderam = list(source.get("televendasQuePositivaram") or
                               source.get("positivacoesTelevendas") or [])
        detalhes = []
        for origin in origens:
            if origin == "Televendas" and tv_que_venderam:
                detalhes.append("Televendas: " + ", ".join(dict.fromkeys(tv_que_venderam)))
            elif origin == "Vendedor" and source.get("positivacoesVendedor"):
                detalhes.append("Vendedor: " + ", ".join(source["positivacoesVendedor"]))
            else:
                detalhes.append("Diretoria" if origin == "Diretoria/Supervisão" else origin)
        rows.append({
            "codigo": original["codigo"], "cliente": original["cliente"],
            "cnpj": original.get("cnpj", ""), "bloqueado": bool(original.get("bloqueado")),
            "vendedores": [person] if owner_seller else list(source.get("vendedores") or []),
            "setores": [person] if owner_seller else [],
            "televendas": tv_cadastrados if owner_seller else [person],
            "origens": origens,
            "origensDaVenda": origens,
            "origensDetalhadas": detalhes,
            "creditoIndividual": direct,
            "status": "Inativo" if is_inactive else "Positivado" if positive else "Não positivado",
            "inativo": is_inactive,
            "situacaoInatividade": source.get("situacaoInatividade", ""),
            "inatividadeMotivo": source.get("inatividadeMotivo", ""),
            "inatividadeAprovadaEm": source.get("inatividadeAprovadaEm"),
            "carteiraCompartilhada": bool(source.get("carteiraCompartilhada")),
            "positivacoesVendedor": [person] if owner_seller and direct else [],
            "positivacoesTelevendas": [person] if not owner_seller and direct else [],
        })
    active_rows = [row for row in rows if not row["inativo"]]
    count = len(active_rows)
    positive_count = sum(row["status"] == "Positivado" for row in active_rows)
    direct_count = sum(bool(row["creditoIndividual"]) for row in active_rows)
    blocked = sum(row["bloqueado"] for row in active_rows)
    pct = round(100 * positive_count / count, 2) if count else 0
    totals = {"carteira": count, "positivados": positive_count,
              "naoPositivados": count-positive_count, "percentual": pct,
              "bloqueados": blocked, "inativos": len(rows)-count,
              "positivadosForaCarteira": 0}
    group = {"total": count, "positivados": positive_count,
             "naoPositivados": count-positive_count, "percentual": pct,
             "bloqueados": blocked, "inativos": len(rows)-count}
    if owner_seller:
        group["setor"] = person
        sectors, teles = [group], []
    else:
        group["televendas"] = person
        sectors, teles = [{"setor": person, **{k:v for k,v in group.items() if k!="televendas"}}], [group]
    origins = _origins_for_rows(rows)
    # Somente contagens gerais da empresa: sem listas de outras carteiras.
    general = {key: data.get("indicadores", {}).get(key, 0)
               for key in ("carteira", "positivados", "naoPositivados", "percentual")}
    return {"schema": MODULE, "competencia": data.get("competencia", ""),
            "atualizadoEm": data.get("atualizadoEm", ""),
            "persistencia": data.get("persistencia", "POSTGRESQL"),
            "inatividadesVersao": data.get("inatividadesVersao", "0"),
            "clientes": rows, "setores": sectors, "carteirasTelevendas": teles,
            "origens": origins, "indicadores": totals,
             "creditoIndividual": direct_count, "geralEmpresa": general,
            "movimentacao": {"novos": 0, "removidos": 0,
                             "bloqueadosNovos": 0, "reativados": 0},
            "acesso": {"individual": True, "canal": channel,
                       "profissional": person, "setor": context["setor"]}}


@router.get("/positivacoes/api/resumo-filtro")
async def positivacao_filtered_summary(
    setor: str = "", nao_bloqueados: bool = Query(False),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    setor = _enforced_sector(setor, context)
    data = _visible_data(await _get_data(context["profile"]), context)
    if not setor:
        return _safe_json_response({"indicadores": data["indicadores"],
                                    "origens": data["origens"], "setores": data["setores"],
                                    "carteirasTelevendas": data.get("carteirasTelevendas", [])})
    is_tv = setor.startswith("TV:")
    person = _norm(setor[3:] if is_tv else setor)
    key = "televendas" if is_tv else "setor"
    group = data.get("carteirasTelevendas", []) if is_tv else data["setores"]
    matched = next((x for x in group if _norm(x[key]) == person), None)
    if matched is None:
        raise HTTPException(400, "Profissional indisponivel na fotografia atual.")
    customers = _selected(data, "todos", setor, "", nao_bloqueados)
    live = [x for x in customers if not x.get("inativo")]
    total = len(live)
    positive = sum(x["status"] == "Positivado" for x in live)
    blocked = sum(bool(x["bloqueado"]) for x in live)
    channel = "Televendas" if is_tv else "Vendedor"
    origins = _origins_for_rows(customers)
    focused = {**matched, "total": total, "positivados": positive,
               "naoPositivados": total-positive, "bloqueados": blocked,
               "percentual": round(100*positive/total, 2) if total else 0}
    return _safe_json_response({"indicadores": {
        "carteira": total, "positivados": positive,
        "naoPositivados": total-positive,
        "percentual": round(100*positive/total, 2) if total else 0,
        "bloqueados": blocked, "inativos": len(customers)-total}, "origens": origins, "setores": [focused],
        "profissional": matched[key], "canal": channel})


@router.get("/positivacoes/api/clientes")
async def positivacao_clients(
    status: str = "todos", setor: str = "", busca: str = "", pagina: int = Query(1, ge=1),
    tamanho: int = Query(50, ge=1, le=100),
    nao_bloqueados: bool = Query(False),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    setor = _enforced_sector(setor, context)
    data = _visible_data(await _get_data(context["profile"]), context)
    rows = _selected(data, status, setor, busca, nao_bloqueados)
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


# DEV10.7 — Decisoes da inatividade no sino; autorizacao sempre pelo cookie.
@router.get('/positivacoes/api/notificacoes-sino')
async def positivacoes_sino_inatividades(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    login = str(context['profile'].get('usuario') or '').strip()
    if not login:
        raise HTTPException(403, 'Usuário sem identificação de notificações.')
    result = await _inat_edge('USER_NOTICES', {'usuario': login})
    notices = result.get('notificacoes', [])
    if not isinstance(notices, list):
        raise HTTPException(503, 'Não foi possível consultar suas notificações.')
    return _safe_json_response({
        'sucesso': True, 'itens': notices,
        'naoLidas': sum(not bool(item.get('lida')) for item in notices),
    })


@router.post('/positivacoes/api/notificacoes-sino/{notificacao_id}/ler')
async def positivacoes_sino_inatividade_ler(
    notificacao_id: str,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    login = str(context['profile'].get('usuario') or '').strip()
    if not login:
        raise HTTPException(403, 'Usuário sem identificação de notificações.')
    if not re.fullmatch(r'POS-INAT-[0-9]{1,12}-[1-9][0-9]*-(?:aprovado|rejeitado|reativado)', notificacao_id):
        raise HTTPException(404, 'Notificação não encontrada.')
    await _inat_edge('READ_NOTICE', {'usuario': login, 'id': notificacao_id})
    return _safe_json_response({'sucesso': True})

# DEV10 - observacoes compartilhadas por codigo de cliente, fora da fotografia mensal.
# Somente o backend autenticado possui a credencial para a funcao de observacoes.
class PositivacaoObservacaoNova(BaseModel):
    cliente_codigo: str = Field(min_length=1, max_length=12)
    tipo: str = Field(min_length=4, max_length=12)
    motivo: str = Field(min_length=1, max_length=120)
    texto: str = Field(min_length=1, max_length=1800)
    retorno_em: str | None = None


class PositivacaoObservacaoAlteracao(PositivacaoObservacaoNova):
    id: int = Field(ge=1)
    versao: int = Field(ge=1)
    situacao: str = Field(min_length=7, max_length=10)


async def _obs_edge(acao: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = settings.supabase_url.rstrip('/') + '/functions/v1/dismepe-positivacoes-observacoes'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(22.0)) as client:
            response = await client.post(
                url, json={'acao': acao, **payload},
                headers={'apikey': settings.supabase_publishable_key,
                         'x-dismepe-token': settings.edge_token,
                         'Content-Type': 'application/json', 'Accept': 'application/json'},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(503, 'Não foi possível consultar as observações. Tente novamente.') from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(503, 'A consulta das observações não retornou dados válidos.') from exc
    if not isinstance(result, dict) or not response.is_success or result.get('sucesso') is not True:
        message = result.get('erro', '') if isinstance(result, dict) else ''
        code = 409 if response.status_code == 409 else 503
        raise HTTPException(code, str(message or 'Não foi possível salvar ou consultar as observações.'))
    return result


def _obs_valid_code(value: str) -> str:
    code = str(value or '').strip()
    if not re.fullmatch(r'[0-9]{1,12}', code):
        raise HTTPException(400, 'Código de cliente inválido.')
    return code


def _obs_valid_fields(note: PositivacaoObservacaoNova) -> dict[str, Any]:
    kind = note.tipo.strip().lower()
    if kind not in {'fixa', 'temporaria'}:
        raise HTTPException(400, 'Escolha observação fixa ou temporária.')
    reason, body = note.motivo.strip(), note.texto.strip()
    if not reason or not body or len(reason) > 120 or len(body) > 1800:
        raise HTTPException(400, 'Preencha o motivo e a observação.')
    due = str(note.retorno_em or '').strip()
    if kind == 'temporaria':
        try:
            datetime.strptime(due, '%Y-%m-%d')
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, 'Informe uma data válida para o retorno.') from exc
    return {'tipo': kind, 'motivo': reason, 'texto': body,
            'retorno_em': due if kind == 'temporaria' else None}


async def _obs_permission(context: dict[str, Any], codigo: str,
                          *, historic_admin: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    # Nunca usar o filtro, nome ou papel enviados pelo navegador para autorizar.
    code = _obs_valid_code(codigo)
    data = await _get_data(context['profile'])
    row = next((x for x in data['clientes'] if x['codigo'] == code), None)
    if context['admin']:
        if row is None and not historic_admin:
            raise HTTPException(404, 'Cliente não encontrado na carteira atual.')
        return row, data
    if row is None:
        raise HTTPException(403, 'Cliente fora da sua carteira.')
    own = _norm(context['pessoa'])
    assigned = row.get('televendas', []) if context['canal'] == 'Televendas' else row.get('setores', [])
    if own not in {_norm(name) for name in assigned}:
        raise HTTPException(403, 'Cliente fora da sua carteira.')
    return row, data


async def _obs_page(codes: list[str]) -> list[dict[str, Any]]:
    # Leitura em blocos: nunca consultar uma observação por cliente durante PDF/Excel.
    async def group(batch: list[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = await _obs_edge('LIST', {'codigos': batch, 'offset': offset, 'limite': 500})
            notes = payload.get('observacoes', [])
            if not isinstance(notes, list):
                raise HTTPException(503, 'As observações não puderam ser carregadas.')
            output.extend(notes)
            next_offset = payload.get('proxima')
            if next_offset is None:
                break
            if not isinstance(next_offset, int) or next_offset <= offset or len(output) > 30000:
                raise HTTPException(503, 'A consulta das observações não pôde ser concluída.')
            offset = next_offset
        return output
    unique = list(dict.fromkeys(_obs_valid_code(code) for code in codes))
    semaphore = asyncio.Semaphore(4)
    async def limited(batch: list[str]) -> list[dict[str, Any]]:
        async with semaphore:
            return await group(batch)
    if not unique:
        return []
    pages = await asyncio.gather(*(limited(unique[i:i+100]) for i in range(0, len(unique), 100)))
    return [item for page in pages for item in page]


def _obs_can_edit(note: dict[str, Any], context: dict[str, Any]) -> bool:
    return bool(context['admin'] or
                _norm(note.get('autor_usuario')) == _norm(context['profile'].get('usuario')))


@router.get('/positivacoes/api/observacoes/contagens')
async def positivacao_observacoes_contagens(
    codigos: str = '', session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    selected = [_obs_valid_code(code) for code in codigos.split(',') if code.strip()]
    if not selected or len(selected) > 50:
        raise HTTPException(400, 'Selecione até 50 clientes.')
    data = await _get_data(context['profile'])
    if context['admin']:
        permitted = {item['codigo'] for item in data['clientes']}
    else:
        selected_rows = _selected(data, 'todos', context['setor'], '')
        permitted = {item['codigo'] for item in selected_rows}
    if any(code not in permitted for code in selected):
        raise HTTPException(403, 'Cliente fora da sua carteira.')
    notes = await _obs_page(selected)
    counts: dict[str, int] = {}
    for item in notes:
        code = item['cliente_codigo']
        counts[code] = counts.get(code, 0) + 1
    return _safe_json_response({'sucesso': True, 'contagens': counts})


@router.get('/positivacoes/api/observacoes/administracao')
async def positivacao_observacoes_administracao(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    if not context['admin']:
        raise HTTPException(403, 'Acompanhamento geral reservado à administração.')
    data = await _get_data(context['profile'])
    names = {item['codigo']: item['cliente'] for item in data['clientes']}
    result = await _obs_edge('RECENT', {'limite': 80})
    rows = [{**item, 'cliente': names.get(item['cliente_codigo'], 'Fora da carteira atual')}
            for item in result.get('observacoes', [])]
    return _safe_json_response({'sucesso': True, 'observacoes': rows})


@router.get('/positivacoes/api/observacoes/{codigo}/historico/{observacao_id}')
async def positivacao_observacao_historico(
    codigo: str, observacao_id: int,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    await _obs_permission(context, codigo, historic_admin=True)
    notes = await _obs_page([codigo])
    if not any(note['id'] == observacao_id for note in notes):
        raise HTTPException(404, 'Observação não encontrada neste cliente.')
    result = await _obs_edge('HISTORY', {'id': observacao_id})
    return _safe_json_response({'sucesso': True, 'historico': result.get('historico', [])})


@router.get('/positivacoes/api/observacoes/{codigo}')
async def positivacao_observacoes_cliente(
    codigo: str, session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    row, _ = await _obs_permission(context, codigo, historic_admin=True)
    notes = await _obs_page([codigo])
    for note in notes:
        note['editavel'] = _obs_can_edit(note, context)
    return _safe_json_response({'sucesso': True, 'codigo': codigo,
                                'cliente': row['cliente'] if row else 'Cliente do histórico',
                                'observacoes': notes})


@router.post('/positivacoes/api/observacoes')
async def positivacao_observacoes_criar(
    body: PositivacaoObservacaoNova,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    _, data = await _obs_permission(context, body.cliente_codigo)
    fields = _obs_valid_fields(body)
    author = context['profile']
    author_login = str(author.get('usuario') or '').strip()
    if not author_login:
        raise HTTPException(403, 'Sessão sem usuário identificado.')
    result = await _obs_edge('CREATE', {**fields, 'cliente_codigo': body.cliente_codigo,
        'autor_usuario': author_login,
        'autor_nome': str(author.get('nome') or author.get('vendedor') or context['pessoa'] or author_login)[:160],
        'autor_tipo': _norm(author.get('tipo')),
        'competencia_criacao': str(data.get('competencia') or '')})
    return _safe_json_response({'sucesso': True, 'observacao': result.get('observacao')})


@router.put('/positivacoes/api/observacoes')
async def positivacao_observacoes_alterar(
    body: PositivacaoObservacaoAlteracao,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    await _obs_permission(context, body.cliente_codigo, historic_admin=True)
    notes = await _obs_page([body.cliente_codigo])
    record = next((x for x in notes if x['id'] == body.id), None)
    if not record:
        raise HTTPException(404, 'Observação não encontrada.')
    if not _obs_can_edit(record, context):
        raise HTTPException(403, 'Somente o autor ou um administrador pode alterar esta observação.')
    fields = _obs_valid_fields(body)
    author_login = str(context['profile'].get('usuario') or '').strip()
    result = await _obs_edge('UPDATE', {**fields, 'cliente_codigo': body.cliente_codigo,
        'id': body.id, 'versao': body.versao, 'situacao': body.situacao,
        'atualizada_por': author_login})
    return _safe_json_response({'sucesso': True, 'observacao': result.get('observacao')})


def _obs_export_text(note: dict[str, Any]) -> str:
    kind = 'Fixa' if note['tipo'] == 'fixa' else 'Temporária'
    deadline = (' | Retorno: ' + str(note['retorno_em'])) if note.get('retorno_em') else ''
    status = 'Concluída' if note.get('situacao') == 'concluida' else 'Pendente'
    return (f"{kind} | {note['autor_nome']} | {note['criada_em'][:10]} | {status}{deadline} "
            f"| {note['motivo']}: {note['texto']}")


def _obs_excel_text(value: Any) -> str:
    text = str(value or '')
    # Texto livre nunca pode ser interpretado como formula por um programa de planilhas.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text




# DEV10.3: inatividade aprovada, sem modificar a fotografia mensal.
_INAT_CACHE: list[dict[str, Any]] | None = None
_INAT_CHECK_AT = 0.0
_INAT_REV = 0
_INAT_OVERLAY_KEY: tuple[int, int] | None = None
_INAT_OVERLAY: dict[str, Any] | None = None
_INAT_LOCK = asyncio.Lock()


async def _inat_edge(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = settings.supabase_url.rstrip('/') + '/functions/v1/dismepe-positivacoes-inatividades'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            response = await client.post(
                url, json={'acao': action, **payload},
                headers={'apikey': settings.supabase_publishable_key,
                         'x-dismepe-token': settings.edge_token,
                         'Content-Type': 'application/json', 'Accept': 'application/json'},
            )
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, 'Não foi possível consultar as inatividades. Os indicadores não foram recalculados.') from exc
    if not isinstance(result, dict) or not response.is_success or result.get('sucesso') is not True:
        status = response.status_code if response.status_code in {400, 403, 404, 409} else 503
        raise HTTPException(status, str(result.get('erro') or 'Não foi possível concluir a operação.')
                            if isinstance(result, dict) else 'Serviço de inatividade indisponível.')
    return result


def _inat_invalidate() -> None:
    global _INAT_CACHE, _INAT_CHECK_AT, _INAT_REV, _INAT_OVERLAY, _INAT_OVERLAY_KEY
    _INAT_CACHE = None
    _INAT_CHECK_AT = 0.0
    _INAT_REV += 1
    _INAT_OVERLAY = None
    _INAT_OVERLAY_KEY = None


async def _inat_records() -> list[dict[str, Any]]:
    global _INAT_CACHE, _INAT_CHECK_AT, _INAT_REV
    if _INAT_CACHE is not None and time.monotonic() - _INAT_CHECK_AT < 35:
        return _INAT_CACHE
    async with _INAT_LOCK:
        if _INAT_CACHE is not None and time.monotonic() - _INAT_CHECK_AT < 35:
            return _INAT_CACHE
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = await _inat_edge('LIST', {'offset': offset, 'limite': 1000})
            page = response.get('registros')
            if not isinstance(page, list):
                raise HTTPException(503, 'A lista de inatividades veio incompleta.')
            result.extend(page)
            next_offset = response.get('proxima')
            if next_offset is None:
                break
            if not isinstance(next_offset, int) or next_offset <= offset or len(result) > 20000:
                raise HTTPException(503, 'Não foi possível concluir a consulta de inatividades.')
            offset = next_offset
        _INAT_CACHE = result
        _INAT_CHECK_AT = time.monotonic()
        _INAT_REV += 1
        return result


def _inat_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    live = [row for row in rows if not row.get('inativo')]
    count = len(live)
    pos = sum(row['status'] == 'Positivado' for row in live)
    blocked = sum(bool(row.get('bloqueado')) for row in live)
    return {'carteira': count, 'positivados': pos, 'naoPositivados': count-pos,
            'percentual': round(100*pos/count, 2) if count else 0,
            'bloqueados': blocked, 'inativos': len(rows)-count}


async def _inat_enrich(data: dict[str, Any]) -> dict[str, Any]:
    global _INAT_OVERLAY_KEY, _INAT_OVERLAY
    records = await _inat_records()
    cache_key = (id(data), _INAT_REV)
    if _INAT_OVERLAY is not None and _INAT_OVERLAY_KEY == cache_key:
        return _INAT_OVERLAY
    states = {str(item['cliente_codigo']): item for item in records
              if item.get('situacao') == 'aprovado'}
    rows: list[dict[str, Any]] = []
    for row in data['clientes']:
        state = states.get(str(row['codigo']))
        row = {**row, 'inativo': bool(state),
               'situacaoInatividade': 'aprovado' if state else '',
               'inatividadeAprovadaEm': state.get('decidido_em') if state else None,
               'inatividadeMotivo': state.get('justificativa') if state else '',
               'inatividadeObservacaoId': state.get('observacao_id') if state else None}
        if state:
            row['statusAntesInatividade'] = row.get('status')
            row['status'] = 'Inativo'
        rows.append(row)
    version = max((str(r.get('atualizado_em') or '') for r in records), default='0')
    result = {**data, 'clientes': rows, 'inatividadesVersao': version}
    totals = _inat_counts(rows)
    totals['positivadosForaCarteira'] = data.get('indicadores', {}).get('positivadosForaCarteira', 0)
    totals['clientesVinculosMultiplos'] = sum(bool(r.get('carteiraCompartilhada'))
                                           for r in rows if not r.get('inativo'))
    totals['carteirasHabilitadas'] = data.get('indicadores', {}).get('carteirasHabilitadas', 0)
    result['indicadores'] = totals
    result['origens'] = _origins_for_rows([r for r in rows if not r['inativo']])
    for key, person_key, wallet_key in (('setores', 'setor', 'setores'),
                                         ('carteirasTelevendas', 'televendas', 'televendas')):
        groups: list[dict[str, Any]] = []
        for entry in data.get(key, []):
            person = _norm(entry.get(person_key))
            assigned = [r for r in rows if person in {_norm(n) for n in r.get(wallet_key, [])}]
            metric = _inat_counts(assigned)
            groups.append({**entry, 'total': metric['carteira'],
                           'positivados': metric['positivados'],
                           'naoPositivados': metric['naoPositivados'],
                           'percentual': metric['percentual'],
                           'bloqueados': metric['bloqueados'],
                           'inativos': metric['inativos']})
        result[key] = groups
    result['inativosAprovados'] = len(states)
    _INAT_OVERLAY = result
    _INAT_OVERLAY_KEY = cache_key
    return result


class PositivacaoInatividadeSolicitacao(BaseModel):
    cliente_codigo: str = Field(min_length=1, max_length=12)
    observacao_id: int = Field(ge=1)


class PositivacaoInatividadeDecisao(BaseModel):
    cliente_codigo: str = Field(min_length=1, max_length=12)
    versao: int = Field(ge=1)
    decisao: str = Field(min_length=7, max_length=10)
    justificativa: str = Field(min_length=1, max_length=1200)


@router.get('/positivacoes/api/inatividades/cliente/{codigo}')
async def positivacao_inatividade_cliente(
    codigo: str, session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    await _obs_permission(context, codigo, historic_admin=True)
    records = await _inat_records()
    record = next((r for r in records if str(r['cliente_codigo']) == codigo), None)
    return _safe_json_response({'sucesso': True, 'registro': record})


@router.post('/positivacoes/api/inatividades/solicitar')
async def positivacao_inatividade_solicitar(
    body: PositivacaoInatividadeSolicitacao,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    row, _ = await _obs_permission(context, body.cliente_codigo)
    if row is None or row.get('inativo'):
        raise HTTPException(409, 'Cliente já inativo ou fora da carteira atual.')
    notes = await _obs_page([body.cliente_codigo])
    note = next((n for n in notes if n.get('id') == body.observacao_id and n.get('tipo') == 'fixa'
                 and str(n.get('texto') or '').strip()), None)
    if note is None:
        raise HTTPException(400, 'Cadastre uma observação fixa para solicitar a inatividade.')
    author = context['profile']
    login = str(author.get('usuario') or '').strip()
    if not login:
        raise HTTPException(403, 'Usuário não identificado.')
    result = await _inat_edge('REQUEST', {'cliente_codigo': body.cliente_codigo,
        'observacao_id': body.observacao_id, 'solicitante_usuario': login,
        'solicitante_nome': str(author.get('nome') or author.get('vendedor') or
                               context['pessoa'] or login)[:160],
        'solicitante_tipo': _norm(author.get('tipo')),
        'justificativa': str(note['texto']).strip()[:1800]})
    _inat_invalidate()
    return _safe_json_response({'sucesso': True, 'registro': result['registro'],
                                'mensagem': 'Solicitação enviada para aprovação da administração.'})


@router.get('/positivacoes/api/inatividades/pendentes-contagem')
async def positivacao_inatividade_pendentes_contagem(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    if not context['admin']:
        raise HTTPException(403, 'A consulta de solicitações é exclusiva da administração.')
    # Consulta somente pendentes; limite protegido pela função existente.
    # Ao atingir o limite, mostrar 200+ em vez de alegar contagem exata.
    response = await _inat_edge('ADMIN', {'situacao': 'pendente', 'limite': 200})
    records = response.get('registros')
    if not isinstance(records, list):
        raise HTTPException(503, 'A contagem de solicitações está indisponível.')
    return _safe_json_response({'sucesso': True, 'pendentes': len(records),
                                'limitado': len(records) >= 200})


@router.get('/positivacoes/api/inatividades/administracao')
async def positivacao_inatividade_administracao(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    if not context['admin']:
        raise HTTPException(403, 'A aprovação é exclusiva da administração.')
    data = await _get_data(context['profile'])
    names = {row['codigo']: row['cliente'] for row in data['clientes']}
    result = await _inat_edge('ADMIN', {'limite': 200})
    return _safe_json_response({'sucesso': True, 'registros': [
        {**item, 'cliente': names.get(item['cliente_codigo'], 'Cliente do histórico')}
        for item in result.get('registros', [])]})


@router.post('/positivacoes/api/inatividades/decidir')
async def positivacao_inatividade_decidir(
    body: PositivacaoInatividadeDecisao,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    if not context['admin']:
        raise HTTPException(403, 'Somente a administração pode aprovar ou rejeitar.')
    if body.decisao not in {'aprovado','rejeitado','reativado'}:
        raise HTTPException(400, 'Decisão inválida.')
    if not body.justificativa.strip():
        raise HTTPException(400, 'Informe a justificativa da decisão.')
    # Revalidar cliente pelo código: nenhum nome, perfil ou crédito vem do navegador.
    code = _obs_valid_code(body.cliente_codigo)
    await _obs_permission(context, code, historic_admin=True)
    result = await _inat_edge('REACTIVATE' if body.decisao == 'reativado' else 'DECIDE',
        {'cliente_codigo': code, 'versao': body.versao,
         'administrador_usuario': str(context['profile'].get('usuario') or '').strip(),
         'decisao': body.decisao, 'decisao_motivo': body.justificativa.strip()[:1200]})
    _inat_invalidate()
    # A notificação individual é gravada atomicamente no sino pela trigger SQL.
    return _safe_json_response({'sucesso': True, 'registro': result['registro'],
                                'mensagem': 'Decisão registrada. O solicitante receberá aviso no sino.'})




def _export_fields(row: dict[str, Any]) -> list[str]:
    # A exportacao individual mostra a origem da venda do cliente autorizado,
    # sem alterar o indicador de credito da carteira.
    origins = row.get("origensDaVenda", row["origens"])
    others = [name for name in origins if name in {"Televendas", "Diretoria/Supervisão"}]
    situation = row["status"]
    if situation == "Não positivado" and others:
        situation = "Positivado por " + " e ".join(
            "Diretoria" if name == "Diretoria/Supervisão" else name for name in others
        )
    return [row["codigo"], row["cnpj"], row["cliente"], ", ".join(row["setores"]) or "Sem vínculo cadastrado",
            ", ".join(row["televendas"]), " + ".join(row.get("origensDetalhadas") or origins), situation,
            "Sim" if row["bloqueado"] else "Não"]


@router.get("/positivacoes/api/exportar/{kind}")
async def positivacao_export(
    kind: str, status: str = "todos", setor: str = "", busca: str = "",
    nao_bloqueados: bool = Query(False),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    context = await _viewer_context(session)
    setor = _enforced_sector(setor, context)
    # Nunca processar a exportacao corporativa completa.
    if not setor or not setor.strip():
        raise HTTPException(400, "Selecione um vendedor ou televendas antes de exportar PDF ou Excel.")
    data = _visible_data(await _get_data(context["profile"]), context)
    is_tv = setor.startswith("TV:")
    person = _norm(setor[3:] if is_tv else setor)
    groups = data.get("carteirasTelevendas", []) if is_tv else data.get("setores", [])
    key = "televendas" if is_tv else "setor"
    if not person or not any(_norm(g.get(key)) == person for g in groups):
        raise HTTPException(400, "Selecione uma carteira individual valida antes de exportar.")
    rows = _selected(data, status, setor, busca, nao_bloqueados)
    # Exportacao da carteira sempre inclui um anexo de inativos, mesmo com filtro ativo.
    inativos = _selected(data, "inativos", setor, busca, nao_bloqueados)
    presentes = {row["codigo"] for row in rows}
    rows.extend(row for row in inativos if row["codigo"] not in presentes)
    # Uma unica leitura em blocos dos comentarios dos clientes AUTORIZADOS.
    # A consulta e feita mesmo se houver zero observacoes, para nunca exportar
    # um arquivo incompleto silenciosamente quando o banco estiver indisponivel.
    notes = await _obs_page([row["codigo"] for row in rows])
    notes_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for note in notes:
        notes_by_code[note["cliente_codigo"]].append(note)
    headers = ["Código", "CNPJ", "Cliente", "Carteira", "Televendas Cad.", "Origem", "Status", "Bloqueado"]
    if kind == "excel":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "Positivacao Geral"
        ws.append(headers + ["Observações", "Inatividade"])
        for row in rows:
            texts = "\n\n".join(_obs_export_text(n) for n in notes_by_code.get(row["codigo"], []))
            status_inat = ("INATIVO • aprovado em " + str(row.get("inatividadeAprovadaEm") or "")[:10] +
                           " • " + str(row.get("inatividadeMotivo") or "")) if row.get("inativo") else ""
            ws.append(_export_fields(row) + [_obs_excel_text(texts[:32000]),
                                             _obs_excel_text(status_inat[:32000])])
            if row.get("inativo"):
                for cell in ws[ws.max_row]:
                    cell.fill = PatternFill("solid", fgColor="FCE8E6")
                flag = ws.cell(ws.max_row, 7)
                flag.value = "INATIVO"
                flag.fill = PatternFill("solid", fgColor="B42318")
                flag.font = Font(color="FFFFFF", bold=True)
            if row["bloqueado"] and not row.get("inativo"):
                for cell in ws[ws.max_row]:
                    cell.fill = PatternFill("solid", fgColor="FCE8E6")
                flagged = ws.cell(ws.max_row, 8)
                flagged.value = "BLOQUEADO"
                flagged.fill = PatternFill("solid", fgColor="B42318")
                flagged.font = Font(color="FFFFFF", bold=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="075548")
            cell.font = Font(color="FFFFFF", bold=True)
        for col, width in {"A":12,"B":20,"C":48,"D":43,"E":30,"F":35,"G":20,"H":13,"I":65,"J":62}.items():
            ws.column_dimensions[col].width=width
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment=Alignment(vertical="top", wrap_text=True)
        obs_ws = wb.create_sheet("Observacoes")
        obs_ws.append(["Código", "Cliente", "Autor", "Tipo", "Motivo", "Observação",
                       "Retorno", "Situação", "Criada em", "Última alteração"])
        for row in rows:
            for note in notes_by_code.get(row["codigo"], []):
                obs_ws.append([row["codigo"], row["cliente"], _obs_excel_text(note["autor_nome"]),
                    "Fixa" if note["tipo"] == "fixa" else "Temporária",
                    _obs_excel_text(note["motivo"]), _obs_excel_text(note["texto"]),
                    note.get("retorno_em") or "", "Concluída" if note["situacao"] == "concluida" else "Pendente",
                    note.get("criada_em", ""), note.get("atualizada_em", "")])
        obs_ws.freeze_panes = "A2"
        obs_ws.auto_filter.ref = obs_ws.dimensions
        for cell in obs_ws[1]:
            cell.fill = PatternFill("solid", fgColor="075548")
            cell.font = Font(color="FFFFFF", bold=True)
        for col, width in {"A":12,"B":43,"C":27,"D":15,"E":31,"F":70,"G":17,"H":17,"I":25,"J":25}.items():
            obs_ws.column_dimensions[col].width = width
        for cells in obs_ws.iter_rows(min_row=2):
            for cell in cells:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
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
        styles.add(ParagraphStyle(name="ObsTinyPos", parent=styles["Normal"], fontSize=7,
                                  leading=10, spaceAfter=5, wordWrap="CJK"))
        story=[Paragraph("DISMEPE ONE | Positivação Geral", styles["Heading2"]),
               Paragraph(f"Filtro: {escape(status)} | Setor: {escape(setor or 'Todos')} | Registros: {len(rows)} | Fonte: {escape(data.get('atualizadoEm',''))}", styles["Normal"]), Spacer(1,10)]
        table_data=[[Paragraph(escape(h),styles["CellTinyPos"]) for h in headers]]
        blocked_pdf_rows = []
        inactive_pdf_rows = []
        for row in rows:
            fields = _export_fields(row)
            if row.get("inativo"):
                inactive_pdf_rows.append(len(table_data))
                fields[6] = "INATIVO"
            if row["bloqueado"] and not row.get("inativo"):
                blocked_pdf_rows.append(len(table_data))
                fields[-1] = "BLOQUEADO"
            cells = [Paragraph(escape(str(x)), styles["CellTinyPos"]) for x in fields]
            if row["bloqueado"] and not row.get("inativo"):
                cells[-1] = Paragraph('<font color="#B42318"><b>BLOQUEADO</b></font>', styles["CellTinyPos"])
            table_data.append(cells)
        table=LongTable(table_data, colWidths=[44,72,170,123,106,112,74,55], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#075548")),
                                   ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                                   ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#F4F8F6")]),
                                   ("VALIGN",(0,0),(-1,-1),"TOP"),
                                   ("BOTTOMPADDING",(0,0),(-1,-1),5),
                                   ("TOPPADDING",(0,0),(-1,-1),5),
                                   ("LINEBELOW",(0,0),(-1,0),.5,colors.HexColor("#075548"))]))
        if blocked_pdf_rows:
            table.setStyle(TableStyle([("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FCE8E6"))
                                       for i in blocked_pdf_rows]))
        if inactive_pdf_rows:
            table.setStyle(TableStyle([("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FCE8E6"))
                                       for i in inactive_pdf_rows]))
        story.append(table)
        if notes:
            story.extend([Spacer(1, 16), Paragraph("Observações dos clientes", styles["Heading2"])])
            for row in rows:
                registered = notes_by_code.get(row["codigo"], [])
                if not registered:
                    continue
                label = escape(str(row["codigo"]) + " - " + str(row["cliente"]))
                story.append(Paragraph("<b>" + label + "</b>", styles["Normal"]))
                for note in registered:
                    safe_text = escape(_obs_export_text(note)).replace("\n", "<br/>")
                    story.append(Paragraph(safe_text, styles["ObsTinyPos"]))
                story.append(Spacer(1, 6))
        if inactive_pdf_rows:
            story.extend([Spacer(1,14), Paragraph("Clientes inativos — fora dos indicadores e pendências", styles["Heading2"])])
            for row in rows:
                if row.get("inativo"):
                    desc = ("Cliente " + row["codigo"] + " — " + row["cliente"] +
                            " | Aprovado em: " + str(row.get("inatividadeAprovadaEm") or "")[:10] +
                            " | Motivo: " + str(row.get("inatividadeMotivo") or ""))
                    story.append(Paragraph(escape(desc), styles["ObsTinyPos"]))
        doc.build(story)
        media="application/pdf"; ext="pdf"
    else:
        raise HTTPException(404, "Formato de exportação indisponível.")
    filename=f"POSITIVACAO_GERAL_{datetime.now(TZ).strftime('%Y%m%d')}.{ext}"
    return Response(content=out.getvalue(), media_type=media,
                    headers={"Cache-Control":"no-store, private", "Content-Disposition": f'attachment; filename="{filename}"'})
