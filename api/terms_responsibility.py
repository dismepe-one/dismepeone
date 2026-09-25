from __future__ import annotations

"""Pilot-only confidentiality agreement. No automatic lock until Drive and PDF validation."""
import asyncio
import base64
import hashlib
import io
import os
import re
import struct
import uuid
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .security import decode_session_token
from .industries_stock_sync import _service_account_info

settings = get_settings()
router = APIRouter(prefix="/termo")
ROOT = Path(__file__).resolve().parents[1]
FOLDER_ID = "1UhQWm0edCZdYSCFrF2BSvV-_5Eh8fTvd"
COMPANY = "DISMEPE DISTRIBUIDORA DE PRODUTOS FARMACEUTICOS LTDA."
VERSION = "1.0"
PILOT = {"DANTON": "Danton", "JOSE": "José"}
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
# Intentionally false in the first deploy. Do not enable until server-account
# create/read/delete and a complete signed-document roundtrip have been verified.
ENFORCE = os.getenv("DISMEPE_TERMS_ENFORCE", "false").strip().lower() == "true"
LOCK = asyncio.Lock()

CLAUSES = (
    ("1. Objeto", "Este Termo estabelece as condições de acesso, uso, proteção e confidencialidade das informações disponibilizadas no DISMEPE ONE. O acesso é concedido exclusivamente para atividades profissionais autorizadas."),
    ("2. Informações protegidas", "São confidenciais, entre outras, as informações de faturamento, vendas, clientes, carteiras, setores, metas, preços, descontos, negociações, campanhas, comissões, premiações, estoque, fornecedores, laboratórios, relatórios, projeções, estratégias comerciais e dados pessoais acessíveis pelo sistema."),
    ("3. Compromisso de confidencialidade", "Comprometo-me a não divulgar ou compartilhar informações com pessoas não autorizadas; não encaminhar fotografias, capturas de tela, relatórios, planilhas ou documentos sigilosos sem autorização; não transferir dados para contas, dispositivos ou plataformas externas sem autorização; não utilizar as informações em benefício próprio ou de terceiros; não compartilhar credenciais; e não consultar, copiar ou exportar dados fora do meu escopo autorizado."),
    ("4. Responsabilidade pelo acesso", "Comprometo-me a proteger minhas credenciais e meus dispositivos e a comunicar imediatamente à gestão qualquer suspeita de vazamento, perda de dispositivo, acesso indevido ou exposição de dados. O uso indevido poderá ensejar suspensão do acesso e medidas administrativas, contratuais e legais cabíveis, conforme as circunstâncias e a legislação aplicável."),
    ("5. Encerramento do vínculo", "O compromisso de sigilo permanece após o encerramento do vínculo profissional ou do acesso ao sistema, enquanto as informações permanecerem confidenciais ou legalmente protegidas. Deixarei de utilizá-las e seguirei as instruções da DISMEPE sobre devolução ou eliminação dos arquivos, observadas as obrigações legais."),
    ("6. Proteção de dados pessoais", "Tratarei dados pessoais apenas para finalidades profissionais autorizadas, segundo as orientações da empresa e a legislação aplicável. Os dados do aceite serão utilizados para identificação, registro e comprovação da assinatura, observadas as regras de proteção de dados."),
    ("7. Declaração e assinatura eletrônica", "Declaro ter lido e compreendido este Termo; reconheço o caráter confidencial das informações; comprometo-me a cumprir as obrigações aqui descritas; e concordo em associar meu aceite e minha assinatura desenhada à minha conta autenticada, à versão deste Termo e à data e hora registradas pelo servidor."),
)
TEXT = "\n\n".join(f"{heading}\n{text}" for heading, text in CLAUSES)
TERM_HASH = hashlib.sha256((COMPANY + "\n" + VERSION + "\n" + TEXT).encode("utf-8")).hexdigest()
ACCEPTED = {}  # Short-lived status cache; never the source of truth.


def _profile(session: str | None):
    if not session:
        raise HTTPException(401, "Entre na sua conta.")
    try:
        profile = decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except Exception as exc:
        raise HTTPException(401, "Sessão inválida ou expirada.") from exc
    username = str(profile.get("usuario") or profile.get("sub") or "").strip().upper()
    if username not in PILOT:
        raise HTTPException(403, "Assinatura disponível apenas para as contas do piloto.")
    return profile, username


