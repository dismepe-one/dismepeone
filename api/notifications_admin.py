from __future__ import annotations

"""Painel administrativo de notificações. Integra-se às tabelas e ao sino legados."""
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .access_reads import AccessReadError, admin_edge
from .config import get_settings
from .security import decode_session_token, normalizar
from .push_notifications import deliver_notice

router = APIRouter()
settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]
ADMIN_ROLES = {"ADMIN", "ADMINISTRADOR"}
MODULES = {
    "HOME": {"INICIO"},
    "CAMPANHAS": {"MENSAIS", "EXTRAS"},
    "VENDEDORES": {"PARCIAL"},
    "TELEVENDAS": {"PARCIAL"},
    "POSITIVACOES": {"GERAL"},
    "INDUSTRIAS": {"INICIO", "MAPA"},
}


def _profile(session: str | None) -> dict:
    if not session:
        raise HTTPException(status_code=401, detail="Entre na sua conta para continuar.")
    try:
        return decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.") from exc


def _admin(session: str | None = Cookie(default=None, alias=settings.cookie_name)) -> dict:
    profile = _profile(session)
    if normalizar(profile.get("tipo")) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Apenas administradores podem criar notificações.")
    return profile


def _user_ok(row: dict) -> bool:
    return row.get("ativo") is True and normalizar(row.get("status")) not in {"EXCLUIDO", "INATIVO", "BLOQUEADO"}


async def _users() -> list[dict]:
    try:
        result = await admin_edge(action="USUARIOS_LIST", data={}, settings=settings)
    except AccessReadError as exc:
        raise HTTPException(status_code=503, detail="Não foi possível consultar os destinatários.") from exc
    return [row for row in result.get("usuarios", []) if isinstance(row, dict) and _user_ok(row)]


def _public_user(row: dict) -> dict:
    return {
        "usuario": str(row.get("usuario") or "").strip(),
        "nome": str(row.get("nome") or row.get("vendedor") or row.get("usuario") or "").strip(),
        "cargo": str(row.get("tipo") or "").strip(),
        "setor": str(row.get("setor") or "").strip(),
    }


class Destination(BaseModel):
    modulo: str
    tela: str
    fornecedor: str = ""


class NotificationRequest(BaseModel):
    titulo: str = Field(min_length=3, max_length=120)
    mensagem: str = Field(min_length=3, max_length=700)
    modo: str
    usuarios: list[str] = Field(default_factory=list, max_length=100)
    cargos: list[str] = Field(default_factory=list, max_length=50)
    destino: Destination


@router.get("/notificacoes/admin", include_in_schema=False)
async def admin_page(profile: dict = Depends(_admin)):
    return FileResponse(
        ROOT / "frontend" / "notificacoes-admin.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/notificacoes/admin.js", include_in_schema=False)
async def admin_script(profile: dict = Depends(_admin)):
    return FileResponse(
        ROOT / "frontend" / "notificacoes-admin.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/notificacoes/launcher.js", include_in_schema=False)
async def launcher_script():
    return FileResponse(
        ROOT / "frontend" / "notificacoes-launcher.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/notificacoes/api/usuarios")
async def search_users(q: str = "", profile: dict = Depends(_admin)):
    query = normalizar(q)[:90]
    if len(query) < 2:
        return {"usuarios": []}
    matched = []
    for row in await _users():
        item = _public_user(row)
        if query in normalizar(" ".join(item.values())):
            matched.append(item)
        if len(matched) >= 12:
            break
    return {"usuarios": matched}


@router.get("/notificacoes/api/cargos")
async def list_roles(profile: dict = Depends(_admin)):
    roles = sorted({str(row.get("tipo") or "").strip() for row in await _users() if str(row.get("tipo") or "").strip()})
    return {"cargos": roles}


@router.get("/notificacoes/api/historico")
async def notification_history(profile: dict = Depends(_admin)):
    try:
        data = await admin_edge(action="NOTIFICACOES_ADMIN_LIST", data={}, settings=settings)
    except AccessReadError as exc:
        raise HTTPException(status_code=503, detail="Histórico indisponível.") from exc
    rows = [
        {"id": item.get("id"), "titulo": item.get("titulo"), "mensagem": item.get("mensagem"), "criadoEm": item.get("criadoEm"),
         "criadoPor": item.get("criadoPor"), "destino": item.get("destino"),
         "publico": item.get("publico"), "push": item.get("pushStatus") or "AGENDADO"}
        for item in data.get("notificacoes", [])
        if isinstance(item, dict) and str(item.get("id") or "").startswith("ONE-PUSH-")
    ]
    return {"notificacoes": rows[:120]}


