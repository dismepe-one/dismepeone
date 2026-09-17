from __future__ import annotations

import calendar
import copy
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field

from .config import get_settings
from .industries import (
    IndustryError,
    _edge_admin_write,
    _permissions,
    _role,
    _session_profile,
)


settings = get_settings()
router = APIRouter()
RECIFE_TZ = ZoneInfo("America/Recife")
CONFIG_PREFIX = "MENSAL_DIAS_UTEIS_AUTO_"


class MonthlyInactiveDayRequest(BaseModel):
    data: str = Field(min_length=10, max_length=10)
    motivo: str = Field(default="", max_length=160)


class MonthlyBusinessDaysUpdateRequest(BaseModel):
    competencia: str = Field(min_length=7, max_length=7)
    diasInativos: list[MonthlyInactiveDayRequest] = Field(default_factory=list, max_length=40)


def _normalize_competence(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(0?[1-9]|1[0-2])/(20\d{2})", text)
    if not match:
        return ""
    return f"{int(match.group(1)):02d}/{match.group(2)}"


def _current_competence() -> str:
    now = datetime.now(RECIFE_TZ)
    return now.strftime("%m/%Y")


def _config_key(comp: str) -> str:
    mm, yyyy = comp.split("/")
    return f"{CONFIG_PREFIX}{yyyy}_{mm}"


def _date_in_competence(value: str, comp: str) -> date:
    try:
        parsed = date.fromisoformat(str(value or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Data inválida: {value!s}.") from exc

    mm, yyyy = comp.split("/")
    if parsed.month != int(mm) or parsed.year != int(yyyy):
        raise HTTPException(
            status_code=400,
            detail=f"O dia {parsed.strftime('%d/%m/%Y')} não pertence à competência {comp}.",
        )
    return parsed


def _normalize_inactive_days(raw: Any, comp: str) -> list[dict[str, str]]:
    rows = raw if isinstance(raw, list) else []
    by_date: dict[str, dict[str, str]] = {}

    for item in rows:
        if isinstance(item, str):
            data_value = item
            reason = ""
        elif isinstance(item, dict):
            data_value = str(item.get("data") or item.get("date") or "").strip()
            reason = str(item.get("motivo") or item.get("reason") or "").strip()[:160]
        else:
            continue

        if not data_value:
            continue
        parsed = _date_in_competence(data_value, comp)
        iso = parsed.isoformat()
        by_date[iso] = {"data": iso, "motivo": reason}

    return [by_date[key] for key in sorted(by_date)]


def _month_bounds(comp: str) -> tuple[date, date]:
    normalized = _normalize_competence(comp)
    if not normalized:
        raise HTTPException(status_code=400, detail="Competência inválida. Use MM/AAAA.")
    mm, yyyy = normalized.split("/")
    year = int(yyyy)
    month = int(mm)
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def calculate_business_days_remaining(
    comp: str,
    inactive_days: list[dict[str, str]] | list[str] | None = None,
    *,
    today: date | None = None,
) -> int:
    normalized = _normalize_competence(comp)
    if not normalized:
        return 0

    first, last = _month_bounds(normalized)
    reference = today or datetime.now(RECIFE_TZ).date()
    start = max(reference, first)
    if start > last:
        return 0

    inactive = {
        item["data"]
        for item in _normalize_inactive_days(inactive_days or [], normalized)
    }

    count = 0
    current = start
    while current <= last:
        if current.weekday() < 5 and current.isoformat() not in inactive:
            count += 1
        current += timedelta(days=1)
    return count


def calculate_business_days_total(
    comp: str,
    inactive_days: list[dict[str, str]] | list[str] | None = None,
) -> int:
    normalized = _normalize_competence(comp)
    if not normalized:
        return 0
    first, _last = _month_bounds(normalized)
    return calculate_business_days_remaining(
        normalized,
        inactive_days or [],
        today=first,
    )


def _can_view(profile: dict[str, Any]) -> bool:
    if _role(profile.get("tipo")) in {"ADMINISTRADOR", "ADMIN"}:
        return True
    perms = _permissions(profile)
    return any(
        perms.get(key) is True
        for key in (
            "CAMPANHAS_MENSAIS_VISUALIZAR",
            "CAMPANHAS_MENSAIS_CRIAR",
            "CAMPANHAS_MENSAIS_EDITAR",
            "CADASTRO_CAMPANHAS_MENSAIS",
        )
    )


def _can_edit(profile: dict[str, Any]) -> bool:
    if _role(profile.get("tipo")) in {"ADMINISTRADOR", "ADMIN"}:
        return True
    perms = _permissions(profile)
    return perms.get("CAMPANHAS_MENSAIS_EDITAR") is True


def _monthly_profile(session: str | None, *, edit: bool = False) -> dict[str, Any]:
    profile = _session_profile(session)
    allowed = _can_edit(profile) if edit else _can_view(profile)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Você não possui permissão para alterar os dias úteis da competência."
                if edit
                else "Você não possui permissão para visualizar a Gestão de Campanhas Mensais."
            ),
        )
    return profile


def _edge_error(exc: IndustryError) -> HTTPException:
    detail: Any = (
        exc.data.get("mensagem")
        or exc.data.get("message")
        or exc.data.get("detail")
        or exc.data.get("erro")
        or exc.data.get("error")
        or str(exc)
    )
    if isinstance(detail, (dict, list)):
        detail = str(detail)
    return HTTPException(status_code=exc.status_code, detail=str(detail))


async def _campaign_metadata(comp: str) -> dict[str, Any]:
    try:
        result = await _edge_admin_write("CM_COMPETENCIAS_LIST", {})
    except IndustryError as exc:
        raise _edge_error(exc) from exc

    records = result.get("registros") if isinstance(result.get("registros"), list) else []
    for item in records:
        if not isinstance(item, dict):
            continue
        if _normalize_competence(item.get("competencia")) == comp:
            return dict(item)
    raise HTTPException(status_code=404, detail=f"Competência {comp} não encontrada na Gestão de Campanhas.")


def _campaign_locked(meta: dict[str, Any]) -> bool:
    status = str(meta.get("status") or "").strip().upper()
    return (
        meta.get("congelada") is True
        or meta.get("fechada") is True
        or status in {"HISTÓRICO", "HISTORICO", "FECHADA", "CONGELADA"}
    )


async def _read_config(comp: str) -> dict[str, Any]:
    try:
        result = await _edge_admin_write(
            "CONFIG_GET",
            {"chave": _config_key(comp)},
        )
    except IndustryError as exc:
        raise _edge_error(exc) from exc

    value = result.get("valor")
    return dict(value) if isinstance(value, dict) else {}


async def _read_config_for_enrichment(comp: str) -> tuple[bool, dict[str, Any]]:
    try:
        result = await _edge_admin_write(
            "CONFIG_GET",
            {"chave": _config_key(comp)},
        )
    except Exception:
        return False, {}
    value = result.get("valor")
    return True, dict(value) if isinstance(value, dict) else {}


def _payload_has_competence(payload: dict[str, Any], comp: str) -> bool:
    days_map = payload.get("diasUteisPorCompetencia")
    if isinstance(days_map, dict) and comp in days_map:
        return True

    campaign = payload.get("campanhaMensalAtual")
    if isinstance(campaign, dict) and _normalize_competence(campaign.get("competencia")) == comp:
        return True

    for key in ("competenciasDisponiveis", "competencias", "gestaoCampanhasMensaisLista"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            value = item.get("competencia") if isinstance(item, dict) else item
            if _normalize_competence(value) == comp:
                return True

    for key in ("dadosVendedores", "dadosTelevendas"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            value = (
                item.get("__COMPETENCIA")
                or item.get("competencia")
                or item.get("Competencia")
                or item.get("Competência")
            )
            if _normalize_competence(value) == comp:
                return True
    return False


def _update_competence_lists(payload: dict[str, Any], comp: str, days: int) -> None:
    for key in ("competenciasDisponiveis", "competencias", "gestaoCampanhasMensaisLista"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        updated: list[Any] = []
        for item in rows:
            if isinstance(item, dict) and _normalize_competence(item.get("competencia")) == comp:
                updated.append({**item, "diasUteisRestantes": days})
            else:
                updated.append(item)
        payload[key] = updated


async def enrich_monthly_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Substitui somente os dias da competência corrente por cálculo automático.

    Se a configuração não puder ser consultada, devolve a fotografia original
    intacta. Assim uma indisponibilidade da configuração nunca remove os dados
    comerciais existentes.
    """
    if not isinstance(payload, dict):
        return payload

    comp = _current_competence()
    if not _payload_has_competence(payload, comp):
        return payload

    config_ok, config = await _read_config_for_enrichment(comp)
    if not config_ok:
        return payload

    try:
        inactive_days = _normalize_inactive_days(config.get("diasInativos"), comp)
    except HTTPException:
        inactive_days = []

    days = calculate_business_days_remaining(comp, inactive_days)
    result = copy.deepcopy(payload)

    days_map = result.get("diasUteisPorCompetencia")
    days_map = dict(days_map) if isinstance(days_map, dict) else {}
    days_map[comp] = days
    result["diasUteisPorCompetencia"] = days_map

    principal = _normalize_competence(result.get("competenciaPrincipal"))
    if not principal or principal == comp:
        result["diasUteisRestantes"] = days

    campaign = result.get("campanhaMensalAtual")
    if isinstance(campaign, dict) and _normalize_competence(campaign.get("competencia")) == comp:
        result["campanhaMensalAtual"] = {**campaign, "diasUteisRestantes": days}

    _update_competence_lists(result, comp, days)
    return result


def _response_payload(
    *,
    comp: str,
    meta: dict[str, Any],
    config: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    inactive_days = _normalize_inactive_days(config.get("diasInativos"), comp)
    first, last = _month_bounds(comp)
    days = calculate_business_days_remaining(comp, inactive_days)
    return {
        "sucesso": True,
        "competencia": comp,
        "automatico": True,
        "fusoHorario": "America/Recife",
        "dataReferencia": datetime.now(RECIFE_TZ).date().isoformat(),
        "inicioCompetencia": first.isoformat(),
        "fimCompetencia": last.isoformat(),
        "diasUteisRestantes": days,
        "diasUteisTotais": calculate_business_days_total(comp, inactive_days),
        "diasInativos": inactive_days,
        "podeEditar": _can_edit(profile),
        "bloqueado": _campaign_locked(meta),
        "statusCampanha": str(meta.get("status") or ""),
        "regra": "SEGUNDA_A_SEXTA_MENOS_DIAS_INATIVOS",
    }


@router.get("/admin/monthly/business-days")
async def monthly_business_days_get(
    competencia: str = Query(min_length=7, max_length=7),
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _monthly_profile(session, edit=False)
    comp = _normalize_competence(competencia)
    if not comp:
        raise HTTPException(status_code=400, detail="Competência inválida. Use MM/AAAA.")

    meta = await _campaign_metadata(comp)
    config = await _read_config(comp)
    return _response_payload(comp=comp, meta=meta, config=config, profile=profile)


@router.post("/admin/monthly/business-days")
async def monthly_business_days_update(
    payload: MonthlyBusinessDaysUpdateRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _monthly_profile(session, edit=True)
    comp = _normalize_competence(payload.competencia)
    if not comp:
        raise HTTPException(status_code=400, detail="Competência inválida. Use MM/AAAA.")

    meta = await _campaign_metadata(comp)
    if _campaign_locked(meta):
        raise HTTPException(
            status_code=409,
            detail="A competência está congelada ou fechada e não pode ter os dias inativos alterados.",
        )

    inactive_days = _normalize_inactive_days(
        [item.model_dump() for item in payload.diasInativos],
        comp,
    )
    config = {
        "competencia": comp,
        "automatico": True,
        "versao": "PROD5.9.8.22",
        "regra": "SEGUNDA_A_SEXTA_MENOS_DIAS_INATIVOS",
        "diasInativos": inactive_days,
    }

    try:
        await _edge_admin_write(
            "CONFIG_SET",
            {
                "chave": _config_key(comp),
                "valor": config,
                "categoria": "CAMPANHAS_MENSAIS",
                "descricao": "Dias úteis automáticos: segunda a sexta menos dias inativos cadastrados.",
                "atualizado_por": str(profile.get("usuario") or profile.get("sub") or ""),
            },
        )
    except IndustryError as exc:
        raise _edge_error(exc) from exc

    response = _response_payload(comp=comp, meta=meta, config=config, profile=profile)
    response["mensagem"] = "Dias inativos salvos. Os dias úteis restantes serão recalculados automaticamente."
    return response
