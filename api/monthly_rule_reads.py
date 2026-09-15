from __future__ import annotations

import copy
import re
from typing import Any

from .security import normalizar


def _role(value: Any) -> str:
    return normalizar(value or "")


def _comp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    match = re.search(r"(0?[1-9]|1[0-2])\s*[/\-]\s*(20\d{2})", text)
    if match:
        return f"{int(match.group(1)):02d}/{match.group(2)}"

    match = re.search(r"(20\d{2})\s*[/\-]\s*(0?[1-9]|1[0-2])", text)
    if match:
        return f"{int(match.group(2)):02d}/{match.group(1)}"

    return text


def _can_manage_rules(profile: dict[str, Any]) -> bool:
    if _role(profile.get("tipo")) in {"ADMINISTRADOR", "ADMIN"}:
        return True

    perms = profile.get("permissoes")
    if not isinstance(perms, dict):
        return False

    return any(
        perms.get(key) is True
        for key in (
            "REGRAS_METRICAS_IMPORTAR",
            "REGRAS_PREMIACAO_VISUALIZAR",
            "REGRAS_PREMIACAO_CRIAR",
            "REGRAS_PREMIACAO_EDITAR",
            "REGRAS_PREMIACAO_EXCLUIR",
            "CAMPANHAS_MENSAIS_CRIAR",
            "CAMPANHAS_MENSAIS_EDITAR",
        )
    )


def _row_comp(row: dict[str, Any]) -> str:
    return _comp(
        row.get("__COMPETENCIA")
        or row.get("competencia")
        or row.get("Competencia")
        or row.get("Competência")
        or ""
    )


def _lab(row: dict[str, Any]) -> str:
    for key in (
        "laboratorio",
        "laboratório",
        "Laboratório",
        "Laboratorio",
        "LABORATORIO",
        "__LAB",
        "lab",
        "FORNECEDOR",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _latest_comp(payload: dict[str, Any]) -> str:
    values: list[str] = []

    for item in payload.get("competencias") if isinstance(payload.get("competencias"), list) else []:
        if isinstance(item, dict):
            value = _comp(item.get("competencia") or item.get("COMPETENCIA") or "")
        else:
            value = _comp(item)
        if value:
            values.append(value)

    if not values:
        for key in ("dadosVendedores", "dadosTelevendas", "regrasPremiacao"):
            for item in payload.get(key) if isinstance(payload.get(key), list) else []:
                if isinstance(item, dict):
                    value = _row_comp(item) if key != "regrasPremiacao" else _comp(item.get("competencia") or item.get("COMPETENCIA") or "")
                    if value:
                        values.append(value)

    def sort_key(value: str) -> tuple[int, int]:
        m = re.fullmatch(r"(\d{2})/(20\d{2})", value)
        if not m:
            return (0, 0)
        return (int(m.group(2)), int(m.group(1)))

    return max(values, key=sort_key) if values else ""


def monthly_rule_options(
    *,
    payload: dict[str, Any],
    profile: dict[str, Any],
    competencia: str | None = None,
    snapshot_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Monta as opções administrativas de Regras/Métricas pelo snapshot MENSAL.

    É deliberadamente somente leitura. As gravações continuam no fluxo legado.
    """
    if not _can_manage_rules(profile):
        raise PermissionError(
            "Você não possui permissão para administrar Regras/Métricas."
        )

    if not isinstance(payload, dict):
        raise ValueError("Snapshot MENSAL inválido.")

    comp = _comp(competencia or "") or _latest_comp(payload)

    rules_raw = (
        payload.get("regrasPremiacao")
        if isinstance(payload.get("regrasPremiacao"), list)
        else []
    )

    rules: list[dict[str, Any]] = []
    labs: set[str] = set()

    for item in rules_raw:
        if not isinstance(item, dict):
            continue
        item_comp = _comp(item.get("competencia") or item.get("COMPETENCIA") or "")
        if comp and item_comp and item_comp != comp:
            continue
        row = copy.deepcopy(item)
        rules.append(row)
        lab = _lab(row)
        if lab:
            labs.add(lab)

    base_rows: list[dict[str, Any]] = []
    for key in ("dadosVendedores", "dadosTelevendas"):
        raw = payload.get(key) if isinstance(payload.get(key), list) else []
        for item in raw:
            if not isinstance(item, dict):
                continue
            item_comp = _row_comp(item)
            if comp and item_comp and item_comp != comp:
                continue
            if comp and not item_comp:
                # Linhas sem competência só entram se o snapshot não tiver
                # competência selecionada; evita misturar bases antigas.
                continue
            base_rows.append(item)
            lab = _lab(item)
            if lab:
                labs.add(lab)

    row = snapshot_row if isinstance(snapshot_row, dict) else {}

    return {
        "sucesso": True,
        "competencia": comp,
        "laboratorios": sorted(labs, key=lambda x: normalizar(x)),
        "regrasExistentes": rules,
        "baseMensalImportada": bool(base_rows),
        "permiteMetricasSemBaseMensal": True,
        "transporte": "FASTAPI_MENSAL_REGRAS_SNAPSHOT",
        "atualizadoEm": str(row.get("atualizado_em") or ""),
        "snapshotVersao": str(row.get("versao") or ""),
    }