@router.post("/notificacoes/api/enviar")
async def send_notification(payload: NotificationRequest, background_tasks: BackgroundTasks, profile: dict = Depends(_admin)):
    titulo = payload.titulo.strip()
    mensagem = payload.mensagem.strip()
    if len(titulo) < 3 or len(mensagem) < 3:
        raise HTTPException(status_code=422, detail="Preencha título e mensagem.")
    modo = normalizar(payload.modo)
    if modo not in {"TODOS", "CARGOS", "USUARIOS", "INDUSTRIAS"}:
        raise HTTPException(status_code=422, detail="Destinatários inválidos.")
    modulo = normalizar(payload.destino.modulo)
    tela = normalizar(payload.destino.tela)
    if modulo not in MODULES or tela not in MODULES[modulo]:
        raise HTTPException(status_code=422, detail="Destino não cadastrado.")
    fornecedor = payload.destino.fornecedor.strip()
    if len(fornecedor) > 90 or (fornecedor and (modulo, tela) != ("TELEVENDAS", "PARCIAL")):
        raise HTTPException(status_code=422, detail="Filtro de fornecedor inválido.")

    users = await _users()
    role_names = {normalizar(row.get("tipo")): str(row.get("tipo") or "") for row in users}
    by_login = {normalizar(row.get("usuario")): str(row.get("usuario")) for row in users}
    chosen_users: list[str] = []
    chosen_roles: list[str] = []
    if modo == "USUARIOS":
        wanted = {normalizar(name) for name in payload.usuarios if str(name).strip()}
        if not wanted or not wanted.issubset(by_login.keys()):
            raise HTTPException(status_code=422, detail="Selecione usuários ativos válidos.")
        chosen_users = sorted({by_login[name] for name in wanted})
    elif modo == "CARGOS":
        wanted = {normalizar(role) for role in payload.cargos if str(role).strip()}
        if not wanted or not wanted.issubset(role_names.keys()):
            raise HTTPException(status_code=422, detail="Selecione cargos válidos.")
        chosen_roles = sorted({role_names[name] for name in wanted})
    elif modo == "INDUSTRIAS":
        if not any(normalizar(row.get("tipo")) == "INDUSTRIA" for row in users):
            raise HTTPException(status_code=422, detail="Nenhuma conta de indústria ativa localizada.")
        chosen_roles = ["INDUSTRIA"]

    if modo == "INDUSTRIAS" and modulo not in {"HOME", "INDUSTRIAS"}:
        raise HTTPException(status_code=422, detail="Selecione HOME ou Indústrias para avisos coletivos da indústria.")
    if modulo == "INDUSTRIAS" and modo == "TODOS":
        raise HTTPException(status_code=422, detail="O destino Indústrias não pode ser enviado a todos os usuários do sistema.")

    # O módulo de gestão corporativa não pode ser divulgado para contas comuns.
    if modulo == "POSITIVACOES":
        recipients = users if modo == "TODOS" else [
            row for row in users if (
                (modo == "USUARIOS" and str(row.get("usuario")) in chosen_users)
                or (modo == "CARGOS" and str(row.get("tipo")) in chosen_roles)
            )
        ]
        if not recipients or any(normalizar(row.get("tipo")) not in ADMIN_ROLES for row in recipients):
            raise HTTPException(status_code=422, detail="Positivações Gerais: selecione apenas administradores.")

    now = datetime.now(ZoneInfo("America/Recife"))
    item_id = "ONE-PUSH-" + uuid.uuid4().hex
    dest = {"modulo": modulo, "tela": tela, "fornecedor": fornecedor}
    notice = {
        "id": item_id, "tipo": "AVISO", "status": "ATIVO",
        "titulo": titulo, "mensagem": mensagem,
        "publico": {"todos": modo == "TODOS", "perfis": chosen_roles,
                    "setores": [], "usuarios": chosen_users},
        "criadoEpoch": int(now.timestamp() * 1000),
        "criadoEm": now.strftime("%d/%m/%Y %H:%M"),
        "criadoPor": str(profile.get("nome") or profile.get("usuario") or "Admin"),
        "publicarEm": now.isoformat(), "expiraEm": "",
        "importante": False, "exibirUmaVez": False,
        "destino": dest, "pushStatus": "AGENDADO",
    }
    try:
        result = await admin_edge(action="NOTIFICACAO_UPSERT", data={"notificacao": notice}, settings=settings)
    except AccessReadError as exc:
        raise HTTPException(status_code=503, detail="Não foi possível salvar a notificação no banco.") from exc
    if str(result.get("id") or "") != item_id:
        raise HTTPException(status_code=503, detail="A gravação da notificação não foi confirmada.")
    # O sino interno continua independente da entrega externa.
    background_tasks.add_task(deliver_notice, item_id)
    return {"sucesso": True, "id": item_id,
            "mensagem": "Aviso registrado no sistema; a entrega Push foi agendada para os dispositivos autorizados.",
            "pushAgendado": True, "destino": dest}
