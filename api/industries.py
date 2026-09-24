from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import re
import secrets
import time
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import httpx
import jwt
from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .cache_reads import CacheReadError, cache_get
from .config import get_settings
from .security import auth_email, decode_session_token, issue_session_token, normalizar, senha_interna
from .industries_stock_sync import CURRENT_FILE as STOCK_CURRENT_FILE, FALLBACK_FILE as STOCK_FALLBACK_FILE, stock_sync_public_status, sync_stock_once
from .industries_sales_sync import ensure_general_sales_fresh, general_sales_sync_public_status


settings = get_settings()
router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]
INDUSTRIES_FILE = ROOT / "frontend" / "industries.html"
STOCK_FILE = STOCK_CURRENT_FILE
GENERAL_SALES_FILE = ROOT / "data" / "industries" / "venda_geral_atual.json"
GENERAL_SALES_HISTORY_FILE = ROOT / "data" / "industries" / "venda_geral_historico.json"
_STOCK_SNAPSHOT_CACHE: tuple[float, dict[str, Any]] | None = None
_STOCK_SNAPSHOT_TTL_SECONDS = 30.0

ROLE_INDUSTRY = "INDUSTRIA"
ROLE_BUYER = "COMPRADOR"
PERM_PORTAL = "INDUSTRIA_PORTAL"
PERM_FIRST_ACCESS = "INDUSTRIA_TROCAR_SENHA"
PERM_LABS = "INDUSTRIA_LABORATORIOS"
PERM_STOCK_UPDATE = "INDUSTRIA_MAPA_ATUALIZAR"
PERM_INTERNAL_PORTAL = "INDUSTRIA_PORTAL_INTERNO"
PERM_BUYER_ALL_LABS = "INDUSTRIA_TODOS_LABORATORIOS"

ALL_LABS_VALUE = "__TODOS__"
ALL_LABS_LABEL = "TODOS OS LABORATÓRIOS"

# Segurança de credenciais internas. A senha temporária nunca é persistida
# pelo FastAPI; ela existe apenas em memória e é devolvida uma única vez ao administrador.
PERM_PASSWORD_CHANGE_REQUIRED = "SEGURANCA_TROCA_SENHA_OBRIGATORIA"
LEGACY_DEFAULT_PASSWORD = "1234"
_PASSWORD_RESET_LOCK = asyncio.Lock()


class IndustryUserCreateRequest(BaseModel):
    usuario: str = Field(min_length=2, max_length=120)
    nome: str = Field(min_length=2, max_length=160)
    laboratorios: list[str] = Field(min_length=1, max_length=10)


class IndustryUserLabsUpdateRequest(BaseModel):
    usuario: str = Field(min_length=2, max_length=120)
    laboratorios: list[str] = Field(min_length=1, max_length=10)


class IndustryPasswordRequest(BaseModel):
    senhaAtual: str = Field(min_length=1, max_length=256)
    novaSenha: str = Field(min_length=6, max_length=256)


class ForcedPasswordChangeRequest(BaseModel):
    senhaAtual: str = Field(min_length=1, max_length=256)
    novaSenha: str = Field(min_length=6, max_length=256)


class AdminPasswordResetDefaultsRequest(BaseModel):
    excluirUsuario: str = Field(default="", max_length=120)
    exigirTrocaExcluido: bool = True


class AdminIndividualPasswordResetRequest(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)


class IndustryFirstAccessFinalizeRequest(BaseModel):
    token: str = Field(min_length=20, max_length=2048)


class IndustrySelectionRequest(BaseModel):
    laboratorio: str | None = None


