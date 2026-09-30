from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import FileResponse

from . import industries as industries_module
from .config import get_settings
from .home_publication import home_publication_cache_get
from .security import decode_session_token, normalizar


settings = get_settings()
router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]
PAGE_FILE = ROOT / "frontend" / "minhas-campanhas.html"
LAUNCHER_FILE = ROOT / "frontend" / "minhas-campanhas-launcher.js"

SPECIAL_OBJECTIVES = {
    "HERBAMED": 160_000.0,
    "NATULAB": 700_000.0,
}


def can_view_my_campaigns(profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    user = normalizar(profile.get("usuario") or profile.get("sub") or "")
    role = normalizar(profile.get("tipo") or "")
    return (
        (user == "FERNANDA" and role == "SUP TELEVENDAS")
        or (user == "DANTON" and role == "ADMINISTRADOR")
    )


def _profile_from_session(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=401, detail="Entre na sua conta para acessar Minhas campanhas.")
    try:
        profile = decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.") from exc
    if not can_view_my_campaigns(profile):
        raise HTTPException(status_code=403, detail="Minhas campanhas está disponível somente para a supervisão de Televendas e, provisoriamente, para Danton.")
    return profile


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _row_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _row_lab(row: dict[str, Any]) -> str:
    value = _row_value(row, "__LAB", "laboratorio", "LABORATORIO", "lab", "fornecedor", "FORNECEDOR")
    return str(value or "").strip()


def _row_competence(row: dict[str, Any]) -> str:
    value = _row_value(row, "__COMPETENCIA", "competencia", "COMPETENCIA", "mes", "MES", "periodo")
    return str(value or "").strip()


def _is_non_sales_row(row: dict[str, Any]) -> bool:
    lab = normalizar(_row_lab(row))
    return (
        "PROD FOCO" in lab
        or "PRODUTO FOCO" in lab
        or "PROD. FOCO" in str(_row_lab(row)).upper()
        or normalizar(row.get("__CANAL") or "") == "PRODUTO FOCO"
        or lab == "BRG SUPLEMENTOS"
        or lab.startswith("BRG SUPLEMENTOS ")
    )


def _competence_key(value: str) -> tuple[int, int, str]:
    text = str(value or "").strip()
    parts = text.replace("-", "/").split("/")
    if len(parts) == 2:
        try:
            first, second = int(parts[0]), int(parts[1])
            if second > 1000:
                return second, first, text
            if first > 1000:
                return first, second, text
        except ValueError:
            pass
    return 0, 0, text


def _current_competence(payload: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    values: set[str] = set()
    for value in payload.get("competencias") or []:
        if str(value or "").strip():
            values.add(str(value).strip())
    for row in rows:
        value = _row_competence(row)
        if value:
            values.add(value)
    return max(values, key=_competence_key) if values else ""


def _special_key(lab: str) -> str | None:
    key = normalizar(lab)
    if key == "HERBAMED" or key.startswith("HERBAMED "):
        return "HERBAMED"
    if key == "NATULAB" or key.startswith("NATULAB "):
        return "NATULAB"
    return None


def _build_campaign_rows(
    payload: dict[str, Any],
    competencia: str,
    *,
    general_sales_getter=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    source = payload.get("dadosTelevendas")
    raw_rows = source if isinstance(source, list) else []
    grouped: dict[str, dict[str, Any]] = {}

    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        if competencia and _row_competence(raw) != competencia:
            continue
        if _is_non_sales_row(raw):
            continue
        lab = _row_lab(raw)
        if not lab:
            continue
        key = normalizar(lab)
        item = grouped.setdefault(key, {
            "laboratorio": lab,
            "objetivo": 0.0,
            "venda": 0.0,
            "linhas": 0,
        })
        item["objetivo"] += _num(_row_value(raw, "__OBJETIVO", "objetivo", "OBJETIVO"))
        item["venda"] += _num(_row_value(raw, "__VENDA", "venda", "VENDA"))
        item["linhas"] += 1

    warnings: list[str] = []
    result: list[dict[str, Any]] = []
    getter = general_sales_getter or industries_module._general_sales_snapshot

    for item in grouped.values():
        lab = str(item["laboratorio"])
        objective = round(float(item["objetivo"]), 2)
        sale: float | None = round(float(item["venda"]), 2)
        special = _special_key(lab)
        scope = "TELEVENDAS"

        if special:
            objective = SPECIAL_OBJECTIVES[special]
            general = getter(lab, competencia)
            sale = round(float(general["venda"]), 2) if isinstance(general, dict) and general.get("venda") is not None else None
            scope = "VENDA_GERAL"
            if sale is None:
                warnings.append(
                    f"{special}: Venda Geral indisponível. O valor de Televendas não foi usado como substituto."
                )

        percentage = round((sale / objective * 100.0), 2) if sale is not None and objective > 0 else None
        missing = round(max(objective - sale, 0.0), 2) if sale is not None and objective > 0 else None
        excess = round(max(sale - objective, 0.0), 2) if sale is not None and objective > 0 else None
        if objective <= 0:
            status = "SEM_OBJETIVO"
        elif sale is None:
            status = "SEM_VENDA_GERAL"
        elif sale >= objective:
            status = "META_ATINGIDA"
        else:
            status = "ABAIXO_META"

        result.append({
            "laboratorio": lab,
            "objetivo": objective,
            "venda": sale,
            "atingimento": percentage,
            "falta": missing,
            "excedente": excess,
            "status": status,
            "escopo": scope,
            "escopoLabel": (
                "Venda Geral · vendedores + televendas + diretoria"
                if scope == "VENDA_GERAL"
                else "Somente Televendas"
            ),
            "regraEspecial": bool(special),
            "quantidadeTelevendas": int(item["linhas"]),
        })

    result.sort(key=lambda x: (
        x["atingimento"] is None,
        x["atingimento"] if x["atingimento"] is not None else 10**9,
        normalizar(x["laboratorio"]),
    ))
    return result, warnings


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "campanhas": len(rows),
        "metaAtingida": sum(1 for row in rows if row.get("status") == "META_ATINGIDA"),
        "abaixoMeta": sum(1 for row in rows if row.get("status") == "ABAIXO_META"),
        "semObjetivo": sum(1 for row in rows if row.get("status") == "SEM_OBJETIVO"),
        "dadosIncompletos": sum(1 for row in rows if row.get("venda") is None),
    }


@router.get("/minhas-campanhas", include_in_schema=False)
async def my_campaigns_page(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _profile_from_session(session)
    return FileResponse(
        PAGE_FILE,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/minhas-campanhas/launcher.js", include_in_schema=False)
async def my_campaigns_launcher(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _profile_from_session(session)
    return FileResponse(
        LAUNCHER_FILE,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/minhas-campanhas/api/acesso")
async def my_campaigns_access(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _profile_from_session(session)
    return {
        "sucesso": True,
        "usuario": str(profile.get("usuario") or profile.get("sub") or ""),
        "tipo": str(profile.get("tipo") or ""),
    }


@router.get("/minhas-campanhas/api/dados")
async def my_campaigns_data(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _profile_from_session(session)
    try:
        # Mesma fotografia publicada e mesmo timestamp exibido nas Parciais Mensais.
        payload, cache_row = await home_publication_cache_get(modulo="MENSAL", settings=settings)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="A base mensal das campanhas está temporariamente indisponível.") from exc

    raw = payload.get("dadosTelevendas") if isinstance(payload.get("dadosTelevendas"), list) else []
    rows_for_comp = [row for row in raw if isinstance(row, dict)]
    competencia = _current_competence(payload, rows_for_comp)
    rows, warnings = _build_campaign_rows(payload, competencia)
    if not rows:
        raise HTTPException(status_code=503, detail="Nenhuma campanha de Televendas foi localizada na competência atual.")

    return {
        "sucesso": True,
        "usuario": str(profile.get("usuario") or profile.get("sub") or ""),
        "tipo": str(profile.get("tipo") or ""),
        "competencia": competencia,
        "atualizadoEm": str(cache_row.get("atualizado_em") or ""),
        "resumo": _build_summary(rows),
        "campanhas": rows,
        "avisos": warnings,
    }
