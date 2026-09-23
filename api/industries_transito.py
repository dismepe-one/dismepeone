"""Portal Indústrias — Trânsito. Apenas itens vinculados por CNPJ a laboratório autorizado."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Cookie, HTTPException, Query, Request
from fastapi.responses import Response

from .cache_reads import CacheReadError, cache_get
from .industries import (
    ALL_LABS_VALUE, _buyer_all_labs, _choose_lab, _industry_profile, _is_all_labs_request,
    _portal_lab_key, _strict_admin_profile, _edge_admin_write, settings,
)

router = APIRouter()
MODULE = "INDUSTRIAS_TRANSITO_V1"
SCHEMA = "transito-v1"

# Vinculação EXATA do CNPJ do emitente, conferida no ZIP recebido. Não atribuir
# CNPJ de farmácias/distribuidores a laboratórios por aproximação de nomes.
EMITENTE_LAB = {
    "00677858000195": "ARTE NATIVA",
    "02456955000183": "NATULAB",
    "02456955000507": "NATULAB",
    "02625651000100": "SANFARMA",
    "17115437000173": "GLOBO",
    "03485572000104": "GEOLAB",
    "35356799000138": "LAPON",
    "57235426000303": "BRG SUPLEMENTOS NUTRICIONAIS LTDA",
}

def _tag(element: ET.Element | None, tag: str) -> str:
    if element is None:
        return ""
    child = element.find("{*}" + tag)
    return str(child.text or "").strip() if child is not None else ""

def _xml_root(blob: bytes) -> ET.Element:
    if b"<!DOCTYPE" in blob.upper() or b"<!ENTITY" in blob.upper():
        raise ValueError("DTD e entidades não são permitidas.")
    try:
        return ET.fromstring(blob)
    except ET.ParseError:
        # Alguns arquivos fornecidos são Latin-1 mesmo sem declaração correta.
        # Escapar apenas & isolado, preservando referências XML válidas.
        try:
            content = blob.decode("utf-8")
        except UnicodeDecodeError:
            content = blob.decode("latin-1")
        content = re.sub(r"&(?!#(?:\d+|x[0-9a-fA-F]+);|(?:amp|lt|gt|apos|quot);)", "&amp;", content)
        return ET.fromstring(content)

def _decode_zip(blob: bytes) -> tuple[list[dict], dict]:
    if len(blob) > 10 * 1024 * 1024:
        raise HTTPException(413, "ZIP excede o limite de 10 MB.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except (ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, "Envie um arquivo ZIP válido contendo XMLs de NF-e.") from exc
    names = [entry for entry in archive.infolist() if entry.filename.lower().endswith(".xml") and not entry.is_dir()]
    if not names or len(names) > 2000 or sum(entry.file_size for entry in names) > 40 * 1024 * 1024:
        raise HTTPException(400, "ZIP vazio ou acima do limite seguro de arquivos XML.")
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    errors = 0
    unmapped: set[str] = set()
    ignored = 0
    for entry in names:
        if entry.file_size > 2 * 1024 * 1024:
            errors += 1
            continue
        try:
            root = _xml_root(archive.read(entry))
            nfe = root.find(".//{*}infNFe")
            if nfe is None and root.tag.rsplit("}", 1)[-1] == "infNFe":
                nfe = root
            if nfe is None:
                errors += 1
                continue
            ide = nfe.find("{*}ide")
            emit = nfe.find("{*}emit")
            doc = re.sub(r"\D", "", _tag(emit, "CNPJ"))
            lab = EMITENTE_LAB.get(doc, "")
            if not lab:
                unmapped.add(doc or "SEM CNPJ")
                continue
            # Exclui devoluções, entradas e notas complementares: não são carga
            # de fornecedor em trânsito. Dados antigos não comprovam recebimento.
            if _tag(ide, "tpNF") != "1" or _tag(ide, "finNFe") not in {"", "1"}:
                ignored += 1
                continue
            nat = _tag(ide, "natOp").upper()
            if "DEVOLU" in nat:
                ignored += 1
                continue
            emitted = _tag(ide, "dhEmi") or _tag(ide, "dEmi")
            day = emitted[:10]
            datetime.strptime(day, "%Y-%m-%d")
            key = str(nfe.attrib.get("Id") or "").strip() or entry.filename
            for item in nfe.findall("{*}det"):
                prod = item.find("{*}prod")
                if prod is None:
                    continue
                number = str(item.attrib.get("nItem") or len(rows) + 1)
                unique = (key, number)
                if unique in seen:
                    continue
                seen.add(unique)
                amount = Decimal(_tag(prod, "qCom") or "0")
                if not amount.is_finite() or amount <= 0:
                    continue
                rows.append({
                    "dataEmissao": day,
                    "emitente": _tag(emit, "xNome")[:180],
                    "ean": _tag(prod, "cEAN")[:20],
                    "produto": _tag(prod, "xProd")[:260],
                    "quantidade": str(amount),
                    "laboratorio": lab,
                    "chaveItem": key + ":" + number,
                })
        except (ET.ParseError, UnicodeError, ValueError, InvalidOperation, OverflowError):
            errors += 1
    if not rows:
        raise HTTPException(422, "Nenhum item elegível com emitente vinculado a laboratório. A base anterior foi preservada.")
    rows.sort(key=lambda x: (x["dataEmissao"], x["emitente"], x["chaveItem"]), reverse=True)
    return rows, {"arquivos": len(names), "itens": len(rows), "arquivosInvalidos": errors,
                  "naoVinculados": len(unmapped), "operacoesIgnoradas": ignored}

def _scope(rows: list[dict], selected: str) -> list[dict]:
    key = _portal_lab_key(selected)
    filtered = rows if selected == ALL_LABS_VALUE else [
        row for row in rows if _portal_lab_key(row.get("laboratorio")) == key
    ]
    # A API nunca envia o identificador interno da NF-e ou outros laboratórios.
    return [{k: row.get(k, "") for k in ("dataEmissao", "emitente", "ean", "produto", "quantidade")}
            for row in filtered]

@router.get("/industrias/transito")
async def transit_list(
    laboratorio: str | None = Query(default=None),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=True)
    selected = _choose_lab(profile, laboratorio)
    if _is_all_labs_request(selected) and not _buyer_all_labs(profile):
        raise HTTPException(403, "Visão consolidada não autorizada.")
    try:
        payload, _ = await cache_get(modulo=MODULE, settings=settings)
    except CacheReadError as exc:
        if "ainda não está disponível" in str(exc):
            return Response(content=json.dumps({"sucesso": True, "linhas": [], "importado": False}),
                            media_type="application/json", headers={"Cache-Control": "no-store"})
        raise HTTPException(503, "Não foi possível consultar a base de Trânsito.") from exc
    if payload.get("schema") != SCHEMA or not isinstance(payload.get("linhas"), list):
        raise HTTPException(503, "Fotografia de Trânsito inválida.")
    output = {"sucesso": True, "linhas": _scope(payload["linhas"], selected),
              "importado": True, "atualizadoEm": payload.get("atualizadoEm", "")}
    return Response(content=json.dumps(output, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})

@router.post("/admin/industrias/transito/importar")
async def transit_import(
    request: Request,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _strict_admin_profile(session)
    # Exigir mesma origem impede envio autenticado a partir de outra página.
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem da importação não autorizada.")
    if "application/zip" not in request.headers.get("content-type", "").lower():
        raise HTTPException(415, "Envie ZIP em application/zip.")
    if int(request.headers.get("content-length") or 0) > 10 * 1024 * 1024:
        raise HTTPException(413, "ZIP excede o limite de 10 MB.")
    raw = await request.body()
    lines, stats = _decode_zip(raw)
    from datetime import timezone
    stamp = datetime.now(timezone.utc).isoformat()
    payload = {"schema": SCHEMA, "atualizadoEm": stamp, "linhas": lines}
    try:
        await _edge_admin_write("CACHE_SET", {
            "modulo": MODULE, "payload": payload, "nome": "Trânsito — Portal Indústrias",
            "tamanho": len(lines), "versao": SCHEMA,
            "atualizado_por": str(profile.get("usuario") or ""),
        })
        saved, _ = await cache_get(modulo=MODULE, settings=settings)
        if saved.get("atualizadoEm") != stamp or saved.get("schema") != SCHEMA:
            raise RuntimeError("Gravação não confirmada.")
    except Exception as exc:
        raise HTTPException(503, "Não foi possível confirmar a publicação do Trânsito.") from exc
    return {"sucesso": True, **stats, "atualizadoEm": stamp}
