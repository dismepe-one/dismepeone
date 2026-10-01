from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from .monthly_competence_guard import preferred_operational_competence


_INSTALLED = False
_OPERATIONAL_COMPETENCE: ContextVar[str] = ContextVar(
    "dismepe_industry_operational_competence",
    default="",
)


def _normalize_competence(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text[2] == "/" and text[:2].isdigit() and text[3:].isdigit():
        month = int(text[:2])
        if 1 <= month <= 12:
            return f"{month:02d}/{int(text[3:]):04d}"
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        month = int(text[5:])
        if 1 <= month <= 12:
            return f"{month:02d}/{int(text[:4]):04d}"
    return ""


def _current_snapshot_for_lab(industries_module, lab: str) -> dict[str, Any] | None:
    """Lê a fotografia mais recente do OBJETIVO X VENDA sem confiar no mês do relógio.

    O sincronizador histórico carimbava a competência com datetime.now(). Na virada
    do mês isso pode marcar 10/2026 mesmo quando o arquivo ainda representa a
    operação de 09/2026. A competência correta é decidida pelo motor mensal; aqui
    usamos somente os valores mais recentes do arquivo oficial enquanto essa
    competência estiver operacional.
    """
    path = getattr(industries_module, "GENERAL_SALES_FILE", None)
    if path is None or not path.exists():
        return None
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(snapshot, dict):
        return None
    rows = snapshot.get("linhas")
    if not isinstance(rows, list):
        return None

    all_labs = industries_module._is_all_labs_request(lab)
    lab_keys = industries_module._portal_source_keys(lab)
    total = 0.0
    objective = 0.0
    positivity = 0.0
    found = False
    has_objective = False
    has_positivity = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_lab = (
            row.get("laboratorio")
            or row.get("lab")
            or row.get("fornecedor")
            or row.get("industria")
        )
        if not all_labs and industries_module._lab_key(row_lab) not in lab_keys:
            continue

        raw_value = row.get("venda_total")
        if raw_value is None:
            raw_value = row.get("venda")
        if raw_value is None:
            raw_value = row.get("total")
        if raw_value is None:
            raw_value = row.get("faturamento")
        if raw_value in (None, ""):
            continue
        total += industries_module._num(raw_value)
        found = True

        raw_obj = row.get("objetivo_total")
        if raw_obj is None:
            raw_obj = row.get("objetivo")
        if raw_obj not in (None, ""):
            objective += industries_module._num(raw_obj)
            has_objective = True

        raw_pos = row.get("positivacao_total")
        if raw_pos is None:
            raw_pos = row.get("positivacao")
        if raw_pos is None:
            raw_pos = row.get("positivação")
        if raw_pos is None:
            raw_pos = row.get("positivados")
        if raw_pos not in (None, ""):
            positivity += industries_module._num(raw_pos)
            has_positivity = True

    if not found:
        return None
    return {
        "venda": round(total, 2),
        "objetivo": round(objective, 2) if has_objective else None,
        "positivacao": int(round(positivity)) if has_positivity else None,
        "atualizadoEm": str(snapshot.get("gerado_em") or snapshot.get("atualizado_em") or ""),
        "arquivoOrigem": str(snapshot.get("fonte") or snapshot.get("arquivo_origem") or ""),
    }


def install_industry_operational_sales_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from . import industries as industries_module
    except Exception:
        return

    original_all = getattr(industries_module, "_all_competences", None)
    original_general = getattr(industries_module, "_general_sales_snapshot", None)
    if not callable(original_all) or not callable(original_general):
        return

    if not getattr(original_all, "__dismepe_sales_operational_context__", False):
        def tracked_all_competences(payload, rows):
            comps = list(original_all(payload, rows))
            preferred = preferred_operational_competence(payload)
            _OPERATIONAL_COMPETENCE.set(preferred)
            if preferred and preferred in comps:
                comps = [preferred] + [item for item in comps if item != preferred]
            return comps

        tracked_all_competences.__dismepe_sales_operational_context__ = True
        tracked_all_competences.__wrapped__ = original_all
        industries_module._all_competences = tracked_all_competences

    if not getattr(original_general, "__dismepe_current_sales_for_operational__", False):
        def operational_general_sales_snapshot(lab: str, competencia: str):
            requested = _normalize_competence(competencia)
            operational = _normalize_competence(_OPERATIONAL_COMPETENCE.get())

            # Somente a competência operacional pode reaproveitar a fotografia
            # mais recente. Competências históricas continuam no fluxo anterior.
            if requested and operational and requested == operational:
                current = _current_snapshot_for_lab(industries_module, lab)
                if current is not None:
                    return current

            return original_general(lab, competencia)

        operational_general_sales_snapshot.__dismepe_current_sales_for_operational__ = True
        operational_general_sales_snapshot.__wrapped__ = original_general
        industries_module._general_sales_snapshot = operational_general_sales_snapshot

    _INSTALLED = True
