from __future__ import annotations

"""Private PDF storage and administrator archive for signed terms.

Files live in a private Supabase Storage bucket. SQL keeps a minimal, immutable
acceptance record. Signing is a pilot for DANTON and JOSE; no global access
guard is introduced by this module.
"""
import base64
import hashlib
import hmac
import io
import json
import re
import time
import uuid
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .terms_responsibility import (
    VERSION, PILOT, COMPANY, _pilot, _pdf, _edge, settings,
)

router = APIRouter(prefix="/termo")
HASH = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[0-9a-fA-F-]{36}$")
FILE = re.compile(
    r"^TERMO_DISMEPE_ONE_[A-Z0-9_-]+_[0-9]{8}_[0-9]{6}_[0-9a-f]{12}\.pdf$"
)
ZIP_NAME = "TERMOS_DISMEPE_ONE_BACKUP.zip"


def _admin(pilot=Depends(_pilot)):
    profile, user = pilot
    if user != "DANTON" or str(profile.get("tipo") or "").upper() != "ADMINISTRADOR":
        raise HTTPException(403, "A área de gestão dos termos é exclusiva do administrador.")
    return user


async def storage_call(action: str, user: str, **extra):
    if not settings.edge_token or not settings.supabase_publishable_key:
        raise HTTPException(503, "Armazenamento privado não configurado.")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            res = await client.post(
                settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-termos-storage",
                headers={"apikey": settings.supabase_publishable_key,
                         "x-dismepe-token": settings.edge_token},
                json={"acao": action, "usuario": user, **extra},
            )
            data = res.json()
    except Exception as exc:
        raise HTTPException(503, "O armazenamento privado não respondeu.") from exc
    if not res.is_success or data.get("sucesso") is not True:
        code = 403 if res.status_code == 403 else 503
        raise HTTPException(code, "Não foi possível confirmar a operação no armazenamento privado.")
    return data


async def verified_file(user: str, doc_id: str):
    if not ID.fullmatch(doc_id):
        raise HTTPException(422, "Identificador inválido.")
    record = await storage_call("FILE", user, id=doc_id)
    try:
        raw = base64.b64decode(record["pdf_base64"], validate=True)
        filehash = hashlib.sha256(raw).hexdigest()
        name = str(record["arquivo_nome"])
        if not (raw.startswith(b"%PDF-") and 1000 <= len(raw) <= 2097152
                and HASH.fullmatch(record["pdf_sha256"])
                and filehash == record["pdf_sha256"]
                and FILE.fullmatch(name)):
            raise ValueError("invalid content")
        return name, raw, filehash
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Integridade do documento não confirmada.") from exc


