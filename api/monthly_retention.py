from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .cache_reads import CacheReadError, cache_get
from .security import normalizar
from .update_center import APPS_SCRIPT_UPDATE_CENTER_URL

RETENTION_MONTHS = 2
HISTORY_ITEMS_LIMIT = 3
TIMEZONE = ZoneInfo("America/Recife")


def _comp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if len(text) == 7 and text[2] in {"/", "-"}:
        mm, yyyy = text[:2], text[3:]
        if mm.isdigit() and yyyy.isdigit():
            month = int(mm)
            year = int(yyyy)
            if 1 <= month <= 12:
                return f"{month:02d}/{year:04d}"

    if len(text) == 7 and text[4] in {"-", "/"}:
        yyyy, mm = text[:4], text[5:]
        if mm.isdigit() and yyyy.isdigit():
            month = int(mm)
            year = int(yyyy)
            if 1 <= month <= 12:
                return f"{month:02d}/{year:04d}"

    return text


def retained_competencias(now: datetime | None = None) -> list[str]:
    current = now or datetime.now(TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TIMEZONE)
    else:
        current = current.astimezone(TIMEZONE)

    current_comp = f"{current.month:02d}/{current.year:04d}"

    if current.month == 1:
        previous_month = 12
        previous_year = current.year - 1
    else:
        previous_month = current.month - 1
        previous_year = current.year

    previous_comp = f"{previous_month:02d}/{previous_year:04d}"
    return [current_comp, previous_comp]


def _item_comp(item: Any) -> str:
    if isinstance(item, dict):
        return _comp(
            item.get("competencia")
            or item.get("COMPETENCIA")
            or item.get("__COMPETENCIA")
            or ""
        )
    return _comp(item)


def _filter_items(values: Any, allowed: set[str]) -> list[Any]:
    if not isinstance(values, list):
        return []

    filtered: list[Any] = []
    for item in values:
        comp = _item_comp(item)
        if comp and comp in allowed:
            filtered.append(copy.deepcopy(item))
    return filtered


