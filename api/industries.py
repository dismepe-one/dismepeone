from __future__ import annotations

import io
import json
import re
import secrets
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import httpx
import jwt
from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .cache_reads import CacheReadError, cache_get
from .config import get_settings
from .security import auth_email, decode_session_token, issue_session_token, normalizar, senha_interna
from .industries_stock_sync import CURRENT_FILE as STOCK_CURRENT_FILE, FALLBACK_FILE as STOCK_FALLBACK_FILE, stock_sync_public_status, sync_stock_once


settings = get_settings()
router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]
INDUSTRIES_FILE = ROOT / "frontend" / "industries.html"
STOCK_FILE = STOCK_CURRENT_FILE
GENERAL_SALES_FILE = ROOT / "data" / "industries" / "venda_geral_atual.json"
GENERAL_SALES_HISTORY_FILE = ROOT / "data" / "industries" / "venda_geral_historico.json"

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


class IndustryUserCreateRequest(BaseModel):
    usuario: str = Field(min_length=2, max_length=120)
    nome: str = Field(min_length=2, max_length=160)
    laboratorios: list[str] = Field(min_length=1, max_length=10)


class IndustryPasswordRequest(BaseModel):
    senhaAtual: str = Field(min_length=1, max_length=256)
    novaSenha: str = Field(min_length=8, max_length=256)


class IndustryFirstAccessFinalizeRequest(BaseModel):
    token: str = Field(min_length=20, max_length=2048)


class IndustrySelectionRequest(BaseModel):
    laboratorio: str | None = None


class IndustryStockPermissionRequest(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    permitido: bool


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
    # Consolidado global: exclusivo do perfil COMPRADOR.
    if _is_all_labs_request(requested):
        if _buyer_all_labs(profile):
            return ALL_LABS_VALUE
        raise HTTPException(
            status_code=403,
            detail="O consolidado de todos os laboratórios é exclusivo do perfil Comprador.",
        )

    # Usuário interno autorizado pode selecionar qualquer laboratório individual.
    if _is_internal_industry_viewer(profile):
        label = _clean_lab(requested)
        if not label:
            raise HTTPException(status_code=400, detail="Selecione um laboratório.")
        return label

    allowed = industry_allowed_labs(profile)
    if not allowed:
        raise HTTPException(status_code=403, detail="Nenhum laboratório foi vinculado a este usuário.")
    if not requested:
        return allowed[0]
    key = _lab_key(requested)
    for label in allowed:
        if _lab_key(label) == key:
            return label
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
    lab_key = _lab_key(lab)
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

        if _lab_key(_rule_lab(row)) != lab_key:
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
    allowed_keys = {_lab_key(x) for x in allowed}
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
        "laboratoriosAutorizados": allowed,
        "primeiroAcesso": industry_must_change_password(profile),
    }


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

    initial_password = "1234"
    perms = _internal_role_permissions(role)

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
        "senhaInicialPadrao": True,
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


