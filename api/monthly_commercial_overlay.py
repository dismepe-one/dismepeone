"""Overlay comercial por competência. Nenhum cálculo ou registro financeiro é modificado."""
from __future__ import annotations

import copy
from decimal import Decimal

from .cache_reads import CacheReadError, cache_get
from .monthly_commercial_live import CHANNELS, current_source, CommercialSyncError


def _rows_for_comp(snapshot, key, competence):
    return [row for row in snapshot.get(key, []) if isinstance(row, dict)
            and str(row.get("__COMPETENCIA") or row.get("competencia") or "") == competence]


def _commercial_copy(previous, incoming, key, comp):
    row = copy.deepcopy(previous) if previous else {}
    objective = float(incoming["__OBJETIVO"])
    sale = float(incoming["__VENDA"])
    if previous and (str(previous.get("__COLABORADOR") or "") != incoming["__COLABORADOR"]
                     or str(previous.get("__LAB") or "") != incoming["__LAB"]):
        raise ValueError("Identidade de linha divergente.")
    row.update({
        "__COMPETENCIA": comp, "competencia": comp,
        "__COLABORADOR": incoming["__COLABORADOR"], "__LAB": incoming["__LAB"],
        "__OBJETIVO": objective, "__VENDA": sale,
        "__TEM_FOCO": incoming["__TEM_FOCO"],
        "__CODIGO_FOCO": incoming["__CODIGO_FOCO"],
        "__OBJETIVO_FOCO": incoming["__OBJETIVO_FOCO"],
        "__VENDA_FOCO": incoming["__VENDA_FOCO"],
        "Meta": objective, "Objetivo": objective, "objetivo": objective,
        "Venda": sale, "Vendas": sale, "Realizado": sale, "venda": sale,
        "VENDA F.": objective - sale,
        "%": sale / objective if objective else 0,
        "colab": incoming["__COLABORADOR"], "lab": incoming["__LAB"],
    })
    if not previous:
        row.update({"__linha": incoming["__linha"], "__aba": incoming["__aba"],
                    "__CANAL": incoming["__CANAL"], "__canal": incoming["__CANAL"],
                    "tipo": "VENDEDOR" if key == "dadosVendedores" else "TELEVENDAS",
                    "Premiação": "", "metricaPendente": True})
        row["Vendedor" if key == "dadosVendedores" else "Televendas"] = incoming["__COLABORADOR"]
        row["Laboratório"] = incoming["__LAB"]
    elif objective != previous.get("__OBJETIVO") or sale != previous.get("__VENDA"):
        row["premiacaoComBaseAnterior"] = True
    return row


def overlay_commercial(original, original_row, commercial, commercial_row, baseline_row=None):
    """Adiciona somente números comerciais ao payload que já passou pela autorização de leitura."""
    data = copy.deepcopy(original)
    comp, sheet_id = current_source(data)
    baseline_time = str((baseline_row or original_row).get("atualizado_em") or "")
    if (commercial.get("competencia") != comp
            or commercial.get("sheetId") != sheet_id
            or str(commercial.get("baseAtualizadoEm") or "") != baseline_time):
        return original, original_row
    for key in CHANNELS:
        incoming = commercial.get(key)
        if not isinstance(incoming, list) or not incoming:
            return original, original_row
        if any(not isinstance(row, dict) or row.get("__COMPETENCIA") != comp for row in incoming):
            return original, original_row
        old = _rows_for_comp(data, key, comp)
        mapped = {str(row.get("__linha")): row for row in old}
        result = []
        used = set()
        try:
            for row in incoming:
                line = str(row["__linha"])
                if line in used:
                    return original, original_row
                used.add(line)
                result.append(_commercial_copy(mapped.get(line), row, key, comp))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return original, original_row
        data[key] = [row for row in data[key]
                     if str(row.get("__COMPETENCIA") or row.get("competencia") or "") != comp] + result
    data["fonteDadosComerciais"] = "POSTGRESQL_MENSAL_COMERCIAL"
    data["financeiro"] = "CALCULO_LEGADO_PRESERVADO"
    data["financeiroPendente"] = commercial.get("temDivergenciaComercial") is True
    data["versaoDadosComerciais"] = "MENSAL_COMERCIAL_SQL_V1"
    timestamp = str(commercial_row.get("atualizado_em") or "")
    if not timestamp:
        return original, original_row
    row_copy = dict(original_row)
    row_copy["atualizado_em"] = timestamp
    row_copy["atualizado_em_financeiro"] = original_row.get("atualizado_em")
    return data, row_copy


async def monthly_commercial_overlay(*, payload, row, settings):
    try:
        commercial, commercial_row = await cache_get(modulo="MENSAL_COMERCIAL", settings=settings)
        baseline, baseline_row = await cache_get(modulo="MENSAL", settings=settings)
        if current_source(baseline) != current_source(payload):
            return payload, row
        return overlay_commercial(payload, row, commercial, commercial_row, baseline_row)
    except (CacheReadError, CommercialSyncError, ValueError, TypeError, KeyError):
        return payload, row