class IndustryStockPermissionRequest(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    permitido: bool


class GranularPermissionChange(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    revisao: str = Field(min_length=64, max_length=64)
    permissoes: dict[str, bool] = Field(min_length=1, max_length=20)


# Somente chaves cuja autorização também é validada na API correspondente.
_POS_GRANULAR: dict[str, str] = {
    "POS_GERAL_VER_PROPRIA": "Visualizar apenas a própria carteira",
    "POS_GERAL_VER_TODOS": "Visualizar todas as carteiras",
    "POS_GERAL_ATUALIZAR": "Publicar atualizações da base",
    "POS_GERAL_META_ALTERAR": "Cadastrar ou alterar a meta",
    "POS_GERAL_OBSERVACOES_VER": "Consultar observações dos clientes autorizados",
    "POS_GERAL_OBSERVACOES_EDITAR": "Criar e editar observações autorizadas",
    "POS_GERAL_OBSERVACOES_GERAIS": "Consultar observações de toda a empresa",
    "POS_GERAL_INATIVIDADE_SOLICITAR": "Solicitar inatividade de cliente autorizado",
    "POS_GERAL_INATIVIDADE_APROVAR": "Consultar, aprovar ou rejeitar solicitações de inatividade",
    "POS_GERAL_EXPORTAR": "Exportar dados das carteiras autorizadas",
}
_GRANULAR_LOCK = asyncio.Lock()


def _granular_revision(row: dict[str, Any]) -> str:
    content = {"usuario": normalizar(row.get("usuario")), "tipo": str(row.get("tipo") or ""),
               "permissoes": _permission_map(row.get("permissoes"))}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


async def _granular_user(usuario: str) -> dict[str, Any]:
    raw = await _edge_admin_write("USUARIOS_LIST", {})
    matched = [u for u in _active_supabase_users(raw)
               if normalizar(u.get("usuario")) == normalizar(usuario)]
    if len(matched) != 1:
        raise HTTPException(status_code=404, detail="Usuário ativo não localizado no cadastro.")
    return matched[0]


@router.get("/admin/permissoes-detalhadas/catalogo")
async def granular_permissions_catalog(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _permission_view_profile(session)
    return {"sucesso": True, "grupos": [{"id": "POSITIVACAO_GERAL", "nome": "Positivação Geral",
        "itens": [{"chave": k, "nome": v} for k, v in _POS_GRANULAR.items()]}]}


@router.get("/admin/permissoes-detalhadas/usuario")
async def granular_permissions_user(usuario: str, session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _permission_view_profile(session)
    try:
        row = await _granular_user(usuario)
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raw = _permission_map(row.get("permissoes"))
    role = normalizar(row.get("tipo"))
    base_own = role in {"VENDEDOR", "TELEVENDAS"}
    defaults = {"POS_GERAL_VER_PROPRIA", "POS_GERAL_OBSERVACOES_VER",
                "POS_GERAL_OBSERVACOES_EDITAR", "POS_GERAL_INATIVIDADE_SOLICITAR",
                "POS_GERAL_EXPORTAR"}
    rights = {key: (True if _is_admin_profile(row) else
                    bool(raw[key]) if key in raw else base_own and key in defaults)
              for key in _POS_GRANULAR}
    return {"sucesso": True, "usuario": row["usuario"], "nome": row["nome"],
            "tipo": row["tipo"], "revisao": _granular_revision(row),
            "permissoes": rights, "administrador": _is_admin_profile(row)}


@router.post("/admin/permissoes-detalhadas/salvar")
async def granular_permissions_save(
    body: GranularPermissionChange,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    editor = _strict_admin_profile(session)  # Nunca permitir autoelevação por outro papel.
    if set(body.permissoes) != set(_POS_GRANULAR):
        raise HTTPException(status_code=400, detail="Lista de permissões incompleta ou desatualizada.")
    async with _GRANULAR_LOCK:
        try:
            row = await _granular_user(body.usuario)
            if _granular_revision(row) != body.revisao:
                raise HTTPException(status_code=409, detail="As permissões mudaram. Reabra o usuário antes de salvar.")
            if _is_admin_profile(row):
                raise HTTPException(status_code=403, detail="O perfil administrador tem direitos fixos; altere apenas usuários não administradores.")
            previous = _permission_map(row.get("permissoes"))
            updated = dict(previous)
            updated.update(body.permissoes)
            await _edge_admin_write("USUARIO_PERMISSOES_SET", {
                "usuario_norm": normalizar(row["usuario"]),
                "tipo": str(row["tipo"]), "permissoes": updated,
            })
            # Nunca confirmar sucesso sem reler a fonte de verdade.
            confirmed = await _granular_user(row["usuario"])
            actual = _permission_map(confirmed.get("permissoes"))
            if any(actual.get(key) is not allowed for key, allowed in body.permissoes.items()):
                raise HTTPException(status_code=503, detail=(
                    "O banco não confirmou as permissões selecionadas. Nenhuma liberação será presumida."
                ))
        except IndustryError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if normalizar(editor.get("usuario") or editor.get("sub")) == normalizar(row["usuario"]):
        refreshed = dict(editor)
        refreshed["permissoes"] = updated
        token = issue_session_token(
            usuario=str(editor.get("usuario") or editor.get("sub")), profile=refreshed,
            secret=settings.jwt_secret, issuer=settings.jwt_issuer,
            lifetime_seconds=settings.session_seconds,
        )
        response.set_cookie(key=settings.cookie_name, value=token,
            max_age=settings.session_seconds, httponly=True,
            secure=settings.cookie_secure, samesite=settings.cookie_samesite,
            domain=settings.cookie_domain, path="/")
    return {"sucesso": True, "usuario": row["usuario"], "mensagem":
            "Permissões da Positivação Geral atualizadas. As demais permissões foram preservadas."}


# Permissões efetivas: somente chaves cuja API já verifica o acesso.
# Não incluir funções inexistentes: opções sem validação no servidor seriam enganosas.
_ADVANCED_GROUPS: dict[str, dict[str, str]] = {
    "POSITIVACAO_GERAL": dict(_POS_GRANULAR),
    "MAPA_ESTOQUE": {
        "INDUSTRIA_PORTAL_INTERNO": "Acessar o portal interno de Indústrias e o Mapa de Estoque (novo login)",
        "INDUSTRIA_MAPA_ATUALIZAR": "Atualizar a base do Mapa (requer acesso ao portal e novo login)",
    },
}
_ADVANCED_NAMES = {"POSITIVACAO_GERAL": "Positivação Geral", "MAPA_ESTOQUE": "Mapa de Estoque / Indústrias"}
_ADVANCED_KEYS = {key for values in _ADVANCED_GROUPS.values() for key in values}


class AdvancedPermissionSave(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    revisao: str = Field(min_length=64, max_length=64)
    permissoes: dict[str, bool] = Field(min_length=1, max_length=20)


class AdvancedPermissionBatch(BaseModel):
    escopo: str = Field(min_length=5, max_length=30)
    usuarios: list[str] = Field(default_factory=list, max_length=100)
    grupo: str = Field(min_length=3, max_length=50)
    modo: str = Field(min_length=7, max_length=15)
    chaves: list[str] = Field(default_factory=list, max_length=20)


class AdvancedPermissionApply(AdvancedPermissionBatch):
    token: str = Field(min_length=64, max_length=64)
    expira_em: int


def _advanced_effective(row: dict[str, Any]) -> dict[str, bool]:
    raw = _permission_map(row.get("permissoes"))
    own_role = normalizar(row.get("tipo")) in {"VENDEDOR", "TELEVENDAS"}
    defaults = {"POS_GERAL_VER_PROPRIA", "POS_GERAL_OBSERVACOES_VER",
                "POS_GERAL_OBSERVACOES_EDITAR", "POS_GERAL_INATIVIDADE_SOLICITAR",
                "POS_GERAL_EXPORTAR"}
    return {key: (True if _is_admin_profile(row) else
                  raw.get(key) is True if key in raw else own_role and key in defaults)
            for key in _ADVANCED_KEYS}


def _advanced_targets(users: list[dict[str, Any]], body: AdvancedPermissionBatch) -> list[dict[str, Any]]:
    if body.grupo not in _ADVANCED_GROUPS or body.modo not in {"adicionar", "substituir"}:
        raise HTTPException(400, "Grupo ou modo inválido.")
    permitted = set(_ADVANCED_GROUPS[body.grupo])
    if len(body.chaves) != len(set(body.chaves)) or not set(body.chaves).issubset(permitted):
        raise HTTPException(400, "Há permissões inválidas ou duplicadas na seleção.")
    if body.modo == "adicionar" and not body.chaves:
        raise HTTPException(400, "Escolha ao menos uma permissão para adicionar.")
    scopes = {"vendedores": {"VENDEDOR"}, "televendas": {"TELEVENDAS"},
              "ambos": {"VENDEDOR", "TELEVENDAS"}, "selecionados": {"VENDEDOR", "TELEVENDAS"}}
    if body.escopo not in scopes:
        raise HTTPException(400, "Escopo de usuários inválido.")
    if body.escopo != "selecionados" and body.usuarios:
        raise HTTPException(400, "O escopo de todos não aceita uma lista individual.")
    requested = {normalizar(name) for name in body.usuarios}
    if body.escopo == "selecionados" and (not requested or len(requested) != len(body.usuarios)):
        raise HTTPException(400, "Escolha usuários distintos para a aplicação individual.")
    result = [u for u in users
              if normalizar(u.get("tipo")) in scopes[body.escopo]
              and not _is_admin_profile(u)
              and (body.escopo != "selecionados" or normalizar(u.get("usuario")) in requested)]
    if body.escopo == "selecionados" and {normalizar(u["usuario"]) for u in result} != requested:
        raise HTTPException(400, "Seleção contém usuário não localizado ou fora dos cargos permitidos.")
    if not result or len(result) > 100:
        raise HTTPException(400, "O grupo está vazio ou excede o limite de 100 funcionários por operação.")
    if len({normalizar(u["usuario"]) for u in result}) != len(result):
        raise HTTPException(409, "Cadastro possui logins duplicados; operação cancelada.")
    return sorted(result, key=lambda u: normalizar(u["usuario"]))


def _advanced_changes(row: dict[str, Any], body: AdvancedPermissionBatch) -> dict[str, bool]:
    raw = _permission_map(row.get("permissoes"))
    keys = set(body.chaves)
    if body.modo == "substituir":
        return {key: key in keys for key in _ADVANCED_GROUPS[body.grupo]}
    return {key: True for key in keys if raw.get(key) is not True}


def _advanced_check_dependencies(row: dict[str, Any], changes: dict[str, bool]) -> None:
    # A permissão de atualizar não substitui o direito de entrar no portal.
    related = {"INDUSTRIA_PORTAL_INTERNO", "INDUSTRIA_MAPA_ATUALIZAR"}
    if not related.intersection(changes):
        return
    current = _permission_map(row.get("permissoes"))
    current.update(changes)
    if (current.get("INDUSTRIA_MAPA_ATUALIZAR") is True
            and current.get("INDUSTRIA_PORTAL_INTERNO") is not True):
        raise HTTPException(400, "Para liberar atualização do Mapa, libere também o acesso ao portal Indústrias.")


def _advanced_signature(rows: list[dict[str, Any]], body: AdvancedPermissionBatch, expira_em: int) -> str:
    content = {"escopo": body.escopo, "usuarios": sorted(map(normalizar, body.usuarios)),
               "grupo": body.grupo, "modo": body.modo, "chaves": sorted(body.chaves),
               "expiraEm": expira_em,
               "revisoes": [(normalizar(r["usuario"]), _granular_revision(r)) for r in rows]}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


async def _advanced_roster() -> list[dict[str, Any]]:
    try:
        return _active_supabase_users(await _edge_admin_write("USUARIOS_LIST", {}))
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def _advanced_verify(usuario: str, expected: dict[str, Any], tipo: str) -> bool:
    roster = await _advanced_roster()
    rows = [u for u in roster if normalizar(u.get("usuario")) == normalizar(usuario)]
    if len(rows) != 1 or normalizar(rows[0].get("tipo")) != normalizar(tipo):
        return False
    # Comparar TODAS as chaves, não somente os checks enviados pela interface.
    return _permission_map(rows[0].get("permissoes")) == expected


def _advanced_invalidate_roster() -> None:
    # Invalidação imediata no processo corrente; outros processos conferem em até 30 s.
    from . import positivacao_geral
    positivacao_geral._ROSTER_AT = 0.0


@router.get("/admin/permissoes-avancadas/catalogo")
async def advanced_permissions_catalog(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _permission_view_profile(session)
    return {"sucesso": True, "grupos": [
        {"id": code, "nome": _ADVANCED_NAMES[code],
         "itens": [{"chave": key, "nome": label} for key, label in items.items()]}
        for code, items in _ADVANCED_GROUPS.items()
    ], "aviso": "Somente funções com validação específica no servidor são exibidas aqui."}


@router.get("/admin/permissoes-avancadas/usuarios")
async def advanced_permissions_users(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _strict_admin_profile(session)
    roster = await _advanced_roster()
    return {"sucesso": True, "usuarios": [
        {"usuario": u["usuario"], "nome": u["nome"], "tipo": u["tipo"]}
        for u in roster if normalizar(u.get("tipo")) in {"VENDEDOR", "TELEVENDAS"}
        and not _is_admin_profile(u)
    ]}


@router.get("/admin/permissoes-avancadas/usuario")
async def advanced_permissions_user(usuario: str, session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _permission_view_profile(session)
    row = await _granular_user(usuario)
    return {"sucesso": True, "usuario": row["usuario"], "nome": row["nome"],
            "tipo": row["tipo"], "revisao": _granular_revision(row),
            "administrador": _is_admin_profile(row), "permissoes": _advanced_effective(row)}


@router.post("/admin/permissoes-avancadas/salvar")
async def advanced_permissions_save(
    body: AdvancedPermissionSave,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _strict_admin_profile(session)
    if not set(body.permissoes).issubset(_ADVANCED_KEYS):
        raise HTTPException(400, "Uma das permissões não possui autorização no servidor.")
    async with _GRANULAR_LOCK:
        row = await _granular_user(body.usuario)
        if _is_admin_profile(row):
            raise HTTPException(403, "As permissões do administrador não podem ser alteradas aqui.")
        if _granular_revision(row) != body.revisao:
            raise HTTPException(409, "Cadastro alterado; reabra o usuário e tente novamente.")
        updated = dict(_permission_map(row.get("permissoes")))
        _advanced_check_dependencies(row, body.permissoes)
        updated.update(body.permissoes)
        try:
            await _edge_admin_write("USUARIO_PERMISSOES_SET", {
                "usuario_norm": normalizar(row["usuario"]), "tipo": str(row["tipo"]),
                "permissoes": updated,
            })
        except IndustryError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if not await _advanced_verify(row["usuario"], updated, str(row["tipo"])):
            raise HTTPException(503, "A gravação não foi confirmada no cadastro; não considere a permissão liberada.")
        _advanced_invalidate_roster()
    return {"sucesso": True, "usuario": row["usuario"], "mensagem": "Permissões salvas e conferidas no cadastro."}


@router.post("/admin/permissoes-avancadas/previa")
async def advanced_permissions_preview(
    body: AdvancedPermissionBatch,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _strict_admin_profile(session)
    rows = _advanced_targets(await _advanced_roster(), body)
    expira_em = int(time.time()) + 600
    changed = []
    for row in rows:
        actual = _advanced_effective(row)
        changes = _advanced_changes(row, body)
        _advanced_check_dependencies(row, changes)
        changed.append({"usuario": row["usuario"], "nome": row["nome"], "tipo": row["tipo"],
                        "revisao": _granular_revision(row),
                        "alteracoes": [{"chave": key, "antes": actual[key], "depois": value}
                                       for key, value in changes.items() if actual[key] != value]})
    return {"sucesso": True, "quantidade": len(rows),
            "usuarios": changed, "totalAlteracoes": sum(len(x["alteracoes"]) for x in changed),
            "token": _advanced_signature(rows, body, expira_em), "expiraEm": expira_em}


@router.post("/admin/permissoes-avancadas/aplicar")
async def advanced_permissions_apply(
    body: AdvancedPermissionApply,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    editor = _strict_admin_profile(session)
    if int(time.time()) > body.expira_em or body.expira_em > time.time() + 600:
        raise HTTPException(409, "Prévia expirada; gere uma nova antes de aplicar.")
    async with _GRANULAR_LOCK:
        current = await _advanced_roster()
        rows = _advanced_targets(current, body)
        if not hmac.compare_digest(_advanced_signature(rows, body, body.expira_em), body.token):
            raise HTTPException(409, "Cadastro ou seleção alterados; gere novamente a prévia.")
        confirmed: list[str] = []
        unchanged: list[str] = []
        for row in rows:
            actual = dict(_permission_map(row.get("permissoes")))
            changes = _advanced_changes(row, body)
            _advanced_check_dependencies(row, changes)
            next_map = dict(actual)
            next_map.update(changes)
            if next_map == actual:
                unchanged.append(row["usuario"])
                continue
            try:
                await _edge_admin_write("USUARIO_PERMISSOES_SET", {
                    "usuario_norm": normalizar(row["usuario"]), "tipo": str(row["tipo"]),
                    "permissoes": next_map,
                })
                if not await _advanced_verify(row["usuario"], next_map, str(row["tipo"])):
                    raise RuntimeError("O cadastro não confirmou a gravação.")
            except Exception as exc:
                _advanced_invalidate_roster()
                # Operação não é uma transação única: explicitar sucesso parcial;
                # nunca informar sucesso global quando houve erro em um destinatário.
                raise HTTPException(503, detail={
                    "mensagem": f"Aplicação interrompida: {len(confirmed)} usuários confirmados; "
                                "um registro falhou ou não pôde ser confirmado. Gere uma nova prévia para os restantes.",
                    "confirmados": confirmed, "semAlteracao": unchanged,
                    "falhouEm": row["usuario"], "motivo": str(exc)[:160],
                }) from exc
            confirmed.append(row["usuario"])
        _advanced_invalidate_roster()
    return {"sucesso": True, "quantidade": len(rows), "alterados": len(confirmed),
            "semAlteracao": len(unchanged), "usuariosConfirmados": confirmed,
            "mensagem": "Permissões persistidas e verificadas para todos os usuários selecionados."}


class IndustryOperatorPermissionsRequest(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    tipo: str = Field(min_length=1, max_length=80)
    permissoesGerenciadas: list[str] = Field(default_factory=list, max_length=200)
    permissoesSelecionadas: list[str] = Field(default_factory=list, max_length=200)


class IndustryBuyerPromoteRequest(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)


class IndustryBuyerCreateRequest(BaseModel):
    usuario: str = Field(min_length=2, max_length=120)
    nome: str = Field(default="", max_length=160)


class AdminUserCreateRequest(BaseModel):
    usuario: str = Field(min_length=2, max_length=120)
    tipo: str = Field(min_length=2, max_length=80)
    nome: str = Field(default="", max_length=160)
    vendedor: str = Field(default="", max_length=160)


class IndustryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.data = data or {}


def _role(profile: dict[str, Any]) -> str:
    return normalizar(profile.get("tipo") or "")


def is_industry_profile(profile: dict[str, Any] | None) -> bool:
    profile = profile or {}
    if _role(profile) == ROLE_INDUSTRY:
        return True
    # Compatibilidade apenas para representantes antigos: PERM_PORTAL sozinho
    # não transforma usuário interno em representante. É necessário também
    # existir ao menos um laboratório vinculado.
    perms = profile.get("permissoes")
    if not isinstance(perms, dict) or perms.get(PERM_PORTAL) is not True:
        return False
    raw_labs = perms.get(PERM_LABS)
    if isinstance(raw_labs, list):
        return any(str(x or "").strip() for x in raw_labs)
    if isinstance(raw_labs, str):
        return bool(raw_labs.strip())
    return False


def _permissions(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("permissoes")
    return value if isinstance(value, dict) else {}


def is_buyer_profile(profile: dict[str, Any] | None) -> bool:
    profile = profile or {}
    return _role(profile) == ROLE_BUYER


def _buyer_all_labs(profile: dict[str, Any]) -> bool:
    return (
        is_buyer_profile(profile)
        and _permissions(profile).get(PERM_INTERNAL_PORTAL) is True
        and _permissions(profile).get(PERM_BUYER_ALL_LABS) is True
    )


def _can_view_all_labs(profile: dict[str, Any]) -> bool:
    # O usuário interno com acesso a todos os laboratórios individuais
    # também pode solicitar a visão consolidada.
    # Compradores mantêm a permissão específica já exigida anteriormente;
    # representantes externos continuam restritos à própria indústria.
    return _buyer_all_labs(profile) or (
        not is_buyer_profile(profile)
        and _is_internal_industry_viewer(profile)
    )


def _is_all_labs_request(value: Any) -> bool:
    text = str(value or "").strip()
    return text == ALL_LABS_VALUE or normalizar(text) == normalizar(ALL_LABS_LABEL)


def industry_must_change_password(profile: dict[str, Any]) -> bool:
    return _permissions(profile).get(PERM_FIRST_ACCESS) is True


def _clean_lab(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s*-\s*Prod\.?\s*Foco(?:\s*\([^)]*\))?\s*$", "", text, flags=re.I)
    return text.strip()


def _lab_key(value: Any) -> str:
    return normalizar(_clean_lab(value))


# Somente no portal Industrias, os dois fornecedores NEO QUIMICA formam um
# laboratorio virtual. As permissoes e os nomes gravados nas fontes originais
# permanecem intactos; nenhuma outra marca recebe tratamento especial.
_NEO_PORTAL_LAB = "NEO QUIMICA"
_NEO_SOURCE_KEYS = frozenset({"NEO QUIMICA", "NEO QUIMICA GENERICO", "NEO QUIMICA GENERICOS", "NEO QUIMICA SMART"})


def _portal_lab_key(value: Any) -> str:
    key = _lab_key(value)
    return _NEO_PORTAL_LAB if key in _NEO_SOURCE_KEYS else key


def _portal_lab_label(value: Any) -> str:
    return _NEO_PORTAL_LAB if _portal_lab_key(value) == _NEO_PORTAL_LAB else _clean_lab(value)


def _portal_source_keys(value: Any) -> set[str]:
    return set(_NEO_SOURCE_KEYS) if _portal_lab_key(value) == _NEO_PORTAL_LAB else {_lab_key(value)}


def _portal_labs(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _portal_lab_label(value)
        key = _portal_lab_key(label)
        if label and key not in seen:
            seen.add(key)
            result.append(label)
    return result


def industry_allowed_labs(profile: dict[str, Any]) -> list[str]:
    perms = _permissions(profile)
    raw = perms.get(PERM_LABS)
    values: list[Any] = []
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        values = re.split(r"[,;|]", raw)

    labs: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _clean_lab(value)
        key = _lab_key(label)
        if label and key and key not in seen:
            seen.add(key)
            labs.append(label)

    # Compatibilidade defensiva: se algum usuário antigo da indústria tiver
    # sido cadastrado usando SETOR como laboratório, ainda o reconhecemos.
    if not labs and is_industry_profile(profile):
        setor = str(profile.get("setor") or "").strip()
        setor = re.sub(r"^INDUSTRIA\s*[:|\-]\s*", "", setor, flags=re.I)
        if setor and normalizar(setor) != "INDUSTRIA":
            labs = [setor]
    return labs


def _session_profile(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=401, detail="Sessão ausente.")
    try:
        return decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida.") from exc


def _is_internal_industry_viewer(profile: dict[str, Any]) -> bool:
    # Usuário interno permanece no DISMEPE ONE principal e só entra no portal
    # de indústrias quando recebe esta permissão explícita.
    return (
        _role(profile) != ROLE_INDUSTRY
        and _permissions(profile).get(PERM_INTERNAL_PORTAL) is True
    )


async def _merge_live_internal_permissions(profile: dict[str, Any]) -> dict[str, Any]:
    """Compatibilidade PROD5.9.3.

    Não existe snapshot USUARIOS no PostgreSQL. As permissões atuais do usuário
    vêm do JWT principal e, quando o próprio usuário altera suas permissões, o
    endpoint administrativo reemite o cookie com o novo mapa imediatamente.
    """
    return profile


async def _industry_profile(session: str | None, *, require_password_changed: bool = False) -> dict[str, Any]:
    profile = _session_profile(session)

    # Representantes externos continuam com o mesmo isolamento por laboratório.
    if is_industry_profile(profile):
        if _permissions(profile).get(PERM_PORTAL) is not True:
            raise HTTPException(status_code=403, detail="Portal da indústria não liberado para este usuário.")
        if not industry_allowed_labs(profile):
            raise HTTPException(status_code=403, detail="Nenhum laboratório foi vinculado a este usuário.")
        if require_password_changed and industry_must_change_password(profile):
            raise HTTPException(
                status_code=428,
                detail={
                    "codigo": "INDUSTRIA_TROCAR_SENHA",
                    "mensagem": "Troque a senha temporária antes de acessar os dados da indústria.",
                },
            )
        return profile

    # Para usuário interno, a fonte atual de permissões prevalece sobre o JWT.
    profile = await _merge_live_internal_permissions(profile)
    if _is_internal_industry_viewer(profile):
        return profile

    raise HTTPException(status_code=403, detail="Você não possui permissão para acessar o DISMEPE ONE INDÚSTRIAS.")


def _is_admin_profile(profile: dict[str, Any]) -> bool:
    return _role(profile) in {"ADMINISTRADOR", "ADMIN"}


def _strict_admin_profile(session: str | None) -> dict[str, Any]:
    profile = _session_profile(session)
    if not _is_admin_profile(profile):
        raise HTTPException(status_code=403, detail="Ação exclusiva para administrador.")
    return profile


def _admin_profile(session: str | None) -> dict[str, Any]:
    # Mantém a regra já existente para criação de usuários da indústria.
    profile = _session_profile(session)
    perms = _permissions(profile)
    if not _is_admin_profile(profile) and perms.get("USUARIOS_CRIAR") is not True:
        raise HTTPException(status_code=403, detail="Você não possui permissão para criar usuários da indústria.")
    return profile


def _permission_view_profile(session: str | None) -> dict[str, Any]:
    profile = _session_profile(session)
    perms = _permissions(profile)
    if not (
        _is_admin_profile(profile)
        or perms.get("PERMISSOES_VISUALIZAR") is True
        or perms.get("PERMISSOES_ALTERAR") is True
    ):
        raise HTTPException(status_code=403, detail="Você não possui permissão para visualizar permissões.")
    return profile


def _permission_edit_profile(session: str | None) -> dict[str, Any]:
    profile = _session_profile(session)
    perms = _permissions(profile)
    if not (_is_admin_profile(profile) or perms.get("PERMISSOES_ALTERAR") is True):
        raise HTTPException(status_code=403, detail="Você não possui permissão para alterar permissões.")
    return profile


async def _stock_update_profile(session: str | None) -> dict[str, Any]:
    # A permissão do mapa é independente de criação de usuários.
    # Administrador mantém acesso por padrão; demais usuários precisam da permissão explícita.
    profile = _session_profile(session)
    if _is_admin_profile(profile):
        return profile
    profile = await _merge_live_internal_permissions(profile)
    if _permissions(profile).get(PERM_STOCK_UPDATE) is True:
        return profile
    raise HTTPException(
        status_code=403,
        detail="Você não possui permissão para atualizar o mapa de estoque.",
    )


def _permission_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {str(key): True for key in value if str(key).strip()}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None and parsed is not value:
            return _permission_map(parsed)
        # Compatibilidade defensiva com snapshots antigos que serializavam
        # somente as chaves em texto separadas por vírgula/ponto e vírgula.
        keys = [x.strip() for x in re.split(r"[,;|]", text) if x.strip()]
        if keys and all(re.fullmatch(r"[A-Za-z0-9_\-]{2,120}", x) for x in keys):
            return {x: True for x in keys}
    return {}


def _snapshot_users(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("usuarios", "dados", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _choose_lab(profile: dict[str, Any], requested: str | None) -> str:
    # Consolidado global: somente para perfis internos autorizados a
    # visualizar todos os laboratórios, sem abrir acesso a representantes.
    if _is_all_labs_request(requested):
        if _can_view_all_labs(profile):
            return ALL_LABS_VALUE
        raise HTTPException(
            status_code=403,
            detail="Você não possui permissão para visualizar todos os laboratórios.",
        )

    # Usuário interno autorizado pode selecionar qualquer laboratório individual.
    if _is_internal_industry_viewer(profile):
        label = _clean_lab(requested)
        if not label:
            raise HTTPException(status_code=400, detail="Selecione um laboratório.")
        return _portal_lab_label(label)

    allowed = industry_allowed_labs(profile)
    if not allowed:
        raise HTTPException(status_code=403, detail="Nenhum laboratório foi vinculado a este usuário.")
    if not requested:
        return _portal_lab_label(allowed[0])
    key = _portal_lab_key(requested)
    for label in allowed:
        if _portal_lab_key(label) == key:
            return _portal_lab_label(label)
    raise HTTPException(status_code=403, detail="Laboratório não autorizado para este usuário.")


def _row_lab(row: dict[str, Any]) -> str:
    for key in (
        "__LAB", "lab", "Laboratório", "Laboratorio", "LABORATORIO", "FORNECEDOR",
        "fornecedor", "Fornecedor",
    ):
        value = row.get(key)
        if value is not None and str(value).strip():
            return _clean_lab(value)
    return ""


def _row_collaborator(row: dict[str, Any], channel: str) -> str:
    keys = (
        ("__COLABORADOR", "colab", "Televendas", "televendas", "TELEVENDAS")
        if channel == "TELEVENDAS"
        else ("__COLABORADOR", "colab", "Vendedor", "vendedor", "VENDEDOR")
    )
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return 0.0
    # Formatos brasileiros: 1.234,56 / 1.234 / 12,50
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _int(value: Any) -> int:
    return int(round(_num(value)))


def _row_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return None


def _row_competence(row: dict[str, Any]) -> str:
    raw = _row_value(row, ("__COMPETENCIA", "competencia", "Competencia", "Competência"))
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{2}/\d{4}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text[5:7] + "/" + text[:4]
    if re.fullmatch(r"\d{2}-\d{4}", text):
        return text[:2] + "/" + text[3:]
    return text


def _comp_order(comp: str) -> int:
    try:
        mm, yyyy = comp.split("/")
        return int(yyyy) * 100 + int(mm)
    except Exception:
        return 0


def _all_competences(payload: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in payload.get("competenciasDisponiveis") or payload.get("competencias") or []:
        if isinstance(item, dict):
            raw = item.get("competencia") or item.get("COMPETENCIA") or ""
        else:
            raw = item
        comp = _row_competence({"competencia": raw})
        if comp:
            values.append(comp)
    for row in rows:
        comp = _row_competence(row)
        if comp:
            values.append(comp)
    values = list(dict.fromkeys(values))
    values.sort(key=_comp_order, reverse=True)
    return values


def _is_focus_row(row: dict[str, Any]) -> bool:
    if row.get("__TEM_FOCO") is True:
        return True
    tipo = normalizar(row.get("tipoRegistro") or row.get("TIPO_REGISTRO") or "")
    if tipo == "PRODUTO_FOCO":
        return True
    raw_lab = str(_row_value(row, ("__LAB", "lab", "Laboratório", "Laboratorio", "LABORATORIO", "FORNECEDOR")) or "")
    return bool(re.search(r"Prod\.?\s*Foco", raw_lab, flags=re.I))


def _globo_individual_from_partial(row: dict[str, Any]) -> dict[str, Any] | None:
    """Retorna somente POSITIVACAO_CLIENTES ja calculada no snapshot mensal.

    Nao recalcula clientes, metas ou premios e nao envia outras metricas.
    """
    partial = row.get("metricasParcial")
    components = partial.get("componentes") if isinstance(partial, dict) else None
    if not isinstance(components, list):
        return None
    for item in components:
        if isinstance(item, dict) and item.get("metrica") == "POSITIVACAO_CLIENTES":
            return {
                "realizado": item.get("realizado"),
                "meta": item.get("meta"),
                "premio": item.get("premio"),
                "pendente": bool(item.get("pendente")),
                "motivo": str(item.get("motivo") or "")[:180],
            }
    return None


def _sanitize_sales_row(row: dict[str, Any], channel: str, days: float) -> dict[str, Any]:
    foco = _is_focus_row(row)
    objetivo = _num(_row_value(row, ("__OBJETIVO", "objetivo", "Objetivo", "Meta", "meta", "META", "OBJETIVO")))
    venda = _num(_row_value(row, ("__VENDA", "venda", "Venda", "Vendas", "Realizado", "REALIZADO", "Faturamento", "FATURAMENTO", "VENDA")))
    objetivo_foco = _num(_row_value(row, ("__OBJETIVO_FOCO", "objetivoFoco", "OBJETIVO_FOCO")))
    venda_foco = _num(_row_value(row, ("__VENDA_FOCO", "vendaFoco", "VENDA_FOCO")))

    # A tela original apresenta Produto Foco em unidades. Dependendo da versão
    # do snapshot, essas quantidades podem estar nos campos dedicados ou nos
    # campos objetivo/venda da própria linha de foco.
    display_obj = (objetivo_foco if objetivo_foco > 0 else objetivo) if foco else objetivo
    display_sale = (venda_foco if (venda_foco != 0 or objetivo_foco > 0) else venda) if foco else venda
    ating_display = (display_sale / display_obj * 100.0) if display_obj > 0 else None
    falta_display = max(0.0, display_obj - display_sale)
    vender_dia_display = (falta_display / days) if days > 0 else None

    ating = (venda / objetivo * 100.0) if objetivo > 0 else None
    falta = max(0.0, objetivo - venda)
    vender_dia = (falta / days) if days > 0 else None

    if ating_display is None:
        status = "—"
    elif ating_display >= 100:
        status = "Meta Atingida"
    elif ating_display >= 50:
        status = "Em Progresso"
    else:
        status = "Abaixo da Meta"

    return {
        "canal": channel,
        "colaborador": _row_collaborator(row, channel),
        "laboratorio": _row_lab(row),
        "competencia": _row_competence(row),
        "objetivo": round(objetivo, 2),
        "venda": round(venda, 2),
        "atingimento": round(ating, 2) if ating is not None else None,
        "falta": round(falta, 2),
        "venderPorDia": round(vender_dia, 2) if vender_dia is not None else None,
        "produtoFoco": str(_row_value(row, ("produtoFoco", "produtoFocoCampanha", "Produto", "PRODUTO", "__PRODUTO_FOCO")) or "").strip(),
        "codigoProdutoFoco": str(_row_value(row, ("__CODIGO_FOCO", "codigoProdutoFoco", "CODIGO_PRODUTO_FOCO")) or "").strip(),
        "objetivoFoco": round(objetivo_foco, 2),
        "vendaFoco": round(venda_foco, 2),
        "observacaoProdutoFoco": str(_row_value(row, ("observacaoProdutoFoco", "OBSERVACAO_PRODUTO_FOCO")) or "").strip(),
        "observacoes": str(_row_value(row, ("observacoes", "OBSERVACOES", "Observação", "Observacao")) or "").strip(),
        "foco": foco,
        "objetivoExibicao": round(display_obj, 2),
        "vendaExibicao": round(display_sale, 2),
        "venderPorDiaExibicao": round(vender_dia_display, 2) if vender_dia_display is not None else None,
        "atingimentoExibicao": round(ating_display, 2) if ating_display is not None else None,
        "status": status,
        "unidadeExibicao": "UN" if foco else "BRL",
    }


def _merge_neo_sales_rows(rows: list[dict[str, Any]], days: float) -> list[dict[str, Any]]:
    """Somente a exibicao do portal: soma Genericos + Smart por profissional.

    Nao altera o snapshot, nao soma metas de Produto Foco e nao modifica
    as regras de premio da parcial original.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        owner = " ".join(normalizar(row.get("colaborador") or "").split())
        key = owner if owner else f"SEM_NOME_{len(grouped)}"
        if key not in grouped:
            grouped[key] = dict(row)
            grouped[key]["laboratorio"] = _NEO_PORTAL_LAB
            continue
        target = grouped[key]
        for field in ("objetivo", "venda", "objetivoExibicao", "vendaExibicao"):
            target[field] = round(_num(target.get(field)) + _num(row.get(field)), 2)
    for row in grouped.values():
        goal = _num(row.get("objetivo"))
        sale = _num(row.get("venda"))
        display_goal = _num(row.get("objetivoExibicao"))
        display_sale = _num(row.get("vendaExibicao"))
        pct = display_sale / display_goal * 100 if display_goal > 0 else None
        row["atingimento"] = round(sale / goal * 100, 2) if goal > 0 else None
        row["falta"] = round(max(0, goal - sale), 2)
        row["venderPorDia"] = round(row["falta"] / days, 2) if days > 0 else None
        row["atingimentoExibicao"] = round(pct, 2) if pct is not None else None
        row["venderPorDiaExibicao"] = round(max(0, display_goal - display_sale) / days, 2) if days > 0 else None
        row["status"] = "—" if pct is None else "Meta Atingida" if pct >= 100 else "Em Progresso" if pct >= 50 else "Abaixo da Meta"
    return list(grouped.values())


def _days_remaining(payload: dict[str, Any], comp: str) -> float:
    days_map = payload.get("diasUteisPorCompetencia")
    if isinstance(days_map, dict):
        value = _num(days_map.get(comp))
        if value > 0:
            return value
    campaign = payload.get("campanhaMensalAtual")
    if isinstance(campaign, dict):
        value = _num(campaign.get("diasUteisRestantes"))
        if value > 0:
            return value
    return 0.0


def _filter_lab_rows(rows: list[Any], allowed_lab_keys: set[str], comp: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _lab_key(_row_lab(row)) not in allowed_lab_keys:
            continue
        if comp and _row_competence(row) != comp:
            continue
        out.append(row)
    return out


def _rule_active(row: dict[str, Any]) -> bool:
    value = row.get("ativo", row.get("ATIVO", True))
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return True
    return normalizar(value) not in {"FALSE", "FALSO", "NAO", "N", "0", "INATIVO"}


def _rule_competence(row: dict[str, Any]) -> str:
    return _row_competence({
        "competencia": row.get("competencia") or row.get("COMPETENCIA") or ""
    })


def _rule_lab(row: dict[str, Any]) -> str:
    return _clean_lab(
        row.get("laboratorio")
        or row.get("Laboratório")
        or row.get("Laboratorio")
        or row.get("LABORATORIO")
        or row.get("lab")
        or ""
    )


def _campaign_metric_title(value: Any) -> str:
    key = normalizar(value)
    labels = {
        "FATURAMENTO": "Faturamento",
        "FATURAMENTO_LABORATORIO": "Faturamento geral do laboratório",
        "POSITIVACAO_CLIENTES": "Clientes positivados",
        "POSITIVACAO_GERAL": "Positivação geral",
        "PONTUACAO_PRODUTO": "Pontuação por produto",
        "METRICA_COMPOSTA": "Métrica composta",
    }
    return labels.get(key, str(value or "Métrica").replace("_", " ").title())


def _sanitize_campaign_rule(row: dict[str, Any]) -> dict[str, Any]:
    metric = str(row.get("metrica") or row.get("METRICA") or "").strip()
    tipo = str(row.get("tipo") or row.get("TIPO") or "").strip()
    canal = str(row.get("canal") or row.get("CANAL") or "TODOS").strip() or "TODOS"
    valor = row.get("valor") if row.get("valor") is not None else row.get("VALOR")
    criterio = str(row.get("criterio") or row.get("CRITERIO") or "").strip()
    observacao = str(row.get("observacao") or row.get("OBSERVACAO") or "").strip()
    faixas = row.get("faixas") if row.get("faixas") is not None else row.get("FAIXAS")
    if isinstance(faixas, str):
        try:
            parsed = json.loads(faixas)
            faixas = parsed if isinstance(parsed, list) else []
        except Exception:
            faixas = []
    if not isinstance(faixas, list):
        faixas = []
    safe_faixas = []
    for item in faixas[:30]:
        if not isinstance(item, dict):
            continue
        safe_faixas.append({
            "minimo": item.get("minimo", item.get("pontos")),
            "pontos": item.get("pontos"),
            "premio": item.get("premio"),
        })
    return {
        "competencia": _rule_competence(row),
        "laboratorio": _rule_lab(row),
        "canal": canal,
        "metrica": metric,
        "titulo": _campaign_metric_title(metric),
        "tipo": tipo,
        "valor": valor,
        "criterio": criterio,
        "observacao": observacao,
        "faixas": safe_faixas,
        "exigeSomaLaboratorio": row.get("exigeSomaLaboratorio") is True,
        "somaLabMinimo": row.get("somaLabMinimo"),
    }


def _industry_campaign_metrics(payload: dict[str, Any], lab: str, comp: str) -> list[dict[str, Any]]:
    rules = payload.get("regrasPremiacao") if isinstance(payload.get("regrasPremiacao"), list) else []
    lab_keys = _portal_source_keys(lab)
    out: list[dict[str, Any]] = []
    for row in rules:
        if not isinstance(row, dict) or not _rule_active(row):
            continue

        # No portal Indústrias mostramos somente a campanha normal do laboratório.
        metric_key = normalizar(row.get("metrica") or row.get("METRICA") or "")
        focus_text = normalizar(" ".join(str(row.get(k) or "") for k in (
            "metrica", "METRICA", "tipo", "TIPO", "criterio", "CRITERIO",
            "observacao", "OBSERVACAO", "produtoFoco", "PRODUTO_FOCO",
        )))
        if metric_key == "PONTUACAO_PRODUTO" or "PRODUTO FOCO" in focus_text:
            continue

        if _lab_key(_rule_lab(row)) not in lab_keys:
            continue
        rule_comp = _rule_competence(row)
        if comp and rule_comp != comp:
            continue
        out.append(_sanitize_campaign_rule(row))
    return out


def scope_industry_bootstrap(payload: dict[str, Any], profile: dict[str, Any], competencia: str | None = None) -> dict[str, Any]:
    """Escopo seguro usado pelo próprio /auth/login e /data/bootstrap.

    Impede que o bootstrap normal da aplicação devolva laboratórios não
    autorizados antes do redirecionamento para DISMEPE ONE INDÚSTRIAS.
    """
    allowed = industry_allowed_labs(profile)
    allowed_keys = {key for lab in allowed for key in _portal_source_keys(lab)}
    vend_all = payload.get("dadosVendedores") if isinstance(payload.get("dadosVendedores"), list) else []
    tlv_all = payload.get("dadosTelevendas") if isinstance(payload.get("dadosTelevendas"), list) else []
    all_rows = [x for x in vend_all + tlv_all if isinstance(x, dict)]
    comps = _all_competences(payload, all_rows)
    comp = str(competencia or "").strip() or (comps[0] if comps else "")
    if industry_must_change_password(profile):
        vend: list[dict[str, Any]] = []
        tlv: list[dict[str, Any]] = []
    else:
        vend = [row for row in _filter_lab_rows(vend_all, allowed_keys, comp or None) if not _is_focus_row(row)]
        tlv = [row for row in _filter_lab_rows(tlv_all, allowed_keys, comp or None) if not _is_focus_row(row)]
    return {
        "sucesso": True,
        "banco": "SUPABASE",
        "fonteDados": "POSTGRESQL",
        "transporte": "FASTAPI_INDUSTRIA_SCOPE",
        "usuario": {
            "usuario": str(profile.get("usuario") or ""),
            "nome": str(profile.get("nome") or ""),
            "vendedor": str(profile.get("vendedor") or ""),
            "tipo": str(profile.get("tipo") or ""),
            "setor": str(profile.get("setor") or ""),
        },
        "permissoes": dict(_permissions(profile)),
        "competenciaPrincipal": comp,
        "competenciasAtivas": [comp] if comp else [],
        "competenciasSelecionadas": [comp] if comp else [],
        "competenciasDisponiveis": comps,
        "competencias": comps,
        "dadosVendedores": vend,
        "dadosTelevendas": tlv,
        "regrasPremiacao": [],
        "diasUteisRestantes": _days_remaining(payload, comp),
        "industria": True,
        "laboratoriosAutorizados": _portal_labs(allowed),
        "primeiroAcesso": industry_must_change_password(profile),
    }



async def _revoke_industry_passkeys(usuario: str) -> None:
    """Revoga chaves anteriores ao redefinir a senha de uma conta INDUSTRIA.

    O token interno permanece no backend e a resposta não expõe chaves públicas.
    """
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-passkeys"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                endpoint,
                json={"acao": "CREDENTIAL_REVOKE_ALL", "usuario": usuario},
                headers=headers,
            )
            result = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Nao foi possivel revogar as chaves biometricas antigas. A senha nao sera alterada por este fluxo.") from exc
    if not resp.is_success or not isinstance(result, dict) or result.get("sucesso") is not True:
        raise HTTPException(503, "Nao foi possivel revogar as chaves biometricas antigas. Tente novamente antes de alterar a senha.")


async def _edge_admin_write(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Uma única escrita por ação. Não repete automaticamente gravações."""
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    body = {"acao": action, **payload}
    try:
        async with httpx.AsyncClient(timeout=max(10.0, settings.request_timeout_seconds)) as client:
            response = await client.post(endpoint, json=body, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise IndustryError(
            "O serviço de usuários não respondeu dentro do tempo esperado.",
            status_code=503,
        ) from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise IndustryError(
            f"O serviço de usuários respondeu em formato inválido (HTTP {response.status_code}).",
            status_code=502,
        ) from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise IndustryError(
            str(data.get("erro") or data.get("error") or f"HTTP {response.status_code}"),
            status_code=response.status_code if response.status_code in {400, 401, 403, 404, 409, 422} else 502,
            data=data,
        )
    if data.get("sucesso") is not True and data.get("success") is not True and data.get("ok") is not True:
        raise IndustryError(
            str(data.get("erro") or data.get("error") or "A operação não foi confirmada pelo serviço de usuários."),
            status_code=400,
            data=data,
        )
    return data


# PROD5.9.8.11 — usuários internos usam o mesmo fluxo pós-migração
# do DISMEPE ONE INDÚSTRIAS.
_INTERNAL_ROLE_DEFAULT_PERMISSIONS: dict[str, dict[str, Any]] = {
    "ADMINISTRADOR": {},
    "COMERCIAL": {
        "VENDEDORES": True,
        "TELEVENDAS": True,
        "VISAO_GERAL": True,
        "FILTRO_VENDEDORES": True,
        "FILTRO_TELEVENDAS": True,
        "RESUMO_PREMIACOES": True,
        "CAMPANHAS_EXTRAS_VISUALIZAR": True,
        "CAMPANHAS_MENSAIS_VISUALIZAR": True,
        "HISTORICO_MENSAL_VISUALIZAR": True,
        "HISTORICO_EXTRAS_VISUALIZAR": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "GERENTE DE VENDAS": {
        "VENDEDORES": True,
        "TELEVENDAS": True,
        "VISAO_GERAL": True,
        "FILTRO_VENDEDORES": True,
        "FILTRO_TELEVENDAS": True,
        "RESUMO_PREMIACOES": True,
        "CAMPANHAS_EXTRAS_VISUALIZAR": True,
        "CAMPANHAS_MENSAIS_VISUALIZAR": True,
        "HISTORICO_MENSAL_VISUALIZAR": True,
        "HISTORICO_EXTRAS_VISUALIZAR": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "DIRETOR": {
        "VENDEDORES": True,
        "TELEVENDAS": True,
        "VISAO_GERAL": True,
        "FILTRO_VENDEDORES": True,
        "FILTRO_TELEVENDAS": True,
        "RESUMO_PREMIACOES": True,
        "CAMPANHAS_EXTRAS_VISUALIZAR": True,
        "CAMPANHAS_MENSAIS_VISUALIZAR": True,
        "HISTORICO_MENSAL_VISUALIZAR": True,
        "HISTORICO_EXTRAS_VISUALIZAR": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "VENDEDOR": {
        "VENDEDORES": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "TELEVENDAS": {
        "TELEVENDAS": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "SUP VENDAS": {
        "VENDEDORES": True,
        "FILTRO_VENDEDORES": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "SUP TELEVENDAS": {
        "TELEVENDAS": True,
        "FILTRO_TELEVENDAS": True,
        "CONFIGURACAO": True,
        "ALTERAR_SENHA": True,
    },
    "CONTAS A PAGAR": {
        "RESUMO_PREMIACOES": True,
        "PREMIACOES_VISUALIZAR": True,
        "PREMIACOES_HISTORICO": True,
        "NOTIFICACOES_VISUALIZAR": True,
        "NOTIFICACOES_MARCAR_LIDA": True,
        "ALTERAR_SENHA": True,
    },
    ROLE_BUYER: {
        PERM_INTERNAL_PORTAL: True,
        PERM_BUYER_ALL_LABS: True,
        PERM_STOCK_UPDATE: False,
    },
}


def _canonical_internal_role(value: Any) -> str:
    role = normalizar(value or "")
    aliases = {
        "ADMIN": "ADMINISTRADOR",
        "GESTOR": "COMERCIAL",
        "FINANCEIRO": "CONTAS A PAGAR",
        "FINANCAS": "CONTAS A PAGAR",
        "CONTAS PAGAR": "CONTAS A PAGAR",
        "SUPERVISOR VENDAS": "SUP VENDAS",
        "SUPERVISOR_VENDAS": "SUP VENDAS",
        "SUPERVISOR TELEVENDAS": "SUP TELEVENDAS",
        "SUPERVISOR_TELEVENDAS": "SUP TELEVENDAS",
        "GERENTE VENDAS": "GERENTE DE VENDAS",
        "GERENTE COMERCIAL": "GERENTE DE VENDAS",
    }
    role = aliases.get(role, role)

    if role == ROLE_INDUSTRY:
        raise HTTPException(
            status_code=400,
            detail=(
                "Usuários do tipo INDÚSTRIA devem ser criados pela área "
                "DISMEPE ONE INDÚSTRIAS, com os laboratórios vinculados."
            ),
        )
    if role not in _INTERNAL_ROLE_DEFAULT_PERMISSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Cargo não suportado para criação: {role or 'VAZIO'}.",
        )
    return role


def _internal_role_permissions(role: str) -> dict[str, Any]:
    return dict(_INTERNAL_ROLE_DEFAULT_PERMISSIONS.get(role) or {})


def _active_supabase_users(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = result.get("usuarios")
    if not isinstance(raw, list):
        return []

    users: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        usuario = str(item.get("usuario") or "").strip()
        if not usuario:
            continue

        if normalizar(item.get("tipo") or "") == ROLE_INDUSTRY:
            continue

        status = normalizar(item.get("status") or "")
        if item.get("ativo") is False or status in {"EXCLUIDO", "INATIVO"}:
            continue

        users.append({
            "usuario": usuario,
            "usuario_norm": str(item.get("usuario_norm") or normalizar(usuario)),
            "nome": str(item.get("nome") or item.get("vendedor") or usuario).strip(),
            "vendedor": str(item.get("vendedor") or item.get("nome") or usuario).strip(),
            "tipo": str(item.get("tipo") or "").strip(),
            "setor": str(item.get("setor") or "").strip(),
            "ativo": item.get("ativo") is not False,
            "status": str(item.get("status") or "ATIVO").strip() or "ATIVO",
            "permissoes": _permission_map(item.get("permissoes")),
        })

    users.sort(key=lambda item: normalizar(item.get("nome") or item.get("usuario") or ""))
    return users


@router.get("/admin/users")
async def admin_users_list(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _permission_view_profile(session)
    try:
        result = await _edge_admin_write("USUARIOS_LIST", {})
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    users = _active_supabase_users(result)
    return {
        "sucesso": True,
        "origem": "SUPABASE",
        "transporte": "FASTAPI_USUARIOS_LIST",
        "usuarios": users,
        "quantidade": len(users),
    }


@router.post("/admin/users")
async def admin_create_user(
    payload: AdminUserCreateRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_profile(session)

    usuario = str(payload.usuario or "").strip()
    if not usuario:
        raise HTTPException(status_code=400, detail="Usuário inválido.")

    role = _canonical_internal_role(payload.tipo)
    nome = str(payload.nome or payload.vendedor or usuario).strip() or usuario
    vendedor = str(payload.vendedor or nome).strip() or nome

    try:
        listed = await _edge_admin_write("USUARIOS_LIST", {})
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    target_norm = normalizar(usuario)
    existing: dict[str, Any] | None = None

    for item in listed.get("usuarios") if isinstance(listed.get("usuarios"), list) else []:
        if not isinstance(item, dict):
            continue
        if normalizar(item.get("usuario_norm") or item.get("usuario") or "") == target_norm:
            existing = item
            break

    if existing is not None:
        existing_status = normalizar(existing.get("status") or "")
        existing_active = (
            existing.get("ativo") is not False
            and existing_status not in {"EXCLUIDO", "INATIVO"}
        )
        if existing_active:
            raise HTTPException(
                status_code=409,
                detail="Já existe um usuário ativo com este login no Supabase.",
            )

    # Novos usuários internos não recebem mais uma senha compartilhada.
    initial_password = _temporary_password(12)
    perms = _internal_role_permissions(role)
    perms[PERM_PASSWORD_CHANGE_REQUIRED] = True

    try:
        result = await _edge_admin_write(
            "MIGRAR_USUARIO",
            {
                "usuario": {
                    "usuario": usuario,
                    "usuario_norm": target_norm,
                    "auth_email": auth_email(usuario),
                    "nome": nome,
                    "vendedor": vendedor,
                    "tipo": role,
                    "setor": role,
                    "ativo": True,
                    "status": "ATIVO",
                },
                "senha_interna": senha_interna(
                    usuario,
                    initial_password,
                    settings.auth_pepper,
                ),
                "permissoes": perms,
            },
        )
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return {
        "sucesso": True,
        "origem": "SUPABASE",
        "transporte": "FASTAPI_MIGRAR_USUARIO",
        "usuario": usuario,
        "nome": nome,
        "vendedor": vendedor,
        "tipo": role,
        "setor": role,
        "permissoes": perms,
        "senhaInicialPadrao": False,
        "senhaTemporaria": initial_password,
        "trocaSenhaObrigatoria": True,
        "usuarioReativado": existing is not None,
        "authUserId": str(result.get("auth_user_id") or ""),
        "compradorCriadoDireto": role == ROLE_BUYER,
        "mensagem": (
            f"Usuário {usuario} reativado como {role} na arquitetura nova."
            if existing is not None
            else f"Usuário {usuario} criado como {role} na arquitetura nova."
        ),
    }


def _temporary_password(length: int = 14) -> str:
    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower = "abcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    symbols = "@#%*-_"
    alphabet = upper + lower + digits + symbols
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(ch in upper for ch in value)
            and any(ch in lower for ch in value)
            and any(ch in digits for ch in value)
            and any(ch in symbols for ch in value)
        ):
            return value


async def _security_force_change(row: dict[str, Any], required: bool = True) -> dict[str, Any]:
    """Grava o sinalizador preservando todas as demais permissões."""
    perms = dict(_permission_map(row.get("permissoes")))
    perms[PERM_PASSWORD_CHANGE_REQUIRED] = bool(required)
    await _edge_admin_write(
        "USUARIO_PERMISSOES_SET",
        {
            "usuario_norm": normalizar(row["usuario"]),
            "tipo": str(row.get("tipo") or ""),
            "permissoes": perms,
        },
    )
    return perms


async def _reset_single_password_in_auth(*, usuario: str, tipo: str, senha_interna: str) -> None:
    """Apenas o hash interno chega ao Supabase; a senha em claro nunca e persistida."""
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-password-reset-individual"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=max(10.0, settings.request_timeout_seconds)) as client:
            response = await client.post(endpoint, json={
                "usuario_norm": normalizar(usuario),
                "usuario_exato": usuario,
                "tipo_esperado": tipo,
                "senha_nova_interna": senha_interna,
            }, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(503, "Nao foi possivel confirmar a redefinicao da senha. Nao repita a operacao antes de conferir o acesso do usuario.") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(502, "O servico de senha individual retornou uma resposta invalida.") from exc
    if not isinstance(data, dict) or not response.is_success or data.get("sucesso") is not True:
        detail = str(data.get("erro") or "Nao foi possivel redefinir a senha individualmente.") if isinstance(data, dict) else "Resposta invalida do servico de senha."
        raise HTTPException(response.status_code if response.status_code in {400, 401, 403, 404, 409} else 503, detail)
    if normalizar(data.get("usuario")) != normalizar(usuario):
        raise HTTPException(502, "O servico nao confirmou a identidade do usuario. A senha nao sera exibida.")


async def _individual_password_target(usuario: str) -> dict[str, Any]:
    """Busca a conta ativa diretamente, inclusive INDUSTRIA, sem ampliar outras listagens."""
    result = await _edge_admin_write(
        "USUARIO_CONTEXTO", {"usuario_norm": normalizar(usuario)},
    )
    target = result.get("usuario")
    if (not result.get("encontrado") or not isinstance(target, dict)
            or normalizar(target.get("usuario")) != normalizar(usuario)
            or target.get("ativo") is not True
            or normalizar(target.get("status")) != "ATIVO"):
        raise HTTPException(404, "Usuario ativo nao localizado no cadastro.")
    return target


@router.get("/admin/security/password-reset-individual/users")
async def admin_security_password_reset_individual_users(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    """Lista exclusiva desta tela; nao modifica /admin/users nem expoe senhas."""
    actor = _strict_admin_profile(session)
    actor_login = str(actor.get("usuario") or actor.get("sub") or "").strip()
    if not actor_login:
        raise HTTPException(403, "Administrador sem login identificado.")
    try:
        live_admin = await _granular_user(actor_login)
        if not _is_admin_profile(live_admin):
            raise HTTPException(403, "Apenas um administrador ativo pode consultar esta lista.")
        result = await _edge_admin_write("USUARIOS_LIST", {})
    except IndustryError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    records = result.get("usuarios")
    if not isinstance(records, list):
        raise HTTPException(503, "Lista de usuarios indisponivel.")
    users: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        login = str(record.get("usuario") or "").strip()
        role = str(record.get("tipo") or "").strip()
        if (not login or not role or record.get("ativo") is not True
                or normalizar(record.get("status")) != "ATIVO"
                or normalizar(login) == normalizar(actor_login)):
            continue
        users.append({"usuario": login,
                      "nome": str(record.get("nome") or record.get("vendedor") or login).strip(),
                      "tipo": role})
    users.sort(key=lambda item: normalizar(item["nome"]))
    return {"sucesso": True, "usuarios": users}


@router.post("/admin/security/password-reset-individual")
async def admin_security_password_reset_individual(
    body: AdminIndividualPasswordResetRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    """Recuperacao pontual por administrador; sem senha antiga e sem alterar outras contas."""
    actor = _strict_admin_profile(session)
    actor_login = str(actor.get("usuario") or actor.get("sub") or "").strip()
    if not actor_login:
        raise HTTPException(403, "Administrador sem login identificado.")
    # Nao confiar apenas no cargo gravado no cookie: confirmar o cadastro ativo.
    try:
        live_admin = await _granular_user(actor_login)
    except IndustryError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not _is_admin_profile(live_admin):
        raise HTTPException(403, "Apenas um administrador ativo pode redefinir senhas.")

    async with _PASSWORD_RESET_LOCK:
        try:
            target = await _individual_password_target(body.usuario)
        except IndustryError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        login = str(target.get("usuario") or "").strip()
        role = str(target.get("tipo") or "").strip()
        if not login or normalizar(login) != normalizar(body.usuario) or not role:
            raise HTTPException(409, "Usuario selecionado mudou. Atualize a lista e tente novamente.")
        if normalizar(login) == normalizar(actor_login):
            raise HTTPException(409, "Para evitar bloquear seu acesso administrativo, nao e permitido redefinir sua propria senha nesta tela.")
        flag = PERM_FIRST_ACCESS if normalizar(role) == ROLE_INDUSTRY else PERM_PASSWORD_CHANGE_REQUIRED
        original = _permission_map(target.get("permissoes"))
        if original.get(flag) is not True:
            updated = dict(original)
            updated[flag] = True
            try:
                await _edge_admin_write("USUARIO_PERMISSOES_SET", {
                    "usuario_norm": normalizar(login), "tipo": role, "permissoes": updated,
                })
            except IndustryError as exc:
                raise HTTPException(exc.status_code, "Nao foi possivel marcar a troca obrigatoria de senha.") from exc
            try:
                confirmed = await _individual_password_target(login)
            except IndustryError as exc:
                raise HTTPException(exc.status_code, "A marcacao de troca obrigatoria nao foi confirmada.") from exc
            current_perms = _permission_map(confirmed.get("permissoes"))
            if (str(confirmed.get("tipo") or "") != role
                    or current_perms.get(flag) is not True
                    or {key: value for key, value in current_perms.items() if key != flag}
                       != {key: value for key, value in original.items() if key != flag}):
                raise HTTPException(409, "O cadastro nao confirmou a troca obrigatoria sem alterar outras permissoes.")
        temporary = _temporary_password(14)
        if normalizar(role) == ROLE_INDUSTRY:
            # Antes da redefinicao, invalida passkeys antigas; a troca
            # obrigatoria ja foi marcada no banco e bloqueia login biometrico.
            await _revoke_industry_passkeys(login)
        await _reset_single_password_in_auth(
            usuario=login,
            tipo=role,
            senha_interna=senha_interna(login, temporary, settings.auth_pepper),
        )
        return {
            "sucesso": True,
            "usuario": login,
            "nome": str(target.get("nome") or login),
            "tipo": role,
            "senhaTemporaria": temporary,
            "trocaObrigatoria": True,
            "mensagem": "Senha temporaria gerada somente para o usuario selecionado. Copie-a agora: ela nao sera exibida novamente.",
        }


@router.post("/admin/security/password-reset-defaults")
async def admin_security_password_reset_defaults(
    body: AdminPasswordResetDefaultsRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    """Redefine somente contas internas cuja senha ainda é a antiga senha padrão."""
    _strict_admin_profile(session)
    excluded = normalizar(body.excluirUsuario or "")

    async with _PASSWORD_RESET_LOCK:
        try:
            roster = _active_supabase_users(await _edge_admin_write("USUARIOS_LIST", {}))
        except IndustryError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        if excluded and not any(normalizar(u.get("usuario")) == excluded for u in roster):
            raise HTTPException(404, "O usuário excluído não foi localizado entre os usuários internos ativos.")

        changed: list[dict[str, Any]] = []
        already_changed: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        excluded_result: dict[str, Any] | None = None
        semaphore = asyncio.Semaphore(4)

        async def process(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            login = str(row.get("usuario") or "").strip()
            name = str(row.get("nome") or row.get("vendedor") or login).strip()
            role = str(row.get("tipo") or "").strip()

            if excluded and normalizar(login) == excluded:
                if body.exigirTrocaExcluido:
                    try:
                        await _security_force_change(row, True)
                    except Exception as exc:
                        return "erro", {"usuario": login, "nome": name, "motivo": "Não foi possível marcar a troca obrigatória: " + str(exc)[:150]}
                return "excluido", {"usuario": login, "nome": name, "tipo": role, "trocaObrigatoria": bool(body.exigirTrocaExcluido)}

            temporary = _temporary_password(12)
            async with semaphore:
                try:
                    await _edge_admin_write(
                        "USUARIO_SENHA_SET",
                        {
                            "usuario_norm": normalizar(login),
                            "senha_atual_interna": senha_interna(login, LEGACY_DEFAULT_PASSWORD, settings.auth_pepper),
                            "senha_nova_interna": senha_interna(login, temporary, settings.auth_pepper),
                        },
                    )
                except IndustryError as exc:
                    if exc.status_code == 401 and exc.data.get("senhaAtualIncorreta") is True:
                        return "ja_alterada", {"usuario": login, "nome": name, "tipo": role}
                    return "erro", {"usuario": login, "nome": name, "motivo": "Falha ao verificar/redefinir a senha: " + str(exc)[:150]}

                try:
                    await _security_force_change(row, True)
                except Exception as exc:
                    return "erro_com_senha", {
                        "usuario": login,
                        "nome": name,
                        "tipo": role,
                        "senhaTemporaria": temporary,
                        "motivo": "Senha redefinida, mas a troca obrigatória não pôde ser confirmada: " + str(exc)[:150],
                    }

                return "alterada", {"usuario": login, "nome": name, "tipo": role, "senhaTemporaria": temporary}

        results = await asyncio.gather(*(process(row) for row in roster))

        for status, item in results:
            if status == "alterada":
                changed.append(item)
            elif status == "ja_alterada":
                already_changed.append(item)
            elif status == "excluido":
                excluded_result = item
            elif status == "erro_com_senha":
                changed.append(item)
                errors.append({"usuario": item["usuario"], "nome": item["nome"], "motivo": item["motivo"]})
            else:
                errors.append(item)

        try:
            confirmed_roster = _active_supabase_users(await _edge_admin_write("USUARIOS_LIST", {}))
            confirmed_by_user = {normalizar(u.get("usuario")): u for u in confirmed_roster}
            must_confirm = [x["usuario"] for x in changed]
            if excluded_result and excluded_result.get("trocaObrigatoria"):
                must_confirm.append(excluded_result["usuario"])
            for login in must_confirm:
                current = confirmed_by_user.get(normalizar(login))
                current_perms = _permission_map((current or {}).get("permissoes"))
                if current_perms.get(PERM_PASSWORD_CHANGE_REQUIRED) is not True:
                    if not any(e.get("usuario") == login for e in errors):
                        errors.append({"usuario": login, "nome": str((current or {}).get("nome") or login), "motivo": "O banco não confirmou a marcação de troca obrigatória."})
        except Exception as exc:
            errors.append({"usuario": "", "nome": "Conferência final", "motivo": "Não foi possível reler o cadastro após a operação: " + str(exc)[:150]})

        return {
            "sucesso": len(errors) == 0,
            "redefinidos": len(changed),
            "jaTinhamTrocado": len(already_changed),
            "totalAvaliados": len(roster),
            "alterados": changed,
            "preservados": already_changed,
            "excluido": excluded_result,
            "erros": errors,
            "mensagem": f"{len(changed)} senha(s) temporária(s) gerada(s); {len(already_changed)} usuário(s) já tinham trocado a senha.",
        }


@router.post("/admin/security/change-required-password")
async def security_change_required_password(
    body: ForcedPasswordChangeRequest,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    if not session:
        raise HTTPException(401, "Sessão ausente.")
    profile = _session_profile(session)
    login = str(profile.get("usuario") or profile.get("sub") or "").strip()
    if not login:
        raise HTTPException(401, "Sessão sem usuário identificado.")

    live = await _granular_user(login)
    current_perms = _permission_map(live.get("permissoes"))
    if current_perms.get(PERM_PASSWORD_CHANGE_REQUIRED) is not True:
        raise HTTPException(409, "Este usuário não possui troca obrigatória pendente.")
    if body.novaSenha == body.senhaAtual:
        raise HTTPException(400, "A nova senha precisa ser diferente da senha atual.")

    try:
        await _edge_admin_write(
            "USUARIO_SENHA_SET",
            {
                "usuario_norm": normalizar(login),
                "senha_atual_interna": senha_interna(login, body.senhaAtual, settings.auth_pepper),
                "senha_nova_interna": senha_interna(login, body.novaSenha, settings.auth_pepper),
            },
        )
    except IndustryError as exc:
        if exc.status_code == 401 and exc.data.get("senhaAtualIncorreta") is True:
            raise HTTPException(401, "A senha atual/temporária está incorreta.") from exc
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    updated = dict(current_perms)
    updated[PERM_PASSWORD_CHANGE_REQUIRED] = False
    try:
        await _edge_admin_write(
            "USUARIO_PERMISSOES_SET",
            {"usuario_norm": normalizar(login), "tipo": str(live.get("tipo") or profile.get("tipo") or ""), "permissoes": updated},
        )
        confirmed = await _granular_user(login)
        if _permission_map(confirmed.get("permissoes")).get(PERM_PASSWORD_CHANGE_REQUIRED) is not False:
            raise RuntimeError("O cadastro não confirmou a conclusão da troca obrigatória.")
    except Exception as exc:
        raise HTTPException(503, "A senha foi alterada, mas o sistema não confirmou a liberação do acesso. Entre novamente com a nova senha e conclua a troca obrigatória.") from exc

    refreshed = dict(profile)
    refreshed.update({
        "nome": confirmed.get("nome") or profile.get("nome") or "",
        "vendedor": confirmed.get("vendedor") or profile.get("vendedor") or "",
        "tipo": confirmed.get("tipo") or profile.get("tipo") or "",
        "setor": confirmed.get("setor") or profile.get("setor") or "",
        "permissoes": _permission_map(confirmed.get("permissoes")),
    })
    token = issue_session_token(usuario=login, profile=refreshed, secret=settings.jwt_secret, issuer=settings.jwt_issuer, lifetime_seconds=settings.session_seconds)
    response.set_cookie(key=settings.cookie_name, value=token, max_age=settings.session_seconds, httponly=True, secure=settings.cookie_secure, samesite=settings.cookie_samesite, domain=settings.cookie_domain, path="/")
    return {"sucesso": True, "mensagem": "Senha alterada com sucesso. O acesso foi liberado."}


def _canonical_lab_labels(values: list[str]) -> list[str]:
    # No cadastro e nas listas de Indústrias, Neo Química é uma única opção
    # virtual. Os nomes de origem e vínculos já persistidos não são alterados.
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _portal_lab_label(value)
        key = _portal_lab_key(label)
        if label and key and key not in seen:
            seen.add(key)
            out.append(label.upper())
    return out


def _load_stock_local() -> dict[str, Any]:
    last_error: Exception | None = None
    for path in (STOCK_CURRENT_FILE, STOCK_FALLBACK_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            last_error = exc
            continue
        if isinstance(data, dict) and isinstance(data.get("linhas"), list):
            return data
        last_error = ValueError(f"Mapa inválido em {path.name}")
    raise HTTPException(status_code=503, detail="O mapa de estoque ainda não está disponível.") from last_error


async def _load_stock() -> dict[str, Any]:
    global _STOCK_SNAPSHOT_CACHE
    now = time.monotonic()
    cached = _STOCK_SNAPSHOT_CACHE
    if cached and (now - cached[0]) < _STOCK_SNAPSHOT_TTL_SECONDS:
        return cached[1]

    try:
        data, _row = await cache_get(modulo="MAPA_ESTOQUE", settings=settings)
        if isinstance(data, dict) and isinstance(data.get("linhas"), list):
            _STOCK_SNAPSHOT_CACHE = (now, data)
            return data
    except CacheReadError:
        pass

    data = _load_stock_local()
    _STOCK_SNAPSHOT_CACHE = (now, data)
    return data


async def _stock_rows_for_lab(lab: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = await _load_stock()
    all_labs = _is_all_labs_request(lab)
    keys = _portal_source_keys(lab)
    rows: list[dict[str, Any]] = []
    for row in data.get("linhas", []):
        if not isinstance(row, dict):
            continue
        row_lab = _clean_lab(row.get("fornecedor") or row.get("laboratorio") or "")
        if not all_labs and _lab_key(row_lab) not in keys:
            continue
        item = dict(row)
        # Normalizar também a fotografia já publicada, sem regravar o SQL.
        # Assim a tabela e as exportações mostram 6183 em vez de 6.183
        # antes mesmo da próxima importação do Mapa.
        item["codigo"] = str(item.get("codigo") or "").replace(".", "")
        item["laboratorio"] = _portal_lab_label(row_lab) or (_clean_lab(lab) if not all_labs else "")
        rows.append(item)
    return data, rows


def _cell_ref(col: int, row: int) -> str:
    out = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return f"{out}{row}"


def _xlsx_inline_cell(ref: str, value: Any, style: int = 0) -> str:
    text = "" if value is None else str(value)
    preserve = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t{preserve}>{xml_escape(text)}</t></is></c>'


def _xlsx_number_cell(ref: str, value: Any, style: int = 0) -> str:
    return f'<c r="{ref}" s="{style}"><v>{_num(value)}</v></c>'


def _build_xlsx(rows: list[dict[str, Any]], lab: str, generated_at: str) -> bytes:
    include_lab = True  # Laboratório deve aparecer em toda exportação PDF/Excel

    headers = [
        "Código", "Descrição", "Curva", "Preço", "UFO", "Estoque",
        "JUN/26", "JUL/26", "AGO/26", "SET/26", "Média", "EAN",
        "Est. Até", "Últ. Entrada", "Quant.", "Sugest.", "Bloq Compra",
    ]
    keys = [
        "codigo", "descricao", "curva", "preco", "ufo", "estoque",
        "jun_26", "jul_26", "ago_26", "set_26", "media", "ean",
        "est_ate", "ultima_entrada", "quant", "sugest", "bloq_compra",
    ]

    if include_lab:
        headers = ["Laboratório", *headers]
        keys = ["laboratorio", *keys]

    numeric_keys = {"preco", "ufo", "estoque", "jun_26", "jul_26", "ago_26", "set_26", "media", "quant", "sugest"}

    sheet_rows: list[str] = []
    meta = [
        ["DISMEPE ONE INDÚSTRIAS - MAPA DE ESTOQUE"],
        [f"Laboratório: {lab}"],
        [f"Mapa atualizado em: {generated_at}"],
        [],
        headers,
    ]
    all_matrix: list[list[Any]] = meta + [[row.get(k, "") for k in keys] for row in rows]
    for r_idx, row in enumerate(all_matrix, start=1):
        cells: list[str] = []
        for c_idx, value in enumerate(row, start=1):
            ref = _cell_ref(c_idx, r_idx)
            if r_idx >= 6 and keys[c_idx - 1] in numeric_keys:
                cells.append(_xlsx_number_cell(ref, value, 0))
            else:
                style = 1 if r_idx in {1, 5} else 0
                cells.append(_xlsx_inline_cell(ref, value, style))
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    last_row = len(all_matrix)
    last_col = _cell_ref(len(headers), 1)[:-1]
    widths = [12, 54, 9, 12, 10, 12, 11, 11, 11, 11, 11, 18, 14, 15, 11, 11, 12]
    if include_lab:
        widths = [26, *widths]
    cols_xml = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths, start=1)
    )
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_col}{last_row}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="5" topLeftCell="A6" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <cols>{cols_xml}</cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
  <autoFilter ref="A5:{last_col}{last_row}"/>
</worksheet>'''
    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF005548"/><bgColor indexed="64"/></patternFill></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Estoque" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'''

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return out.getvalue()


def _pdf_safe_text(value: Any) -> str:
    text = str(value or "")
    return text.replace("\u2013", "-").replace("\u2014", "-")


def _build_pdf(rows: list[dict[str, Any]], lab: str, generated_at: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Gerador de PDF indisponível no servidor.") from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=7 * mm,
        leftMargin=7 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=f"Mapa de Estoque - {lab}",
        author="DISMEPE ONE INDÚSTRIAS",
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph("<b>DISMEPE ONE INDÚSTRIAS - MAPA DE ESTOQUE</b>", styles["Title"]),
        Paragraph(f"<b>Laboratório:</b> {_pdf_safe_text(lab)} &nbsp;&nbsp; <b>Atualizado:</b> {_pdf_safe_text(generated_at)}", styles["BodyText"]),
        Spacer(1, 5 * mm),
    ]
    include_lab = True  # Laboratório deve aparecer em toda exportação PDF/Excel

    headers = ["Código", "Descrição", "Curva", "Preço", "Estoque", "JUN", "JUL", "AGO", "SET", "Média", "EAN", "Est. até", "Últ. entrada"]
    if include_lab:
        headers = ["Laboratório", *headers]

    data: list[list[Any]] = [headers]
    for row in rows:
        values = [
            _pdf_safe_text(row.get("codigo")),
            _pdf_safe_text(row.get("descricao")),
            _pdf_safe_text(row.get("curva")),
            _pdf_safe_text(row.get("preco")),
            _pdf_safe_text(row.get("estoque")),
            _pdf_safe_text(row.get("jun_26")),
            _pdf_safe_text(row.get("jul_26")),
            _pdf_safe_text(row.get("ago_26")),
            _pdf_safe_text(row.get("set_26")),
            _pdf_safe_text(row.get("media")),
            _pdf_safe_text(row.get("ean")),
            _pdf_safe_text(row.get("est_ate")),
            _pdf_safe_text(row.get("ultima_entrada")),
        ]
        if include_lab:
            values = [_pdf_safe_text(row.get("laboratorio") or row.get("fornecedor")), *values]
        data.append(values)

    col_widths = [17*mm, 74*mm, 13*mm, 14*mm, 17*mm, 13*mm, 13*mm, 13*mm, 13*mm, 13*mm, 31*mm, 22*mm, 24*mm]
    if include_lab:
        # Largura disponível: 297 - (2 x 7) = 283 mm (A4 paisagem).
        col_widths = [26*mm, 15*mm, 78*mm, 11*mm, 13*mm, 15*mm, 11*mm, 11*mm, 11*mm, 11*mm, 11*mm, 25*mm, 18*mm, 20*mm]
    body_style = ParagraphStyle("StockBodyV12", parent=styles["Normal"],
                                fontName="Helvetica", fontSize=6.2, leading=8,
                                wordWrap="CJK", splitLongWords=1)
    head_style = ParagraphStyle("StockHeadV12", parent=body_style,
                                fontName="Helvetica-Bold", textColor=colors.white)
    data = [[Paragraph(xml_escape(str(value or "")), head_style if idx == 0 else body_style)
             for value in record] for idx, record in enumerate(data)]
    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#005548")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.2),
        ("LEADING", (0, 0), (-1, -1), 7.1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E4E0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def _safe_filename_lab(lab: str) -> str:
    text = unicodedata.normalize("NFD", lab)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text.upper() or "LABORATORIO"


def _general_sales_snapshot(lab: str, competencia: str) -> dict[str, Any] | None:
    # Fonte oficial: OBJETIVO X VENDA.xlsx normalizada em venda_geral_atual.json.
    if not GENERAL_SALES_FILE.exists():
        return None
    try:
        payload = json.loads(GENERAL_SALES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    rows = payload.get("linhas") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None

    all_labs = _is_all_labs_request(lab)
    lab_keys = _portal_source_keys(lab)
    comp_key = normalizar(competencia or "")
    total = 0.0
    objective = 0.0
    positivity = 0.0
    found = False
    has_objective = False
    has_positivity = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_lab = row.get("laboratorio") or row.get("lab") or row.get("fornecedor") or row.get("industria")
        if not all_labs and _lab_key(row_lab) not in lab_keys:
            continue
        row_comp = row.get("competencia") or row.get("mes") or row.get("periodo") or ""
        if comp_key and row_comp and normalizar(row_comp) != comp_key:
            continue

        raw_value = row.get("venda_total")
        if raw_value is None:
            raw_value = row.get("venda")
        if raw_value is None:
            raw_value = row.get("total")
        if raw_value is None:
            raw_value = row.get("faturamento")
        total += _num(raw_value)
        found = True

        raw_obj = row.get("objetivo_total")
        if raw_obj is None:
            raw_obj = row.get("objetivo")
        if raw_obj not in (None, ""):
            objective += _num(raw_obj)
            has_objective = True

        raw_pos = row.get("positivacao_total")
        if raw_pos is None:
            raw_pos = row.get("positivacao")
        if raw_pos is None:
            raw_pos = row.get("positivação")
        if raw_pos is None:
            raw_pos = row.get("positivados")
        if raw_pos not in (None, ""):
            positivity += _num(raw_pos)
            has_positivity = True

    if not found:
        return None
    return {
        "venda": round(total, 2),
        "objetivo": round(objective, 2) if has_objective else None,
        "positivacao": int(round(positivity)) if has_positivity else None,
        "atualizadoEm": str(payload.get("gerado_em") or payload.get("atualizado_em") or "") if isinstance(payload, dict) else "",
        "arquivoOrigem": str(payload.get("fonte") or payload.get("arquivo_origem") or "") if isinstance(payload, dict) else "",
    }


def _general_sales_history(lab: str) -> list[dict[str, Any]]:
    # Últimas 3 fotografias, por laboratório ou no consolidado.
    if not GENERAL_SALES_HISTORY_FILE.exists():
        return []
    try:
        payload = json.loads(GENERAL_SALES_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    snapshots = payload.get("atualizacoes") if isinstance(payload, dict) else None
    if not isinstance(snapshots, list):
        return []

    all_labs = _is_all_labs_request(lab)
    lab_keys = _portal_source_keys(lab)
    out: list[dict[str, Any]] = []

    for snapshot in snapshots[:3]:
        if not isinstance(snapshot, dict):
            continue
        rows = snapshot.get("linhas")
        if not isinstance(rows, list):
            continue

        total = 0.0
        objective = 0.0
        found = False
        has_objective = False

        for row in rows:
            if not isinstance(row, dict):
                continue
            row_lab = row.get("laboratorio") or row.get("lab") or row.get("fornecedor") or row.get("industria")
            if not all_labs and _lab_key(row_lab) not in lab_keys:
                continue

            raw_value = row.get("venda_total")
            if raw_value is None:
                raw_value = row.get("venda")
            if raw_value is None:
                raw_value = row.get("total")
            if raw_value is None:
                raw_value = row.get("faturamento")
            total += _num(raw_value)
            found = True

            raw_obj = row.get("objetivo_total")
            if raw_obj is None:
                raw_obj = row.get("objetivo")
            if raw_obj not in (None, ""):
                objective += _num(raw_obj)
                has_objective = True

        if not found:
            continue

        objective_value = round(objective, 2) if has_objective else None
        out.append({
            "idAtualizacao": str(snapshot.get("idAtualizacao") or ""),
            "competencia": str(snapshot.get("competencia") or ""),
            "atualizadoEm": str(snapshot.get("gerado_em") or snapshot.get("atualizado_em") or ""),
            "fonte": str(snapshot.get("fonte") or snapshot.get("arquivo_origem") or ""),
            "vendaTotal": round(total, 2),
            "objetivoTotal": objective_value,
            "atingimentoTotal": (
                round((total / objective_value * 100.0), 2)
                if objective_value is not None and objective_value > 0
                else None
            ),
        })
    return out[:3]


async def _all_available_industry_labs() -> list[str]:
    # Fonte única de laboratórios disponíveis no portal Indústrias.
    # Não depende de o laboratório estar em campanha.
    labels: list[str] = []

    try:
        stock = await _load_stock()
        labels.extend(
            str(x)
            for x in stock.get("fornecedores", [])
            if str(x).strip()
        )
        for row in stock.get("linhas", []):
            if not isinstance(row, dict):
                continue
            lab = _clean_lab(
                row.get("fornecedor")
                or row.get("laboratorio")
                or row.get("Laboratório")
                or row.get("LABORATORIO")
                or ""
            )
            if lab:
                labels.append(lab)
    except HTTPException:
        pass

    try:
        if GENERAL_SALES_FILE.exists():
            general = json.loads(GENERAL_SALES_FILE.read_text(encoding="utf-8"))
            rows = general.get("linhas", []) if isinstance(general, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                lab = _clean_lab(
                    row.get("laboratorio")
                    or row.get("lab")
                    or row.get("fornecedor")
                    or row.get("industria")
                    or ""
                )
                if lab:
                    labels.append(lab)
    except Exception:
        pass

    try:
        payload, _ = await cache_get(modulo="MENSAL", settings=settings)
        for row in list(payload.get("dadosVendedores") or []) + list(payload.get("dadosTelevendas") or []):
            if isinstance(row, dict):
                lab = _row_lab(row)
                if lab:
                    labels.append(lab)
    except Exception:
        pass

    labs = _canonical_lab_labels(labels)
    labs.sort(key=lambda x: normalizar(x))
    return labs


async def _industry_visible_labs(profile: dict[str, Any]) -> list[str]:
    if not _is_internal_industry_viewer(profile):
        return _portal_labs(industry_allowed_labs(profile))
    return _portal_labs(await _all_available_industry_labs())


@router.get("/industrias/laboratorios")
async def industries_labs(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=True)
    labs = await _industry_visible_labs(profile)
    return {
        "sucesso": True,
        "acessoInterno": _is_internal_industry_viewer(profile),
        "acessoComprador": is_buyer_profile(profile),
        "podeTodosLaboratorios": _can_view_all_labs(profile),
        "laboratorios": labs,
    }


@router.get("/industrias/notificacoes.js", include_in_schema=False)
async def industry_notifications_script(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    await _industry_profile(session, require_password_changed=False)
    return FileResponse(ROOT / "frontend" / "industries-notifications.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"})


@router.get("/industrias", include_in_schema=False)
async def industries_page(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    await _industry_profile(session, require_password_changed=False)
    html = INDUSTRIES_FILE.read_text(encoding="utf-8")
    if 'href="/push/manifest.webmanifest"' not in html:
        html = html.replace("</head>", '<link rel="manifest" href="/push/manifest.webmanifest?v=DISMEPE-ICON-3">'
                            '<meta name="theme-color" content="#087b51">'
                            '<meta name="apple-mobile-web-app-capable" content="yes">'
                            '<meta name="apple-mobile-web-app-title" content="DISMEPE ONE">'
                            '<link rel="icon" type="image/png" sizes="192x192" href="/push/app-icon-v2-192.png?v=DISMEPE-ICON-3">'
                            '<link rel="apple-touch-icon" sizes="192x192" href="/push/app-icon-v2-192.png?v=DISMEPE-ICON-3"></head>', 1)
    if html.count("</body>") != 1:
        raise RuntimeError("Fechamento do portal Industrias nao encontrado.")
    html = html.replace(
        "</body>",
        '<script src="/industrias/globo-positivacoes.js?v=GLOBO_POS_V1"></script>\n'
        '<script src="/industrias/notificacoes.js?v=INDUSTRY-BELL-HEADER-2"></script>\n'
        '<script src="/push/client.js?v=PUSH-INDUSTRY-HEADER-2"></script>\n'
        '</body>',
        1,
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/industrias/data")
async def industries_data(
    laboratorio: str | None = Query(default=None),
    competencia: str | None = Query(default=None),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=True)
    lab = _choose_lab(profile, laboratorio)
    all_labs = _is_all_labs_request(lab)

    try:
        payload, row = await cache_get(modulo="MENSAL", settings=settings)
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    vend_all = payload.get("dadosVendedores") if isinstance(payload.get("dadosVendedores"), list) else []
    tlv_all = payload.get("dadosTelevendas") if isinstance(payload.get("dadosTelevendas"), list) else []
    all_rows = [x for x in vend_all + tlv_all if isinstance(x, dict)]
    comps = _all_competences(payload, all_rows)
    comp = str(competencia or "").strip() or (comps[0] if comps else "")
    days = _days_remaining(payload, comp)

    if all_labs:
        vend_raw = [
            row for row in vend_all
            if isinstance(row, dict)
            and (not comp or _row_competence(row) == comp)
            and not _is_focus_row(row)
        ]
        tlv_raw = [
            row for row in tlv_all
            if isinstance(row, dict)
            and (not comp or _row_competence(row) == comp)
            and not _is_focus_row(row)
        ]
    else:
        key = _portal_source_keys(lab)
        vend_raw = [row for row in _filter_lab_rows(vend_all, key, comp or None) if not _is_focus_row(row)]
        tlv_raw = [row for row in _filter_lab_rows(tlv_all, key, comp or None) if not _is_focus_row(row)]

    vend_rows = [_sanitize_sales_row(x, "VENDEDORES", days) for x in vend_raw]
    tlv_rows = [_sanitize_sales_row(x, "TELEVENDAS", days) for x in tlv_raw]
    if not all_labs and _portal_lab_key(lab) == _NEO_PORTAL_LAB:
        vend_rows = _merge_neo_sales_rows(vend_rows, days)
        tlv_rows = _merge_neo_sales_rows(tlv_rows, days)

    # A parcial da industria usa o MESMO componente ja publicado na parcial
    # interna. Somente Globo selecionado; demais laboratorios inalterados.
    if not all_labs and _lab_key(lab) == "GLOBO":
        for original, shown in zip(vend_raw, vend_rows):
            shown["positivacaoIndividualGlobo"] = _globo_individual_from_partial(original)
        for original, shown in zip(tlv_raw, tlv_rows):
            shown["positivacaoIndividualGlobo"] = _globo_individual_from_partial(original)

    venda_v = sum(x["venda"] for x in vend_rows)
    venda_t = sum(x["venda"] for x in tlv_rows)
    obj_v = sum(x["objetivo"] for x in vend_rows)
    obj_t = sum(x["objetivo"] for x in tlv_rows)

    # OBJETIVO X VENDA.xlsx no Drive é a fonte oficial de Venda Geral/Objetivo.
    # A sincronização do Drive já roda em segundo plano na inicialização do portal.
    # A troca de laboratório lê a última fotografia válida sem aguardar rede externa.
    sales_sync_status = general_sales_sync_public_status()

    # Venda Geral nunca cai para Vendedores + Televendas.
    general = _general_sales_snapshot(lab, comp)
    venda_total: float | None = None
    obj_total: float | None = None
    positivacao_total: int | None = None
    fonte_venda_total = "BASE_GERAL_INDISPONIVEL"
    venda_total_atualizado_em = ""
    if general is not None:
        venda_total = float(general["venda"])
        obj_total = general.get("objetivo")
        raw_positivity = general.get("positivacao")
        positivacao_total = int(raw_positivity) if raw_positivity is not None else None
        fonte_venda_total = "BASE_GERAL"
        venda_total_atualizado_em = str(general.get("atualizadoEm") or "")

    return {
        "sucesso": True,
        "laboratorio": ALL_LABS_LABEL if all_labs else lab,
        "todosLaboratorios": all_labs,
        "laboratoriosAutorizados": await _industry_visible_labs(profile),
        "acessoInterno": _is_internal_industry_viewer(profile),
        "acessoComprador": is_buyer_profile(profile),
        "vendaGeralSync": sales_sync_status,
        "competencia": comp,
        "competencias": comps,
        "diasUteisRestantes": days,
        "atualizadoEm": str(row.get("atualizado_em") or ""),
        "resumo": {
            "vendaTotal": None if all_labs else (round(venda_total, 2) if venda_total is not None else None),
            "vendedores": None if all_labs else round(venda_v, 2),
            "televendas": None if all_labs else round(venda_t, 2),
            "objetivoTotal": None if all_labs else (round(obj_total, 2) if obj_total is not None else None),
            "objetivoVendedores": None if all_labs else round(obj_v, 2),
            "objetivoTelevendas": None if all_labs else round(obj_t, 2),
            "atingimentoTotal": (
                None
                if all_labs
                else (
                    round((venda_total / obj_total * 100.0), 2)
                    if venda_total is not None and obj_total is not None and obj_total > 0
                    else None
                )
            ),
            "fonteVendaTotal": fonte_venda_total,
            "vendaTotalAtualizadoEm": venda_total_atualizado_em,
            "positivacao": None if all_labs else positivacao_total,
        },
        "vendedores": vend_rows,
        "televendas": tlv_rows,
        "campanhas": [] if all_labs else _industry_campaign_metrics(payload, lab, comp),
        "historico": [] if all_labs else _general_sales_history(lab),
        "oportunidades": [],
    }


@router.get("/industrias/estoque")
async def industries_stock(
    laboratorio: str | None = Query(default=None),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=True)
    lab = _choose_lab(profile, laboratorio)
    all_labs = _is_all_labs_request(lab)
    data, rows = await _stock_rows_for_lab(lab)
    total_stock = sum(_int(row.get("estoque")) for row in rows)
    without_stock = sum(1 for row in rows if _int(row.get("estoque")) <= 0)
    return {
        "sucesso": True,
        "laboratorio": ALL_LABS_LABEL if all_labs else lab,
        "todosLaboratorios": all_labs,
        "atualizadoEm": str(data.get("gerado_em") or ""),
        "arquivoOrigem": str(data.get("fonte") or data.get("arquivo_origem") or ""),
        "resumo": {
            "skus": len(rows),
            "estoqueTotal": total_stock,
            "semEstoque": without_stock,
        },
        "linhas": rows,
    }


@router.get("/industrias/download/excel")
async def industries_download_excel(
    laboratorio: str | None = Query(default=None),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=True)
    lab = _choose_lab(profile, laboratorio)
    data, rows = await _stock_rows_for_lab(lab)
    content = _build_xlsx(rows, lab, str(data.get("gerado_em") or ""))
    filename = f"MAPA_ESTOQUE_{_safe_filename_lab(lab)}_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/industrias/download/pdf")
async def industries_download_pdf(
    laboratorio: str | None = Query(default=None),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=True)
    lab = _choose_lab(profile, laboratorio)
    data, rows = await _stock_rows_for_lab(lab)
    content = _build_pdf(rows, lab, str(data.get("gerado_em") or ""))
    filename = f"MAPA_ESTOQUE_{_safe_filename_lab(lab)}_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/industries/users")
async def industries_admin_users(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_profile(session)
    try:
        payload = await _edge_admin_write("USUARIOS_LIST", {})
    except IndustryError as exc:
        detail = (
            exc.data.get("mensagem")
            or exc.data.get("message")
            or exc.data.get("detail")
            or exc.data.get("erro")
            or exc.data.get("error")
            or str(exc)
        )
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        raise HTTPException(status_code=exc.status_code, detail=str(detail)) from exc

    users: list[dict[str, Any]] = []
    for item in _snapshot_users(payload):
        usuario = str(item.get("usuario") or item.get("login") or item.get("USUARIO") or "").strip()
        if not usuario:
            continue

        role = normalizar(item.get("tipo") or item.get("perfil") or item.get("cargo") or "")
        if role != ROLE_INDUSTRY:
            continue

        raw_perms = item.get("permissoes")
        if raw_perms is None:
            raw_perms = item.get("PERMISSOES")
        perms = _permission_map(raw_perms)

        raw_labs = perms.get(PERM_LABS)
        user_labs: list[str] = []
        if isinstance(raw_labs, list):
            user_labs = _canonical_lab_labels(raw_labs)
        elif isinstance(raw_labs, str):
            user_labs = _canonical_lab_labels(
                [x for x in re.split(r"[,;|]", raw_labs) if x.strip()]
            )

        if not user_labs:
            setor = str(item.get("setor") or "").strip()
            setor = re.sub(r"^INDUSTRIA\s*[:|\-]\s*", "", setor, flags=re.I)
            if setor and normalizar(setor) != ROLE_INDUSTRY:
                user_labs = _canonical_lab_labels([setor])

        users.append(
            {
                "usuario": usuario,
                "nome": str(item.get("nome") or item.get("vendedor") or usuario).strip(),
                "laboratorios": user_labs,
            }
        )

    users.sort(key=lambda item: normalizar(item.get("nome") or item.get("usuario") or ""))
    return {"sucesso": True, "usuarios": users}


@router.post("/admin/industries/users/labs")
async def industries_update_user_labs(
    payload: IndustryUserLabsUpdateRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_profile(session)

    usuario = str(payload.usuario or "").strip()
    labs = _canonical_lab_labels(payload.laboratorios)
    if not usuario:
        raise HTTPException(status_code=400, detail="Usuário inválido.")
    if not labs:
        raise HTTPException(status_code=400, detail="Selecione ao menos um laboratório.")

    try:
        lookup = await _edge_admin_write(
            "USUARIO_CONTEXTO",
            {"usuario_norm": normalizar(usuario)},
        )
    except IndustryError as exc:
        detail = (
            exc.data.get("mensagem")
            or exc.data.get("message")
            or exc.data.get("detail")
            or exc.data.get("erro")
            or exc.data.get("error")
            or str(exc)
        )
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        raise HTTPException(status_code=exc.status_code, detail=str(detail)) from exc

    target = lookup.get("usuario") if lookup.get("encontrado") is True else None
    if not isinstance(target, dict):
        raise HTTPException(status_code=404, detail="Usuário da indústria não encontrado.")

    role = normalizar(target.get("tipo") or target.get("perfil") or target.get("cargo") or "")
    if role != ROLE_INDUSTRY:
        raise HTTPException(
            status_code=400,
            detail="O usuário selecionado não é um usuário da indústria.",
        )

    perms = _permission_map(target.get("permissoes"))
    perms[PERM_PORTAL] = True
    perms[PERM_LABS] = labs

    try:
        await _edge_admin_write(
            "USUARIO_PERMISSOES_SET",
            {
                "usuario_norm": normalizar(usuario),
                "tipo": ROLE_INDUSTRY,
                "permissoes": perms,
            },
        )
    except IndustryError as exc:
        detail = (
            exc.data.get("mensagem")
            or exc.data.get("message")
            or exc.data.get("detail")
            or exc.data.get("erro")
            or exc.data.get("error")
            or str(exc)
        )
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        raise HTTPException(status_code=exc.status_code, detail=str(detail)) from exc

    return {
        "sucesso": True,
        "usuario": usuario,
        "laboratorios": labs,
        "mensagem": (
            "Laboratórios atualizados. O novo vínculo será aplicado "
            "no próximo login desse usuário."
        ),
    }


@router.post("/admin/industries/buyers")
async def industries_create_buyer(
    payload: IndustryBuyerCreateRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _strict_admin_profile(session)

    usuario = str(payload.usuario or "").strip()
    nome = str(payload.nome or "").strip() or usuario
    if not usuario:
        raise HTTPException(status_code=400, detail="Usuario invalido.")

    initial_password = _temporary_password(12)
    buyer_perms: dict[str, Any] = {
        PERM_INTERNAL_PORTAL: True,
        PERM_BUYER_ALL_LABS: True,
        PERM_STOCK_UPDATE: False,
        PERM_PASSWORD_CHANGE_REQUIRED: True,
    }

    def error_text(exc: IndustryError) -> str:
        values: list[Any] = [
            str(exc),
            exc.data.get("erro"),
            exc.data.get("error"),
            exc.data.get("detail"),
            exc.data.get("mensagem"),
            exc.data.get("message"),
        ]
        for value in values:
            if value is None or value == "":
                continue
            if isinstance(value, (dict, list)):
                try:
                    return json.dumps(value, ensure_ascii=False)
                except Exception:
                    return str(value)
            return str(value)
        return "Falha no servico de usuarios."

    try:
        create_result = await _edge_admin_write(
            "MIGRAR_USUARIO",
            {
                "usuario": {
                    "usuario": usuario,
                    "usuario_norm": normalizar(usuario),
                    "auth_email": auth_email(usuario),
                    "nome": nome,
                    "vendedor": nome,
                    "tipo": "COMERCIAL",
                    "setor": "COMERCIAL",
                    "ativo": True,
                    "status": "ATIVO",
                },
                "senha_interna": senha_interna(
                    usuario,
                    initial_password,
                    settings.auth_pepper,
                ),
                "permissoes": buyer_perms,
            },
        )
        existed = False
    except IndustryError as create_exc:
        message = error_text(create_exc)
        normalized = normalizar(message)
        duplicate = any(
            marker in normalized
            for marker in (
                "JA EXISTE",
                "EXISTENTE",
                "DUPLIC",
                "CADASTRAD",
                "ALREADY",
            )
        )
        if not duplicate:
            raise HTTPException(
                status_code=create_exc.status_code,
                detail={
                    "codigo": "COMPRADOR_CREATE_FAILED",
                    "mensagem": message,
                },
            ) from create_exc
        create_result = {}
        existed = True

    try:
        await _edge_admin_write(
            "USUARIO_PERMISSOES_SET",
            {
                "usuario_norm": normalizar(usuario),
                "tipo": ROLE_BUYER,
                "permissoes": buyer_perms,
            },
        )
    except IndustryError as promote_exc:
        message = error_text(promote_exc)
        raise HTTPException(
            status_code=promote_exc.status_code,
            detail={
                "codigo": "COMPRADOR_PROMOTE_FAILED",
                "mensagem": message,
                "usuarioCriadoComoComercial": not existed,
            },
        ) from promote_exc

    return {
        "sucesso": True,
        "usuario": usuario,
        "nome": nome,
        "tipo": ROLE_BUYER,
        "compradorCriadoDireto": True,
        "usuarioExistenteConvertido": existed,
        "somentePortalIndustrias": True,
        "todosLaboratorios": True,
        "podeAtualizarMapa": False,
        "senhaInicialPadrao": False,
        "senhaTemporaria": initial_password if not existed else None,
        "trocaSenhaObrigatoria": not existed,
        "authUserId": str(create_result.get("auth_user_id") or ""),
        "mensagem": (
            "Usuario existente convertido em COMPRADOR."
            if existed
            else "Usuario criado e promovido para COMPRADOR."
        ),
    }


@router.post("/admin/industries/buyers/promote")
async def industries_promote_buyer(
    payload: IndustryBuyerPromoteRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _strict_admin_profile(session)
    usuario = str(payload.usuario or "").strip()
    if not usuario:
        raise HTTPException(status_code=400, detail="Usuário inválido.")

    buyer_perms: dict[str, Any] = {
        PERM_INTERNAL_PORTAL: True,
        PERM_BUYER_ALL_LABS: True,
        PERM_STOCK_UPDATE: False,
    }
    try:
        await _edge_admin_write(
            "USUARIO_PERMISSOES_SET",
            {
                "usuario_norm": normalizar(usuario),
                "tipo": ROLE_BUYER,
                "permissoes": buyer_perms,
            },
        )
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return {
        "sucesso": True,
        "usuario": usuario,
        "tipo": ROLE_BUYER,
        "somentePortalIndustrias": True,
        "todosLaboratorios": True,
        "podeAtualizarMapa": False,
        "mensagem": "Usuário convertido em COMPRADOR com acesso somente ao DISMEPE ONE INDÚSTRIAS e a todos os laboratórios.",
    }


@router.get("/admin/industries/stock-sync/status")
async def industries_stock_sync_status(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    await _stock_update_profile(session)
    return {"sucesso": True, **stock_sync_public_status()}


@router.post("/admin/industries/stock-sync/run")
async def industries_stock_sync_run(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    await _stock_update_profile(session)
    try:
        result = await sync_stock_once(force=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"sucesso": True, **result}


@router.get("/admin/industries/stock-sync/operators")
async def industries_stock_sync_operators(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _permission_view_profile(session)
    try:
        payload, _ = await cache_get(modulo="USUARIOS", settings=settings)
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    users: list[dict[str, Any]] = []
    for item in _snapshot_users(payload):
        usuario = str(item.get("usuario") or item.get("login") or item.get("USUARIO") or "").strip()
        if not usuario:
            continue
        role = normalizar(item.get("tipo") or item.get("perfil") or item.get("cargo") or "")
        if role == ROLE_INDUSTRY:
            continue
        raw_perms = item.get("permissoes")
        if raw_perms is None:
            raw_perms = item.get("PERMISSOES")
        perms = _permission_map(raw_perms)
        users.append({
            "usuario": usuario,
            "nome": str(item.get("nome") or item.get("vendedor") or usuario).strip(),
            "tipo": str(item.get("tipo") or item.get("perfil") or item.get("cargo") or "").strip(),
            "podeAtualizarMapa": _is_admin_profile(item) or perms.get(PERM_STOCK_UPDATE) is True,
            "podeAcessarPortalIndustrias": perms.get(PERM_INTERNAL_PORTAL) is True,
            "administrador": role in {"ADMINISTRADOR", "ADMIN"},
        })
    users.sort(key=lambda item: normalizar(item.get("nome") or item.get("usuario") or ""))
    return {"sucesso": True, "permissao": PERM_STOCK_UPDATE, "usuarios": users}


@router.post("/admin/industries/operator-permissions")
async def industries_operator_permissions(
    payload: IndustryOperatorPermissionsRequest,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    editor = _permission_edit_profile(session)

    tipo = str(payload.tipo or "").strip()
    if normalizar(tipo) == ROLE_INDUSTRY:
        raise HTTPException(
            status_code=400,
            detail="Representantes da indústria usam o acesso direto ao laboratório vinculado e não usam estas permissões internas.",
        )

    selected = {str(key).strip() for key in payload.permissoesSelecionadas if str(key).strip()}
    managed = {str(key).strip() for key in payload.permissoesGerenciadas if str(key).strip()}
    if PERM_INTERNAL_PORTAL not in managed or PERM_STOCK_UPDATE not in managed:
        raise HTTPException(status_code=400, detail="A tela de permissões está desatualizada. Recarregue o sistema e tente novamente.")

    forbidden = {PERM_PORTAL, PERM_FIRST_ACCESS, PERM_LABS, PERM_BUYER_ALL_LABS}
    # USUARIO_PERMISSOES_SET sobrescreve o mapa INTEIRO no banco.
    # Manter todas as chaves fora do conjunto administrado pela tela legada.
    current_user = await _granular_user(payload.usuario)
    current_role = normalizar(current_user.get("tipo"))
    if current_role != normalizar(tipo):
        if normalizar(tipo) != "DIRETOR":
            raise HTTPException(status_code=409, detail="O cargo mudou. Recarregue as permissões antes de salvar.")
        # Apenas administrador pode promover um usuario interno a DIRETOR.
        _strict_admin_profile(session)
        if current_role not in _INTERNAL_ROLE_DEFAULT_PERMISSIONS or current_role in {
            "ADMIN", "ADMINISTRADOR", ROLE_INDUSTRY, ROLE_BUYER
        }:
            raise HTTPException(status_code=403, detail="Este cargo nao pode ser convertido em DIRETOR nesta tela.")
    perms: dict[str, Any] = _permission_map(current_user.get("permissoes"))
    for key in managed:
        # Permissões sensíveis da Positivação são editadas somente pela rota
        # granular, que exige administrador e valida a revisão do cadastro.
        if key in forbidden or key in _POS_GRANULAR or not re.fullmatch(r"[A-Z0-9_]{2,80}", key):
            continue
        perms[key] = key in selected

    if normalizar(tipo) == ROLE_BUYER:
        perms[PERM_INTERNAL_PORTAL] = True
        perms[PERM_BUYER_ALL_LABS] = True
        perms[PERM_STOCK_UPDATE] = False

    usuario = str(payload.usuario or "").strip()
    if not usuario:
        raise HTTPException(status_code=400, detail="Usuário inválido.")

    try:
        await _edge_admin_write(
            "USUARIO_PERMISSOES_SET",
            {
                "usuario_norm": normalizar(usuario),
                "tipo": tipo,
                "permissoes": perms,
            },
        )
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # Se o administrador está editando o próprio usuário, reemite a sessão
    # imediatamente para que /industrias reconheça a nova permissão sem logout.
    editor_user = normalizar(editor.get("usuario") or editor.get("sub") or "")
    if editor_user and editor_user == normalizar(usuario):
        refreshed = dict(editor)
        refreshed["tipo"] = tipo or str(editor.get("tipo") or "")
        refreshed["permissoes"] = perms
        token = issue_session_token(
            usuario=str(editor.get("usuario") or editor.get("sub") or usuario),
            profile=refreshed,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            lifetime_seconds=settings.session_seconds,
        )
        response.set_cookie(
            key=settings.cookie_name,
            value=token,
            max_age=settings.session_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            domain=settings.cookie_domain,
            path="/",
        )

    admin_target = normalizar(tipo) in {"ADMINISTRADOR", "ADMIN"}
    return {
        "sucesso": True,
        "usuario": usuario,
        "podeAtualizarMapa": admin_target or perms.get(PERM_STOCK_UPDATE) is True,
        "podeAcessarPortalIndustrias": perms.get(PERM_INTERNAL_PORTAL) is True,
        "permissoes": [PERM_INTERNAL_PORTAL, PERM_STOCK_UPDATE],
        "mensagem": "Permissões do DISMEPE ONE INDÚSTRIAS gravadas diretamente no serviço de usuários.",
    }


@router.post("/admin/industries/stock-sync/operator-permission")
async def industries_stock_sync_operator_permission(
    payload: IndustryStockPermissionRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _permission_edit_profile(session)
    try:
        users_payload, _ = await cache_get(modulo="USUARIOS", settings=settings)
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    target_key = normalizar(payload.usuario)
    target = next(
        (item for item in _snapshot_users(users_payload)
         if normalizar(item.get("usuario") or item.get("login") or item.get("USUARIO") or "") == target_key),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado na base de permissões.")

    role = normalizar(target.get("tipo") or target.get("perfil") or target.get("cargo") or "")
    if role == ROLE_INDUSTRY:
        raise HTTPException(status_code=400, detail="Essa permissão é destinada a usuários internos que atualizam o mapa.")
    if role in {"ADMINISTRADOR", "ADMIN"} and not payload.permitido:
        return {
            "sucesso": True,
            "usuario": str(target.get("usuario") or payload.usuario),
            "podeAtualizarMapa": True,
            "mensagem": "Administradores já possuem essa autorização por padrão.",
        }

    if "permissoes" not in target:
        raise HTTPException(
            status_code=409,
            detail="A fotografia de usuários não contém as permissões atuais; nenhuma alteração foi feita.",
        )
    perms = _permission_map(target.get("permissoes"))
    perms[PERM_STOCK_UPDATE] = bool(payload.permitido)
    usuario = str(target.get("usuario") or target.get("login") or target.get("USUARIO") or payload.usuario).strip()
    tipo = str(target.get("tipo") or target.get("perfil") or target.get("cargo") or "").strip()
    try:
        await _edge_admin_write(
            "USUARIO_PERMISSOES_SET",
            {
                "usuario_norm": normalizar(usuario),
                "tipo": tipo,
                "permissoes": perms,
            },
        )
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "sucesso": True,
        "usuario": usuario,
        "podeAtualizarMapa": bool(payload.permitido),
        "permissao": PERM_STOCK_UPDATE,
        "mensagem": (
            "Permissão para atualizar o mapa concedida. Ela será aplicada no próximo login do usuário."
            if payload.permitido
            else "Permissão para atualizar o mapa removida. A revogação será aplicada no próximo login do usuário."
        ),
    }


@router.get("/admin/industries/labs")
async def industries_admin_labs(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_profile(session)
    labs = await _all_available_industry_labs()
    return {"sucesso": True, "laboratorios": labs}


@router.post("/admin/industries/users")
async def industries_create_user(
    payload: IndustryUserCreateRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_profile(session)
    usuario = payload.usuario.strip()
    nome = payload.nome.strip()
    labs = _canonical_lab_labels(payload.laboratorios)
    if not labs:
        raise HTTPException(status_code=400, detail="Selecione ao menos um laboratório.")

    # Antes de MIGRAR_USUARIO, consultar a fonte viva do PostgreSQL.
    # Isso impede que um login já existente (inclusive com diferença apenas
    # de maiúsculas/minúsculas) tenha o Supabase Auth alterado antes de a
    # gravação colidir com usuario_norm.
    try:
        existing_lookup = await _edge_admin_write(
            "USUARIO_CONTEXTO",
            {"usuario_norm": normalizar(usuario)},
        )
    except IndustryError as exc:
        detail = (
            exc.data.get("mensagem")
            or exc.data.get("message")
            or exc.data.get("detail")
            or exc.data.get("erro")
            or exc.data.get("error")
            or str(exc)
        )
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        raise HTTPException(status_code=exc.status_code, detail=str(detail)) from exc

    existing = (
        existing_lookup.get("usuario")
        if existing_lookup.get("encontrado") is True
        else None
    )
    if isinstance(existing, dict):
        existing_role = str(existing.get("tipo") or "").strip()
        if normalizar(existing_role) == ROLE_INDUSTRY:
            message = (
                "Esse usuário da indústria já existe. "
                "Use 'Editar laboratórios do usuário' para alterar os fornecedores vinculados."
            )
        else:
            message = (
                "Esse login já existe no sistema"
                + (f" como {existing_role}" if existing_role else "")
                + ". Para preservar o acesso atual, use outro nome de usuário."
            )
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": "USUARIO_JA_EXISTE",
                "mensagem": message,
            },
        )

    temporary_password = _temporary_password()
    perms: dict[str, Any] = {
        "ALTERAR_SENHA": True,
        PERM_PORTAL: True,
        PERM_FIRST_ACCESS: True,
        PERM_LABS: labs,
    }
    try:
        result = await _edge_admin_write(
            "MIGRAR_USUARIO",
            {
                "usuario": {
                    "usuario": usuario,
                    "usuario_norm": normalizar(usuario),
                    "auth_email": auth_email(usuario),
                    "nome": nome,
                    "vendedor": nome,
                    "tipo": ROLE_INDUSTRY,
                    "setor": "INDUSTRIA:" + labs[0],
                    "ativo": True,
                    "status": "ATIVO",
                },
                "senha_interna": senha_interna(usuario, temporary_password, settings.auth_pepper),
                "permissoes": perms,
            },
        )
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "sucesso": True,
        "usuario": usuario,
        "nome": nome,
        "tipo": ROLE_INDUSTRY,
        "laboratorios": labs,
        # A senha temporária é devolvida somente nesta resposta de criação.
        "senhaTemporaria": temporary_password,
        "trocaObrigatoria": True,
        "authUserId": str(result.get("auth_user_id") or ""),
    }


async def _finalize_first_access(profile: dict[str, Any]) -> dict[str, Any]:
    perms = dict(_permissions(profile))
    perms[PERM_FIRST_ACCESS] = False
    await _edge_admin_write(
        "USUARIO_PERMISSOES_SET",
        {
            "usuario_norm": normalizar(profile.get("usuario") or ""),
            "tipo": ROLE_INDUSTRY,
            "permissoes": perms,
        },
    )
    updated = dict(profile)
    updated["permissoes"] = perms
    return updated


def _issue_first_access_finalize_token(profile: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(profile.get("usuario") or profile.get("sub") or ""),
            "purpose": "INDUSTRIA_FIRST_ACCESS_FINALIZE",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "nonce": secrets.token_urlsafe(18),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def _validate_first_access_finalize_token(token: str, profile: dict[str, Any]) -> None:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="A autorização para concluir o primeiro acesso expirou.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Autorização inválida para concluir o primeiro acesso.") from exc
    expected = normalizar(profile.get("usuario") or profile.get("sub") or "")
    if data.get("purpose") != "INDUSTRIA_FIRST_ACCESS_FINALIZE" or normalizar(data.get("sub") or "") != expected:
        raise HTTPException(status_code=403, detail="Autorização inválida para este usuário.")


def _refresh_session_cookie(response: Response, profile: dict[str, Any]) -> None:
    usuario = str(profile.get("usuario") or profile.get("sub") or "").strip()
    token = issue_session_token(
        usuario=usuario,
        profile=profile,
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        lifetime_seconds=settings.session_seconds,
    )
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.session_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


@router.post("/industrias/change-password")
async def industries_change_password(
    payload: IndustryPasswordRequest,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=False)
    usuario = str(profile.get("usuario") or profile.get("sub") or "").strip()
    first_access = industry_must_change_password(profile)
    if payload.novaSenha == payload.senhaAtual:
        raise HTTPException(status_code=400, detail="A nova senha deve ser diferente da senha atual.")
    if normalizar(profile.get("tipo")) == ROLE_INDUSTRY:
        # Valida a senha ANTES de revogar as chaves, evitando revogacao
        # por quem possua apenas uma sessao roubada e desconheca a senha.
        from .supabase_edge import login_via_edge, InvalidCredentials, UpstreamUnavailable
        try:
            checked = await login_via_edge(usuario=usuario, senha=payload.senhaAtual, settings=settings)
        except InvalidCredentials as exc:
            raise HTTPException(400, "A senha atual esta incorreta.") from exc
        except UpstreamUnavailable as exc:
            raise HTTPException(503, "Nao foi possivel confirmar a senha. Tente novamente.") from exc
        if normalizar(checked.get("usuario")) != normalizar(usuario):
            raise HTTPException(403, "A identidade nao foi confirmada.")
        await _revoke_industry_passkeys(usuario)
    try:
        await _edge_admin_write(
            "USUARIO_SENHA_SET",
            {
                "usuario_norm": normalizar(usuario),
                "senha_atual_interna": senha_interna(usuario, payload.senhaAtual, settings.auth_pepper),
                "senha_nova_interna": senha_interna(usuario, payload.novaSenha, settings.auth_pepper),
            },
        )
    except IndustryError as exc:
        if exc.data.get("senhaAtualIncorreta") is True:
            raise HTTPException(status_code=400, detail="A senha atual está incorreta.") from exc
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    updated = dict(profile)
    if first_access:
        try:
            updated = await _finalize_first_access(profile)
        except IndustryError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "codigo": "PASSWORD_CHANGED_FINALIZE_PENDING",
                    "mensagem": "A senha foi alterada, mas ainda falta concluir o primeiro acesso. Use o botão Finalizar acesso.",
                    "detalhe": str(exc),
                    "finalizationToken": _issue_first_access_finalize_token(profile),
                },
            ) from exc
    _refresh_session_cookie(response, updated)
    return {"sucesso": True, "trocaObrigatoria": False}


@router.post("/industrias/complete-first-access")
async def industries_complete_first_access(
    payload: IndustryFirstAccessFinalizeRequest,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = await _industry_profile(session, require_password_changed=False)
    if not industry_must_change_password(profile):
        _refresh_session_cookie(response, profile)
        return {"sucesso": True, "trocaObrigatoria": False}
    _validate_first_access_finalize_token(payload.token, profile)
    try:
        updated = await _finalize_first_access(profile)
    except IndustryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    _refresh_session_cookie(response, updated)
    return {"sucesso": True, "trocaObrigatoria": False}


# Positivacoes Globo: rota isolada, sem alterar os outros modulos.
from .globo_positivacoes_industrias import router as globo_positivacoes_router
router.include_router(globo_positivacoes_router)