def _canonical_lab_labels(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _clean_lab(value)
        key = _lab_key(label)
        if label and key and key not in seen:
            seen.add(key)
            out.append(label.upper())
    return out


def _load_stock() -> dict[str, Any]:
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


def _stock_rows_for_lab(lab: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = _load_stock()
    all_labs = _is_all_labs_request(lab)
    key = _lab_key(lab)
    rows: list[dict[str, Any]] = []
    for row in data.get("linhas", []):
        if not isinstance(row, dict):
            continue
        row_lab = _clean_lab(row.get("fornecedor") or row.get("laboratorio") or "")
        if not all_labs and _lab_key(row_lab) != key:
            continue
        item = dict(row)
        item["laboratorio"] = row_lab or (_clean_lab(lab) if not all_labs else "")
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
        from reportlab.lib.styles import getSampleStyleSheet
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
    headers = ["Código", "Descrição", "Curva", "Preço", "Estoque", "JUN", "JUL", "AGO", "SET", "Média", "EAN", "Est. até", "Últ. entrada"]
    data: list[list[Any]] = [headers]
    for row in rows:
        data.append([
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
        ])
    col_widths = [17*mm, 74*mm, 13*mm, 14*mm, 17*mm, 13*mm, 13*mm, 13*mm, 13*mm, 13*mm, 31*mm, 22*mm, 24*mm]
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
    lab_key = _lab_key(lab)
    comp_key = normalizar(competencia or "")
    total = 0.0
    objective = 0.0
    found = False
    has_objective = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_lab = row.get("laboratorio") or row.get("lab") or row.get("fornecedor") or row.get("industria")
        if not all_labs and _lab_key(row_lab) != lab_key:
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

    if not found:
        return None
    return {
        "venda": round(total, 2),
        "objetivo": round(objective, 2) if has_objective else None,
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
    lab_key = _lab_key(lab)
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
            if not all_labs and _lab_key(row_lab) != lab_key:
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


async def _industry_visible_labs(profile: dict[str, Any]) -> list[str]:
    if not _is_internal_industry_viewer(profile):
        return industry_allowed_labs(profile)

    labels: list[str] = []
    try:
        stock = _load_stock()
        labels.extend(str(x) for x in stock.get("fornecedores", []) if str(x).strip())
    except HTTPException:
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
        "podeTodosLaboratorios": _buyer_all_labs(profile),
        "laboratorios": labs,
    }


@router.get("/industrias", include_in_schema=False)
async def industries_page(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    await _industry_profile(session, require_password_changed=False)
    return HTMLResponse(
        INDUSTRIES_FILE.read_text(encoding="utf-8"),
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
        key = {_lab_key(lab)}
        vend_raw = [row for row in _filter_lab_rows(vend_all, key, comp or None) if not _is_focus_row(row)]
        tlv_raw = [row for row in _filter_lab_rows(tlv_all, key, comp or None) if not _is_focus_row(row)]

    vend_rows = [_sanitize_sales_row(x, "VENDEDORES", days) for x in vend_raw]
    tlv_rows = [_sanitize_sales_row(x, "TELEVENDAS", days) for x in tlv_raw]

    venda_v = sum(x["venda"] for x in vend_rows)
    venda_t = sum(x["venda"] for x in tlv_rows)
    obj_v = sum(x["objetivo"] for x in vend_rows)
    obj_t = sum(x["objetivo"] for x in tlv_rows)

    # Venda Geral nunca cai para Vendedores + Televendas.
    general = _general_sales_snapshot(lab, comp)
    venda_total: float | None = None
    obj_total: float | None = None
    fonte_venda_total = "BASE_GERAL_INDISPONIVEL"
    venda_total_atualizado_em = ""
    if general is not None:
        venda_total = float(general["venda"])
        obj_total = general.get("objetivo")
        fonte_venda_total = "BASE_GERAL"
        venda_total_atualizado_em = str(general.get("atualizadoEm") or "")

    return {
        "sucesso": True,
        "laboratorio": ALL_LABS_LABEL if all_labs else lab,
        "todosLaboratorios": all_labs,
        "laboratoriosAutorizados": (
            await _industry_visible_labs(profile)
            if _is_internal_industry_viewer(profile)
            else industry_allowed_labs(profile)
        ),
        "acessoInterno": _is_internal_industry_viewer(profile),
        "acessoComprador": is_buyer_profile(profile),
        "competencia": comp,
        "competencias": comps,
        "diasUteisRestantes": days,
        "atualizadoEm": str(row.get("atualizado_em") or ""),
        "resumo": {
            "vendaTotal": round(venda_total, 2) if venda_total is not None else None,
            "vendedores": round(venda_v, 2),
            "televendas": round(venda_t, 2),
            "objetivoTotal": round(obj_total, 2) if obj_total is not None else None,
            "objetivoVendedores": round(obj_v, 2),
            "objetivoTelevendas": round(obj_t, 2),
            "atingimentoTotal": (
                round((venda_total / obj_total * 100.0), 2)
                if venda_total is not None and obj_total is not None and obj_total > 0
                else None
            ),
            "fonteVendaTotal": fonte_venda_total,
            "vendaTotalAtualizadoEm": venda_total_atualizado_em,
            "positivacao": None,
        },
        "vendedores": vend_rows,
        "televendas": tlv_rows,
        "campanhas": [] if all_labs else _industry_campaign_metrics(payload, lab, comp),
        "historico": _general_sales_history(lab),
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
    data, rows = _stock_rows_for_lab(lab)
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
    data, rows = _stock_rows_for_lab(lab)
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
    data, rows = _stock_rows_for_lab(lab)
    content = _build_pdf(rows, lab, str(data.get("gerado_em") or ""))
    filename = f"MAPA_ESTOQUE_{_safe_filename_lab(lab)}_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    initial_password = "1234"
    buyer_perms: dict[str, Any] = {
        PERM_INTERNAL_PORTAL: True,
        PERM_BUYER_ALL_LABS: True,
        PERM_STOCK_UPDATE: False,
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
        "senhaInicialPadrao": not existed,
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
        result = await sync_stock_once(force=True)
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
    perms: dict[str, Any] = {}
    for key in managed:
        if key in forbidden or not re.fullmatch(r"[A-Z0-9_]{2,80}", key):
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
    labels: list[str] = []
    try:
        stock = _load_stock()
        labels.extend(str(x) for x in stock.get("fornecedores", []) if str(x).strip())
    except HTTPException:
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
