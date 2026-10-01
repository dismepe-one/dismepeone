from __future__ import annotations

import json
from typing import Any

from . import main as main_module


_INSTALLED = False
_ORIGINAL_SCOPE = None


def _comp_value(value: Any) -> str:
    if isinstance(value, dict):
        value = (
            value.get("competencia")
            or value.get("COMPETENCIA")
            or value.get("Competência")
            or value.get("Competencia")
            or ""
        )
    text = str(value or "").strip()
    if len(text) == 7 and text[2] == "/" and text[:2].isdigit() and text[3:].isdigit():
        month = int(text[:2])
        if 1 <= month <= 12:
            return f"{month:02d}/{int(text[3:]):04d}"
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        month = int(text[5:])
        if 1 <= month <= 12:
            return f"{month:02d}/{int(text[:4]):04d}"
    if len(text) == 7 and text[2] == "-" and text[:2].isdigit() and text[3:].isdigit():
        month = int(text[:2])
        if 1 <= month <= 12:
            return f"{month:02d}/{int(text[3:]):04d}"
    return ""


def _comp_order(comp: str) -> int:
    normalized = _comp_value(comp)
    if not normalized:
        return 0
    month, year = normalized.split("/")
    return int(year) * 100 + int(month)


def _row_comp(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return _comp_value(
        row.get("__COMPETENCIA")
        or row.get("competencia")
        or row.get("COMPETENCIA")
        or row.get("Competencia")
        or row.get("Competência")
        or ""
    )


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _objective_value(row: dict[str, Any]) -> float:
    for key in (
        "__OBJETIVO",
        "objetivo",
        "OBJETIVO",
        "Objetivo",
        "meta",
        "META",
        "Meta",
    ):
        if key in row:
            return _number(row.get(key))
    return 0.0


def _objective_declared(row: dict[str, Any]) -> bool:
    return any(
        key in row
        for key in (
            "__OBJETIVO",
            "objetivo",
            "OBJETIVO",
            "Objetivo",
            "meta",
            "META",
            "Meta",
        )
    )


def _metadata(payload: dict[str, Any], comp: str) -> dict[str, Any]:
    for key in ("competenciasDisponiveis", "competencias", "gestaoCampanhasMensaisLista"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict) and _comp_value(item) == comp:
                return item
    return {}


def _rows(payload: dict[str, Any], key: str, comp: str) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [
        row
        for row in values
        if isinstance(row, dict) and _row_comp(row) == comp
    ]


def _has_business_days(payload: dict[str, Any], meta: dict[str, Any], comp: str) -> bool:
    days_map = payload.get("diasUteisPorCompetencia")
    if isinstance(days_map, dict) and comp in days_map:
        return True
    return (
        "diasUteisRestantes" in meta
        or "dias" in meta
        or "diasUteis" in meta
    )


def _competence_ready(payload: dict[str, Any], comp: str) -> bool:
    meta = _metadata(payload, comp)
    if not meta:
        return False

    publication_status = str(meta.get("publicacaoStatus") or "").strip().upper()
    if publication_status and publication_status != "PUBLICADA":
        return False

    vendors = _rows(payload, "dadosVendedores", comp)
    televendas = _rows(payload, "dadosTelevendas", comp)
    if not vendors or not televendas:
        return False

    total_rows = len(vendors) + len(televendas)
    expected_rows = int(_number(meta.get("baseRegistros")))
    if expected_rows > 0 and total_rows < expected_rows:
        return False

    if "regrasRegistros" in meta and _number(meta.get("regrasRegistros")) <= 0:
        return False

    if not _has_business_days(payload, meta, comp):
        return False

    if not all(_objective_declared(row) for row in vendors + televendas):
        return False

    if not any(_objective_value(row) > 0 for row in vendors):
        return False
    if not any(_objective_value(row) > 0 for row in televendas):
        return False

    return True


def _candidate_competences(payload: dict[str, Any]) -> list[str]:
    values: set[str] = set()

    for key in ("competenciasDisponiveis", "competencias", "gestaoCampanhasMensaisLista"):
        rows = payload.get(key)
        if isinstance(rows, list):
            for item in rows:
                comp = _comp_value(item)
                if comp:
                    values.add(comp)

    for key in ("dadosVendedores", "dadosTelevendas"):
        rows = payload.get(key)
        if isinstance(rows, list):
            for row in rows:
                comp = _row_comp(row)
                if comp:
                    values.add(comp)

    days_map = payload.get("diasUteisPorCompetencia")
    if isinstance(days_map, dict):
        for value in days_map:
            comp = _comp_value(value)
            if comp:
                values.add(comp)

    return sorted(values, key=_comp_order, reverse=True)


def preferred_operational_competence(payload: dict[str, Any]) -> str:
    """Retorna a competência mais recente comprovadamente pronta para operação.

    Uma competência nova só vira padrão depois de existir uma fotografia
    publicada com os dois canais, base completa, regras, dias úteis e objetivos.
    Assim a simples mudança do calendário ou a criação parcial do mês seguinte
    não desmonta a competência anterior ainda em uso.
    """
    if not isinstance(payload, dict):
        return ""
    for comp in _candidate_competences(payload):
        if _competence_ready(payload, comp):
            return comp
    return ""


def _general_sales_from_snapshot(industries_module, snapshot: Any, lab: str, competencia: str):
    if not isinstance(snapshot, dict):
        return None
    rows = snapshot.get("linhas")
    if not isinstance(rows, list):
        return None

    target_comp = _comp_value(competencia)
    snapshot_comp = _comp_value(snapshot.get("competencia"))
    if target_comp and snapshot_comp and snapshot_comp != target_comp:
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
        row_comp = _comp_value(row.get("competencia") or row.get("mes") or row.get("periodo") or "")
        if target_comp and row_comp and row_comp != target_comp:
            continue
        row_lab = row.get("laboratorio") or row.get("lab") or row.get("fornecedor") or row.get("industria")
        if not all_labs and industries_module._lab_key(row_lab) not in lab_keys:
            continue

        raw_value = row.get("venda_total")
        if raw_value is None:
            raw_value = row.get("venda")
        if raw_value is None:
            raw_value = row.get("total")
        if raw_value is None:
            raw_value = row.get("faturamento")
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


def _install_industries_competence_guard() -> None:
    """Mantém a tela Indústrias na mesma competência operacional do mensal.

    A base geral do portal é sincronizada pelo Drive e historicamente era
    carimbada com o mês do relógio. Se o calendário virar antes de a nova
    competência mensal estar pronta, usamos a fotografia histórica que pertence
    à competência ainda operacional, sem alterar nem recalcular os números.
    """
    try:
        from . import industries as industries_module
    except Exception:
        return

    original_all = getattr(industries_module, "_all_competences", None)
    if callable(original_all) and not getattr(original_all, "__dismepe_operational_order__", False):
        def operational_all_competences(payload, rows):
            comps = list(original_all(payload, rows))
            preferred = preferred_operational_competence(payload)
            if preferred and preferred in comps:
                comps = [preferred] + [item for item in comps if item != preferred]
            return comps

        operational_all_competences.__dismepe_operational_order__ = True
        operational_all_competences.__wrapped__ = original_all
        industries_module._all_competences = operational_all_competences

    original_general = getattr(industries_module, "_general_sales_snapshot", None)
    if callable(original_general) and not getattr(original_general, "__dismepe_competence_history_fallback__", False):
        def guarded_general_sales_snapshot(lab: str, competencia: str):
            current = original_general(lab, competencia)
            if current is not None:
                return current

            history_path = getattr(industries_module, "GENERAL_SALES_HISTORY_FILE", None)
            if history_path is None or not history_path.exists():
                return None
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
            except Exception:
                return None
            updates = history.get("atualizacoes") if isinstance(history, dict) else None
            if not isinstance(updates, list):
                return None
            for snapshot in updates:
                fallback = _general_sales_from_snapshot(industries_module, snapshot, lab, competencia)
                if fallback is not None:
                    return fallback
            return None

        guarded_general_sales_snapshot.__dismepe_competence_history_fallback__ = True
        guarded_general_sales_snapshot.__wrapped__ = original_general
        industries_module._general_sales_snapshot = guarded_general_sales_snapshot


def install_monthly_competence_guard() -> None:
    global _INSTALLED, _ORIGINAL_SCOPE
    if _INSTALLED:
        return

    original = main_module.scope_mensal_dashboard
    if not callable(original):
        return

    _ORIGINAL_SCOPE = original

    def guarded_scope(payload, profile, competencia=None):
        # Consulta explícita da Gestão/Histórico continua livre para qualquer
        # competência, inclusive outubro ainda em preparação.
        explicit = _comp_value(competencia)
        if explicit:
            return original(payload, profile, competencia=explicit)

        preferred = preferred_operational_competence(payload)
        if preferred:
            # Ao passar a competência como explícita para o escopo já existente,
            # linhas, regras, campanha atual, objetivos e dias úteis permanecem
            # coerentes na mesma competência.
            return original(payload, profile, competencia=preferred)

        # Compatibilidade com fotografias antigas: sem metadados suficientes
        # para comprovar uma competência completa, não bloqueia o painel.
        return original(payload, profile, competencia=competencia)

    guarded_scope.__dismepe_monthly_competence_guard__ = True
    guarded_scope.__wrapped__ = original
    main_module.scope_mensal_dashboard = guarded_scope
    _install_industries_competence_guard()
    _INSTALLED = True
