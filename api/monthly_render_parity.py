"""Bloqueio de segurança da migração mensal para processamento no Render.

O worker independente só poderá gravar MENSAL se produzir a mesma fotografia
do cálculo de referência sobre as MESMAS revisões de fonte. Nunca publica HOME.
"""
from __future__ import annotations

import collections
import json
from decimal import Decimal, InvalidOperation
from typing import Any

SOURCES = ("dadosVendedores", "dadosTelevendas")
BUSINESS_FIELDS = (
    "__COMPETENCIA", "__COLABORADOR", "__LAB", "__CANAL",
    "__OBJETIVO", "__VENDA", "__TEM_FOCO", "__CODIGO_FOCO",
    "__OBJETIVO_FOCO", "__VENDA_FOCO", "produtoFocoCampanha",
    "metricasParcial", "metricasDetalhes", "metricaPendente",
    "Premiação", "premiacao", "observacaoProdutoFoco",
)
AMOUNT_FIELDS = {
    "__OBJETIVO", "__VENDA", "__OBJETIVO_FOCO",
    "__VENDA_FOCO", "premiacao",
}


class MonthlyParityError(RuntimeError):
    pass


def _amount(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return format(Decimal(str(value)).quantize(Decimal("0.000001")), "f")
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MonthlyParityError("Valor numérico inválido na fotografia mensal.") from exc


def _normalized_row(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        raise MonthlyParityError("A fotografia mensal contém linha inválida.")
    data = {}
    for field in BUSINESS_FIELDS:
        if field not in row:
            continue
        value = row[field]
        data[field] = _amount(value) if field in AMOUNT_FIELDS else value
    # Regras especiais são estruturas do negócio, não metadados descartáveis.
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _rows(payload: dict[str, Any], key: str) -> collections.Counter[str]:
    rows = payload.get(key)
    if not isinstance(rows, list) or not rows:
        raise MonthlyParityError(f"{key} ausente ou vazio.")
    return collections.Counter(_normalized_row(row) for row in rows)


def _rules(payload: dict[str, Any]) -> collections.Counter[str]:
    rules = payload.get("regrasPremiacao")
    if not isinstance(rules, list) or not rules:
        raise MonthlyParityError("Regras de premiação ausentes.")
    return collections.Counter(
        json.dumps(rule, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        for rule in rules
        if isinstance(rule, dict)
    )


def assert_monthly_parity(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    reference_source_revisions: dict[str, str],
    candidate_source_revisions: dict[str, str],
) -> dict[str, Any]:
    """Rejeita qualquer divergência de vendas, foco, premiações, regras ou fontes.

    Os snapshots só podem ser comparados quando Google Sheets e bases auxiliares
    têm as mesmas revisões no início e no fim de ambas as execuções.
    """
    if not reference_source_revisions or reference_source_revisions != candidate_source_revisions:
        raise MonthlyParityError("As fontes mudaram entre os cálculos; comparação cancelada.")
    if not isinstance(reference, dict) or not isinstance(candidate, dict):
        raise MonthlyParityError("Fotografia mensal ausente ou inválida.")
    for key in SOURCES:
        official = _rows(reference, key)
        proposed = _rows(candidate, key)
        if official != proposed:
            raise MonthlyParityError(
                f"Resultados divergentes em {key}: cálculo do Render não autorizado para publicação."
            )
    if _rules(reference) != _rules(candidate):
        raise MonthlyParityError("Regras ou faixas de premiação divergentes.")
    for field in ("versaoCalculoVendedores", "diasUteisPorCompetencia"):
        if reference.get(field) != candidate.get(field):
            raise MonthlyParityError(f"{field} divergente.")
    # A competência histórica também precisa estar preservada integralmente.
    if reference.get("competencias") != candidate.get("competencias"):
        raise MonthlyParityError("Metadados ou competências históricas divergentes.")
    return {
        "equivalencia": True,
        "vendedores": sum(_rows(reference, "dadosVendedores").values()),
        "televendas": sum(_rows(reference, "dadosTelevendas").values()),
        "regras": sum(_rules(reference).values()),
        "fontes": len(reference_source_revisions),
        "podePublicar": True,
    }
