from __future__ import annotations

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
    _INSTALLED = True
