"""Prévia agregada das métricas especiais mensais, isolada da publicação.

Opera sobre matrizes já lidas da MESMA revisão. Não grava no PostgreSQL.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .monthly_awards_engine import group_rows, laboratory
from .monthly_special_awards import (
    SpecialAwardError, globo, herbamed_clients, herbamed_general,
    integral_points, money, norm, records,
)

SPECIALS = {
    "GLOBO": {"POSITIVACAO_CLIENTES"},
    "HERBAMED": {"POSITIVACAO_CLIENTES", "POSITIVACAO_GERAL", "FATURAMENTO_LABORATORIO"},
    "INTEGRALMEDICA": {"PONTUACAO_PRODUTO"},
}
REQUIRED = ("METRICA_GLOBO", "GLOBO_CLIENTES", "HERBAMED_REGRAS",
            "HERB_COM", "INTEGRAL_PRODUTOS", "INTEGRAL_FAIXAS", "INT_PONTOS")


def preview_special_awards(
    snapshot: dict[str, Any], matrices: dict[str, list[list[Any]]],
    indicators: dict[str, Any], competence: str,
) -> dict[str, Any]:
    """Resumo sem nome de vendedor ou valor individual; jamais prova paridade."""
    if not isinstance(snapshot, dict) or not isinstance(matrices, dict):
        raise SpecialAwardError("Fotografia ou fontes auxiliares ausentes.")
    if any(name not in matrices for name in REQUIRED):
        raise SpecialAwardError("Não foi possível ler todas as fontes especiais.")
    rows = [
        row for key in ("dadosVendedores", "dadosTelevendas")
        for row in snapshot.get(key, [])
        if isinstance(row, dict) and row.get("__COMPETENCIA") == competence
    ]
    groups = group_rows(rows)
    raw_rules = snapshot.get("regrasPremiacao")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise SpecialAwardError("Regras oficiais ausentes.")
    aux = {name: records(matrices[name]) for name in REQUIRED}
    out = Counter()
    pending = Counter()
    for group in groups:
        lab = laboratory(group["laboratorio"])
        if lab not in SPECIALS:
            continue
        matched = [
            rule for rule in raw_rules
            if isinstance(rule, dict) and rule.get("ativo") is not False
            and rule.get("competencia") == competence
            and laboratory(rule.get("laboratorio")) == lab
            and rule.get("metrica") in SPECIALS[lab]
            and str(rule.get("canal") or "TODOS").upper() in ("TODOS", group["canal"])
        ]
        if not matched:
            continue
        for rule in matched:
            metric = rule["metrica"]
            if lab == "GLOBO":
                result = globo(
                    competence, group["canal"], group["colaborador"], rule,
                    aux["METRICA_GLOBO"], aux["GLOBO_CLIENTES"],
                )
            elif lab == "HERBAMED":
                configs = [
                    c for c in aux["HERBAMED_REGRAS"]
                    if norm(c.get("INDICADOR")) == {
                        "POSITIVACAO_CLIENTES": "CLIENTESPOSITIVADOS",
                        "POSITIVACAO_GERAL": "CLIENTESGERAL",
                        "FATURAMENTO_LABORATORIO": "VENDAGERAL",
                    }[metric]
                ]
                if len(configs) != 1:
                    pending[lab] += 1
                    out[lab] += 1
                    continue
                meta, prize = money(configs[0].get("META")), money(configs[0].get("PREMIO"))
                result = (
                    herbamed_clients(
                        competence, group["canal"], group["colaborador"], rule,
                        meta, prize, aux["HERB_COM"],
                    )
                    if metric == "POSITIVACAO_CLIENTES"
                    else herbamed_general(rule, metric, meta, prize, indicators)
                )
            else:
                result = integral_points(
                    competence, group["canal"], group["colaborador"], rule,
                    aux["INT_PONTOS"], aux["INTEGRAL_PRODUTOS"], aux["INTEGRAL_FAIXAS"],
                )
            out[lab] += 1
            if result["pendente"]:
                pending[lab] += 1
    return {
        "modo": "PREVIA_SOMENTE_LEITURA",
        "competencia": competence,
        "componentesPorLaboratorio": dict(sorted(out.items())),
        "componentesPendentesPorLaboratorio": dict(sorted(pending.items())),
        "usaParticipantesDaFotografiaAnterior": True,
        "premiacoesComparadasComMesmaRevisao": False,
        "publicacaoAutorizada": False,
    }