def _pilot(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    return _profile(session)


async def _edge(action: str, username: str, **extra):
    if not settings.edge_token or not settings.supabase_publishable_key:
        raise HTTPException(503, "Serviço de registro do termo não configurado.")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-termos",
                headers={"apikey": settings.supabase_publishable_key, "x-dismepe-token": settings.edge_token},
                json={"acao": action, "usuario": username, "versao": VERSION, **extra},
            )
            data = response.json()
        if not response.is_success or data.get("sucesso") is not True:
            raise HTTPException(503, "Não foi possível confirmar o aceite no PostgreSQL.")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Registro de termos temporariamente indisponível.") from exc


async def signed(username: str) -> bool:
    # Use SQL as authority even when cookies persist or another device signed.
    from .terms_storage_routes import storage_call
    result = await storage_call("STATUS", username)
    return result.get("assinado") is True


def _google_service():
    info = _service_account_info()
    if not info or info.get("type") != "service_account":
        raise RuntimeError("CONTA_TECNICA_NAO_CONFIGURADA")
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    credentials = Credentials.from_service_account_info(info, scopes=[DRIVE_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _folder(service):
    try:
        meta = service.files().get(
            fileId=FOLDER_ID, fields="id,mimeType,capabilities(canAddChildren)",
            supportsAllDrives=True,
        ).execute()
    except Exception as exc:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError) and exc.resp.status in {403, 404}:
            raise RuntimeError("PASTA_INACESSIVEL_CONTA_TECNICA") from exc
        raise
    if meta.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError("PASTA_INVALIDA")
    if meta.get("capabilities", {}).get("canAddChildren") is not True:
        raise RuntimeError("SEM_PERMISSAO_DE_GRAVACAO")


def _pdf(username: str, role: str, accepted_at: datetime, signature_png: bytes | None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, KeepTogether, HRFlowable

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=17*mm, bottomMargin=18*mm,
                            rightMargin=19*mm, leftMargin=19*mm,
                            title="Termo de Responsabilidade e Confidencialidade - DISMEPE ONE")
    st = getSampleStyleSheet()
    st.add(ParagraphStyle(name="BrandONE", parent=st["Heading1"], fontName="Helvetica-Bold",
                          alignment=TA_CENTER, textColor=colors.HexColor("#135441"), fontSize=14,
                          spaceAfter=8, leading=19))
    st.add(ParagraphStyle(name="TermsSection", parent=st["Heading2"],
                          textColor=colors.HexColor("#135441"), fontSize=10.5,
                          spaceBefore=10, spaceAfter=4, leading=14))
    st.add(ParagraphStyle(name="TermsBody", parent=st["Normal"], fontName="Helvetica",
                          fontSize=9.2, leading=13.1, spaceAfter=3))
    story = []
    logo = ROOT / "frontend" / "app-icon-v2-192.png"
    if not logo.is_file():
        raise RuntimeError("LOGO_OFICIAL_AUSENTE")
    image = Image(str(logo), width=22*mm, height=22*mm)
    image.hAlign = "CENTER"
    story.extend([image, Spacer(1, 5*mm),
        Paragraph("DISMEPE ONE - TERMO DE RESPONSABILIDADE E CONFIDENCIALIDADE", st["BrandONE"]),
        Paragraph(escape(COMPANY), st["TermsBody"]),
        Paragraph("Versão " + VERSION + " | Identificador de integridade do texto: " + TERM_HASH, st["TermsBody"]),
        HRFlowable(width="100%", color=colors.HexColor("#d3e3db"), thickness=1), Spacer(1, 3*mm)])
    for heading, content in CLAUSES:
        story.append(KeepTogether([Paragraph(escape(heading), st["TermsSection"]),
                                  Paragraph(escape(content), st["TermsBody"])]))
    tz = accepted_at.astimezone(ZoneInfo("America/Recife"))
    story.extend([Spacer(1, 8*mm), HRFlowable(width="100%", color=colors.HexColor("#d3e3db")),
        Paragraph("IDENTIFICAÇÃO DO SIGNATÁRIO", st["TermsSection"]),
        Paragraph("Nome: " + escape(PILOT[username]) + " | Conta: " + escape(username) +
                  " | Cargo: " + escape(role), st["TermsBody"]),
        Paragraph("Aceite: " + tz.strftime("%d/%m/%Y %H:%M:%S") + " (America/Recife)" +
                  " | Versão: " + VERSION, st["TermsBody"])])
    if signature_png:
        signature = Image(io.BytesIO(signature_png), width=72*mm, height=25*mm)
        signature.hAlign = "LEFT"
        story.extend([Spacer(1, 4*mm), signature, Paragraph("Assinatura eletrônica desenhada pelo signatário autenticado.", st["TermsBody"])])
    else:
        story.append(Paragraph("AMOSTRA DE DIAGNÓSTICO - NÃO CONTÉM ASSINATURA OU ACEITE.", st["TermsBody"]))
    doc.build(story)
    content = buffer.getvalue()
    if not content.startswith(b"%PDF-") or len(content) < 1000:
        raise RuntimeError("PDF_NAO_GERADO")
    return content


def _signature(value: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise HTTPException(422, "Desenhe sua assinatura para continuar.")
    if len(value) > 350000:
        raise HTTPException(422, "Assinatura excedeu o limite permitido.")
    try:
        data = base64.b64decode(value[len(prefix):], validate=True)
        if not (250 <= len(data) <= 250000 and data[:8] == b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG inválido")
        width, height = struct.unpack(">II", data[16:24])
        if not (100 <= width <= 1600 and 40 <= height <= 700):
            raise ValueError("Dimensão inválida")
        from reportlab.lib.utils import ImageReader
        ImageReader(io.BytesIO(data)).getSize()
        return data
    except Exception as exc:
        raise HTTPException(422, "A imagem da assinatura não é válida.") from exc


def _upload_and_verify(pdf: bytes, filename: str):
    from googleapiclient.http import MediaIoBaseUpload
    service = _google_service()
    _folder(service)
    created = None
    try:
        created = service.files().create(
            body={"name": filename, "mimeType": "application/pdf", "parents": [FOLDER_ID]},
            media_body=MediaIoBaseUpload(io.BytesIO(pdf), mimetype="application/pdf", resumable=False),
            fields="id,name,parents,mimeType", supportsAllDrives=True,
        ).execute()
        fid = str(created.get("id") or "")
        if not fid or FOLDER_ID not in created.get("parents", []):
            raise RuntimeError("GRAVACAO_NAO_CONFIRMADA")
        downloaded = service.files().get_media(fileId=fid, supportsAllDrives=True).execute()
        if hashlib.sha256(downloaded).digest() != hashlib.sha256(pdf).digest():
            raise RuntimeError("PDF_NO_DRIVE_DIVERGENTE")
        return fid
    except Exception:
        if created and created.get("id"):
            try:
                service.files().delete(fileId=created["id"], supportsAllDrives=True).execute()
            except Exception:
                pass
        raise


def _probe_drive():
    sample = _pdf("DANTON", "ADMINISTRADOR", datetime.now(ZoneInfo("America/Recife")), None)
    from pypdf import PdfReader
    parsed = PdfReader(io.BytesIO(sample))
    content = "\n".join(page.extract_text() or "" for page in parsed.pages)
    if not parsed.pages or "TERMO DE RESPONSABILIDADE" not in content or "DANTON" not in content.upper():
        raise RuntimeError("PDF_NAO_GERADO")
    service = _google_service()
    _folder(service)
    filename = "TESTE_TECNICO_TERMO_" + uuid.uuid4().hex + ".pdf"
    file_id = None
    try:
        file_id = _upload_and_verify(sample, filename)
        return file_id
    finally:
        if file_id:
            service.files().delete(fileId=file_id, supportsAllDrives=True).execute()


@router.get("/api/status")
async def term_status(pilot=Depends(_pilot)):
    profile, username = pilot
    from .terms_storage_routes import storage_call
    db = await storage_call("STATUS", username)
    return {
        "sucesso": True, "usuario": username, "nome": PILOT[username],
        "cargo": str(profile.get("tipo") or ""), "versao": VERSION,
        "empresa": COMPANY, "texto": [{"titulo": h, "texto": p} for h,p in CLAUSES],
        "assinado": db.get("assinado") is True, "aceitoEm": db.get("aceitoEm"),
        "obrigatorio": ENFORCE, "hashTermo": TERM_HASH,
    }


@router.get("/assinar")
async def term_page(pilot=Depends(_pilot)):
    return FileResponse(ROOT / "frontend" / "termo-assinatura.html",
                        media_type="text/html",
                        headers={"Cache-Control": "no-store, private", "X-Frame-Options": "DENY"})


@router.get("/api/diagnostico")
async def term_diagnostic(pilot=Depends(_pilot)):
    _, username = pilot
    if username != "DANTON":
        raise HTTPException(403, "Diagnóstico restrito ao administrador.")
    # Retornar somente o endereço público de identificação da conta de
    # serviço; nunca expor JSON de credenciais, token ou chave privada.
    info = _service_account_info() or {}
    sa_email = str(info.get("client_email") or "").strip()
    if not sa_email.endswith(".gserviceaccount.com"):
        sa_email = ""
    try:
        await asyncio.to_thread(_probe_drive)
        return {"sucesso": True, "contaTecnica": "CONFIGURADA",
                "emailContaTecnica": sa_email,
                "pasta": "ACESSIVEL", "gravarLerExcluirPDF": "CONFIRMADO",
                "obrigatoriedadeAtiva": ENFORCE}
    except Exception as exc:
        # Categorizar o erro sem revelar mensagens da API, tokens ou credenciais.
        kind = str(exc) if str(exc) in {
            "CONTA_TECNICA_NAO_CONFIGURADA", "PASTA_INVALIDA",
            "PASTA_INACESSIVEL_CONTA_TECNICA",
            "SEM_PERMISSAO_DE_GRAVACAO", "LOGO_OFICIAL_AUSENTE",
            "PDF_NAO_GERADO", "GRAVACAO_NAO_CONFIRMADA", "PDF_NO_DRIVE_DIVERGENTE"
        } else "FALHA_GOOGLE_DRIVE_OU_PDF"
        try:
            from googleapiclient.errors import HttpError
            if isinstance(exc, HttpError):
                status = int(exc.resp.status)
                raw = bytes(exc.content or b"").decode("utf-8", "replace").lower()
                if "storagequotaexceeded" in raw or "storage quota" in raw:
                    kind = "COTA_DRIVE_CONTA_TECNICA"
                elif status in {401, 403, 404}:
                    kind = "ACESSO_DRIVE_CONTA_TECNICA_NEGADO"
                elif status == 429:
                    kind = "LIMITE_TEMPORARIO_GOOGLE_DRIVE"
        except Exception:
            pass
        return {"sucesso": False, "motivo": kind,
                "emailContaTecnica": sa_email,
                "obrigatoriedadeAtiva": ENFORCE}


class SignRequest(BaseModel):
    confirmado: bool
    assinatura: str = Field(min_length=300, max_length=350000)


@router.post("/api/assinar")
async def term_sign(body: SignRequest, request: Request, pilot=Depends(_pilot)):
    profile, username = pilot
    origin = request.headers.get("origin", "").rstrip("/")
    if origin not in {"https://dismepeone.com.br", "https://www.dismepeone.com.br",
                      "https://dismepeone.onrender.com"}:
        raise HTTPException(403, "Origem de assinatura não autorizada.")
    if body.confirmado is not True:
        raise HTTPException(422, "Confirme a leitura e concordância com o termo.")
    signature = _signature(body.assinatura)
    async with LOCK:
        existing = await _edge("STATUS", username)
        if existing.get("assinado") is True:
            return {"sucesso": True, "assinado": True, "jaExistia": True}
        now = datetime.now(ZoneInfo("America/Recife"))
        document = await asyncio.to_thread(_pdf, username, str(profile.get("tipo") or ""), now, signature)
        filename = (f"TERMO_DISMEPE_ONE_{username}_{now:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:12]}.pdf")
        try:
            fid = await asyncio.to_thread(_upload_and_verify, document, filename)
        except Exception as exc:
            if str(exc) == "PASTA_INACESSIVEL_CONTA_TECNICA":
                raise HTTPException(
                    503, "A conta técnica ainda não consegue acessar a pasta de termos. "
                         "Na conta DANTON, abra o diagnóstico e confira qual endereço "
                         "precisa de acesso de Editor à pasta. Nenhum aceite foi registrado."
                ) from exc
            raise HTTPException(503, "O Drive não confirmou o arquivo assinado. Nenhum aceite foi registrado.") from exc
        try:
            result = await _edge(
                "COMPLETE", username, aceito_em=now.isoformat(),
                arquivo_drive_id=fid, arquivo_nome=filename,
                pdf_sha256=hashlib.sha256(document).hexdigest(),
                termo_sha256=TERM_HASH,
            )
        except HTTPException:
            # Retain uploaded PDF as recovery evidence; do not mark the user as signed.
            raise HTTPException(503, "PDF salvo, mas o registro do aceite não foi confirmado. Contate a gestão.")
        return {"sucesso": True, "assinado": result.get("assinado") is True,
                "jaExistia": result.get("jaExistia") is True}