def _token(rows):
    # The exact exported document set is signed. Browser cannot modify it.
    payload = json.dumps({
        "iat": int(time.time()),
        "files": [{"id": row["id"], "sha256": row["pdf_sha256"]} for row in rows],
    }, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    mac = hmac.new(settings.jwt_secret.encode("utf-8"), encoded.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return encoded + "." + mac


def _parse_token(value):
    try:
        part, mac = value.rsplit(".", 1)
        expected = hmac.new(settings.jwt_secret.encode("utf-8"), part.encode("ascii"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, mac):
            raise ValueError("mac")
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        age = time.time() - int(data["iat"])
        if not 0 <= age <= 3600 or not isinstance(data["files"], list) or not data["files"]:
            raise ValueError("expired")
        docs = data["files"]
        if len(docs) > 500 or len({str(x["id"]) for x in docs}) != len(docs):
            raise ValueError("invalid")
        for row in docs:
            if not ID.fullmatch(str(row["id"])) or not HASH.fullmatch(str(row["sha256"])):
                raise ValueError("invalid")
        return docs
    except (KeyError, ValueError, TypeError, UnicodeError, IndexError) as exc:
        raise HTTPException(422, "A confirmação do backup expirou. Exporte novamente os PDFs.") from exc


async def sign_private(body, request, pilot):
    from .terms_responsibility import _signature, LOCK, TERM_HASH
    import asyncio
    import base64
    import hashlib
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo
    profile, username = pilot
    if request.headers.get("origin", "").rstrip("/") not in {
        "https://dismepeone.com.br", "https://www.dismepeone.com.br",
        "https://dismepeone.onrender.com",
    }:
        raise HTTPException(403, "Origem de assinatura não autorizada.")
    if body.confirmado is not True:
        raise HTTPException(422, "Confirme a leitura e concordância.")
    signature = _signature(body.assinatura)
    async with LOCK:
        current = await storage_call("STATUS", username)
        if current.get("assinado") is True:
            return {"sucesso": True, "assinado": True, "jaExistia": True}
        now = datetime.now(ZoneInfo("America/Recife"))
        document = await asyncio.to_thread(
            _pdf, username, str(profile.get("tipo") or ""), now, signature
        )
        name = f"TERMO_DISMEPE_ONE_{username}_{now:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:12]}.pdf"
        saved = await storage_call(
            "SAVE", username, aceito_em=now.isoformat(), arquivo_nome=name,
            pdf_sha256=hashlib.sha256(document).hexdigest(), termo_sha256=TERM_HASH,
            pdf_base64=base64.b64encode(document).decode("ascii"),
        )
        if saved.get("assinado") is not True:
            raise HTTPException(503, "PDF não confirmado no armazenamento.")
        return {"sucesso": True, "assinado": True,
                "jaExistia": saved.get("jaExistia") is True}


@router.get("/admin")
async def admin_page(admin=Depends(_admin)):
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "frontend" / "termo-admin.html"
    return HTMLResponse(path.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, private",
                                 "X-Frame-Options": "DENY"})


@router.get("/admin/api/lista")
async def admin_list(admin=Depends(_admin)):
    result = await storage_call("LIST", admin)
    return {"sucesso": True, "documentos": result["documentos"],
            "assinaturaObrigatoriaAtiva": False, "versao": VERSION}


@router.get("/admin/api/arquivo/{doc_id}")
async def admin_pdf(doc_id: str, admin=Depends(_admin)):
    name, raw, _ = await verified_file(admin, doc_id)
    return Response(content=raw, media_type="application/pdf",
                    headers={"Cache-Control": "no-store, private",
                             "Content-Disposition": 'attachment; filename="' + name + '"',
                             "X-Content-Type-Options": "nosniff"})


@router.get("/admin/api/exportar")
async def export_zip(admin=Depends(_admin)):
    data = await storage_call("LIST", admin)
    rows = [row for row in data["documentos"]
            if row.get("storage_path") and not row.get("arquivo_removido_em")]
    if not rows:
        raise HTTPException(404, "Não existem documentos disponíveis para exportação.")
    if len(rows) > 500:
        raise HTTPException(409, "Quantidade acima do limite de exportação por lote.")
    rows.sort(key=lambda x: (x.get("usuario_norm") or "", x.get("id") or ""))
    output = io.BytesIO()
    manifest = []
    total = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for row in rows:
            name, raw, checksum = await verified_file(admin, row["id"])
            total += len(raw)
            if total > 250000000:
                raise HTTPException(409, "O lote excedeu o limite de 250 MB.")
            archive.writestr(name, raw)
            manifest.append({
                "id": row["id"], "arquivo": name, "usuario": row["usuario_norm"],
                "dataAssinatura": row["aceito_em"],
                "versao": row["termo_versao"], "sha256": checksum,
            })
        archive.writestr("MANIFESTO_TERMOS_DISMEPE_ONE.json",
                        json.dumps({"empresa": COMPANY, "geradoEm": datetime.now(
                            ZoneInfo("America/Recife")).isoformat(),
                            "documentos": manifest}, ensure_ascii=False, indent=2))
    return Response(content=output.getvalue(), media_type="application/zip", headers={
        "Cache-Control": "no-store, private",
        "Content-Disposition": 'attachment; filename="' + ZIP_NAME + '"',
        "X-Dismepe-Backup-Token": _token(rows),
        "X-Content-Type-Options": "nosniff",
    })


class ArchiveRequest(BaseModel):
    token: str
    confirmacao: str


@router.post("/admin/api/arquivar")
async def archive_files(body: ArchiveRequest, admin=Depends(_admin)):
    if body.confirmacao != "CONFIRMO BACKUP":
        raise HTTPException(422, "Confirme que salvou e conferiu o arquivo ZIP.")
    exported = _parse_token(body.token)
    current = await storage_call("LIST", admin)
    remaining = [
        r for r in current["documentos"]
        if r.get("storage_path") and not r.get("arquivo_removido_em")
    ]
    expected = sorted((str(r["id"]), str(r["pdf_sha256"])) for r in remaining)
    actual = sorted((str(r["id"]), str(r["sha256"])) for r in exported)
    if not remaining or expected != actual:
        raise HTTPException(409, "O conjunto de documentos mudou. Exporte novamente antes de arquivar.")
    ids = [str(row["id"]) for row in exported]
    # Verify every PDF again before a deletion is authorized.
    for row in exported:
        _, _, checksum = await verified_file(admin, str(row["id"]))
        if checksum != row["sha256"]:
            raise HTTPException(409, "Documento alterado desde a exportação.")
    await storage_call("BACKUP_CONFIRM", admin, ids=ids)
    result = await storage_call("ARCHIVE", admin, ids=ids)
    return {"sucesso": True, "arquivosRemovidos": result.get("arquivosRemovidos", 0),
            "registrosAceitePreservados": True}