def filter_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Mantém na Gestão Mensal somente a competência atual e a anterior.

    A competência fechada continua listada enquanto estiver dentro dessa janela.
    Não altera cálculos, regras, dados comerciais ou o status de fechamento.
    """
    if not isinstance(payload, dict):
        return payload

    result = copy.deepcopy(payload)
    retained = retained_competencias()
    allowed = set(retained)

    for key in (
        "competenciasDisponiveis",
        "competencias",
        "gestaoCampanhasMensaisLista",
    ):
        if isinstance(result.get(key), list):
            result[key] = _filter_items(result.get(key), allowed)

    if isinstance(result.get("competenciasSelecionadas"), list):
        result["competenciasSelecionadas"] = [
            _comp(value)
            for value in result["competenciasSelecionadas"]
            if _comp(value) in allowed
        ]

    if isinstance(result.get("competenciasAtivas"), list):
        result["competenciasAtivas"] = [
            _comp(value)
            for value in result["competenciasAtivas"]
            if _comp(value) in allowed
        ]

    monthly = result.get("campanhaMensalAtual")
    if isinstance(monthly, dict):
        monthly = copy.deepcopy(monthly)
        comps = monthly.get("competencias")
        if isinstance(comps, list):
            monthly["competencias"] = [
                _comp(value)
                for value in comps
                if _comp(value) in allowed
            ]
        result["campanhaMensalAtual"] = monthly

    result["retencaoMensalCompetencias"] = retained
    result["retencaoMensalLimite"] = RETENTION_MONTHS
    result["retencaoMensalAutomatica"] = True
    return result


def _role(value: Any) -> str:
    return normalizar(value or "")


def _perms(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("permissoes")
    return value if isinstance(value, dict) else {}


def _is_admin(profile: dict[str, Any]) -> bool:
    return _role(profile.get("tipo")) in {"ADMINISTRADOR", "ADMIN"}


def _can_view_monthly_history(profile: dict[str, Any]) -> bool:
    if _is_admin(profile):
        return True
    perms = _perms(profile)
    return (
        perms.get("HISTORICO_MENSAL_VISUALIZAR") is True
        or perms.get("CADASTRO_CAMPANHAS_MENSAIS") is True
    )


def _can_delete_monthly_history(profile: dict[str, Any]) -> bool:
    if _is_admin(profile):
        return True

    perms = _perms(profile)
    return (
        perms.get("HISTORICO_MENSAL_EXCLUIR") is True
        or perms.get("CADASTRO_CAMPANHAS_MENSAIS") is True
        or any(
            perms.get(key) is True
            for key in (
                "CAMPANHAS_EXTRAS_CRIAR",
                "CAMPANHAS_EXTRAS_EDITAR",
                "CAMPANHAS_EXTRAS_ATIVAR_OCULTAR",
                "CAMPANHAS_EXTRAS_EXCLUIR",
                "CAMPANHAS_EXTRAS_OBSERVACAO",
            )
        )
    )


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date_key(item: dict[str, Any]) -> float:
    raw = str(
        item.get("dataHoraISO")
        or item.get("dataHoraFormatado")
        or ""
    ).strip()

    if not raw:
        return 0.0

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)
        return parsed.timestamp()
    except Exception:
        pass

    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(
                tzinfo=TIMEZONE
            ).timestamp()
        except Exception:
            pass

    return 0.0


def _public_history_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    ident = str(item.get("idAtualizacao") or "").strip()
    comp = _comp(item.get("competencia") or "")
    if not ident or not comp:
        return None

    return {
        "idAtualizacao": ident,
        "competencia": comp,
        "origem": str(item.get("origem") or ""),
        "dataHoraISO": str(item.get("dataHoraISO") or ""),
        "dataHoraFormatado": str(item.get("dataHoraFormatado") or ""),
        "usuario": str(item.get("usuario") or ""),
        "registrosVendedores": _num(item.get("registrosVendedores")),
        "registrosTelevendas": _num(item.get("registrosTelevendas")),
        "objetivoVendedores": _num(item.get("objetivoVendedores")),
        "vendaVendedores": _num(item.get("vendaVendedores")),
        "objetivoTelevendas": _num(item.get("objetivoTelevendas")),
        "vendaTelevendas": _num(item.get("vendaTelevendas")),
    }


async def retained_monthly_history_list(
    *,
    profile: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """Expõe uma fotografia por competência: mês atual + mês anterior.

    Competências anteriores saem automaticamente do histórico operacional do
    portal. A limpeza física do legado é feita separadamente pela rotina de purga.
    """
    if not _can_view_monthly_history(profile):
        raise PermissionError(
            "Você não possui permissão para visualizar este histórico."
        )

    try:
        payload, row = await cache_get(
            modulo="HISTORICO_MENSAL",
            settings=settings,
        )
    except CacheReadError as exc:
        raise RuntimeError(str(exc)) from exc

    raw = (
        payload.get("atualizacoes")
        if isinstance(payload.get("atualizacoes"), list)
        else []
    )

    retained = retained_competencias()
    allowed = set(retained)

    candidates: list[dict[str, Any]] = []
    for item in raw:
        public = _public_history_item(item)
        if public and public["competencia"] in allowed:
            public["__dateKey"] = _date_key(item)
            candidates.append(public)

    candidates.sort(
        key=lambda item: item.get("__dateKey", 0),
        reverse=True,
    )

    # PROD5.9.8.23.29:
    # A retenção continua por competência, mas a navegação é por atualização.
    # 18/09, 17/09 e 16/09 pertencem a 09/2026 e não podem ser colapsadas.
    # Depois de filtrar as competências permitidas, mantemos as 3 fotografias
    # mais recentes em ordem cronológica decrescente.
    items: list[dict[str, Any]] = []
    for candidate in candidates[:HISTORY_ITEMS_LIMIT]:
        item = dict(candidate)
        item.pop("__dateKey", None)
        items.append(item)

    return {
        "sucesso": True,
        "configurado": True,
        "banco": "SUPABASE",
        "origem": "FASTAPI_POSTGRESQL_RETENCAO_2_COMPETENCIAS",
        "atualizacoes": items,
        "limiteHistorico": HISTORY_ITEMS_LIMIT,
        "limiteHistoricoCompetencias": RETENTION_MONTHS,
        "competenciasRetidas": retained,
        "retencaoAutomatica": True,
        "podeExcluir": _can_delete_monthly_history(profile),
        "snapshotAtualizadoEm": str(row.get("atualizado_em") or ""),
        "snapshotVersao": str(row.get("versao") or ""),
    }


class MonthlyRetentionPurgeError(Exception):
    pass


def _comp_order(value: Any) -> int:
    comp = _comp(value)
    try:
        month, year = comp.split("/")
        return int(year) * 100 + int(month)
    except Exception:
        return 0


async def _legacy_history_call(
    *,
    action: str,
    payload: dict[str, Any],
    legacy_token: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Chama o histórico legado sem retry de escrita."""
    token = str(legacy_token or "").strip()
    if not token:
        raise MonthlyRetentionPurgeError(
            "A sessão de compatibilidade ainda não está pronta."
        )

    body = dict(payload or {})
    body["acao"] = str(action or "").strip().upper()
    body["token"] = token

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
        ) as client:
            response = await client.post(
                APPS_SCRIPT_UPDATE_CENTER_URL,
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "text/plain;charset=utf-8",
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise MonthlyRetentionPurgeError(
            "Falha temporária na comunicação com o histórico mensal."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise MonthlyRetentionPurgeError(
            f"O histórico mensal respondeu em formato inválido (HTTP {response.status_code})."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise MonthlyRetentionPurgeError(
            str(
                data.get("erro")
                or data.get("error")
                or f"Histórico mensal HTTP {response.status_code}."
            )
        )
    if not isinstance(data, dict):
        raise MonthlyRetentionPurgeError(
            "Resposta inválida do histórico mensal."
        )
    return data


async def purge_expired_monthly_history(
    *,
    legacy_token: str,
) -> dict[str, Any]:
    """Exclui fisicamente do histórico legado competências anteriores à janela.

    Regra: mantém mês atual + mês imediatamente anterior. Cada HIST39_EXCLUIR
    é enviado uma única vez por execução e nunca é repetido automaticamente.
    """
    listing = await _legacy_history_call(
        action="HIST39_LISTAR",
        payload={"acao": "HIST39_LISTAR"},
        legacy_token=legacy_token,
        timeout_seconds=70.0,
    )

    if not (
        listing.get("sucesso") is True
        or listing.get("ok") is True
        or listing.get("success") is True
    ):
        raise MonthlyRetentionPurgeError(
            str(
                listing.get("erro")
                or listing.get("error")
                or "Não foi possível listar o histórico mensal."
            )
        )

    retained = retained_competencias()
    oldest_kept_order = _comp_order(retained[-1])
    raw = (
        listing.get("atualizacoes")
        if isinstance(listing.get("atualizacoes"), list)
        else []
    )

    expired: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("idAtualizacao") or "").strip()
        comp = _comp(item.get("competencia") or "")
        order = _comp_order(comp)
        if (
            ident
            and ident not in seen_ids
            and order > 0
            and order < oldest_kept_order
        ):
            seen_ids.add(ident)
            expired.append({
                "idAtualizacao": ident,
                "competencia": comp,
            })

    removed: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for item in expired:
        try:
            result = await _legacy_history_call(
                action="HIST39_EXCLUIR",
                payload={
                    "acao": "HIST39_EXCLUIR",
                    "idAtualizacao": item["idAtualizacao"],
                },
                legacy_token=legacy_token,
                timeout_seconds=45.0,
            )
            if (
                result.get("sucesso") is True
                or result.get("ok") is True
                or result.get("success") is True
            ):
                removed.append(item)
            else:
                errors.append({
                    **item,
                    "erro": str(
                        result.get("erro")
                        or result.get("error")
                        or "Exclusão não confirmada."
                    ),
                })
        except MonthlyRetentionPurgeError as exc:
            # Não repete a escrita quando a resposta é ambígua.
            errors.append({**item, "erro": str(exc)})

    return {
        "sucesso": len(errors) == 0,
        "competenciasRetidas": retained,
        "encontradosParaExcluir": len(expired),
        "excluidos": removed,
        "erros": errors,
        "retencaoAutomatica": True,
    }
