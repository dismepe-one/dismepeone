"""Contratos de não-publicação do motor mensal em migração."""
import copy

import pytest

from api.monthly_render_parity import MonthlyParityError, assert_monthly_parity


def fixture_snapshot():
    return {
        "dadosVendedores": [
            {"__COMPETENCIA": "09/2026", "__COLABORADOR": "A",
             "__LAB": "HERBAMED", "__VENDA": 150, "__OBJETIVO": 200,
             "Premiação": "Pendente: faltam indicadores", "premiacao": 0,
             "metricasParcial": {"pendente": True, "componentes": []}},
        ],
        "dadosTelevendas": [
            {"__COMPETENCIA": "09/2026", "__COLABORADOR": "B",
             "__LAB": "BRG", "__VENDA": 100, "__OBJETIVO": 90,
             "__TEM_FOCO": True, "__CODIGO_FOCO": "6048",
             "Premiação": 200, "premiacao": 200},
        ],
        "regrasPremiacao": [{"id": "r1", "valor": 200, "metrica": "PONTUACAO_PRODUTO"}],
        "competencias": [{"competencia": "09/2026", "status": "ATUAL"}],
        "versaoCalculoVendedores": "V167",
        "diasUteisPorCompetencia": {"09/2026": 4},
    }


def check(a, b, r=None, c=None):
    revisions = {"planilha": "rev-1", "admin": "rev-2"}
    return assert_monthly_parity(
        a, b,
        reference_source_revisions=r if r is not None else revisions,
        candidate_source_revisions=c if c is not None else revisions,
    )


def test_identical_result_passes():
    a = fixture_snapshot()
    assert check(a, copy.deepcopy(a))["podePublicar"] is True


@pytest.mark.parametrize(("channel", "field", "new_value"), [
    ("dadosVendedores", "__VENDA", 151),
    ("dadosVendedores", "Premiação", "Pendente: outro indicador"),
    ("dadosVendedores", "metricasParcial", {"pendente": False, "componentes": []}),
    ("dadosTelevendas", "__CODIGO_FOCO", "0000"),
    ("dadosTelevendas", "premiacao", 199),
])
def test_changed_business_result_rejected(channel, field, new_value):
    old = fixture_snapshot()
    new = copy.deepcopy(old)
    new[channel][0][field] = new_value
    with pytest.raises(MonthlyParityError):
        check(old, new)


def test_source_revision_changed_rejected():
    old = fixture_snapshot()
    with pytest.raises(MonthlyParityError):
        check(old, copy.deepcopy(old), c={"planilha": "rev-3", "admin": "rev-2"})


def test_rule_changed_rejected():
    old = fixture_snapshot()
    new = copy.deepcopy(old)
    new["regrasPremiacao"][0]["valor"] = 250
    with pytest.raises(MonthlyParityError):
        check(old, new)


def test_historical_competence_changed_rejected():
    old = fixture_snapshot()
    new = copy.deepcopy(old)
    new["competencias"].append({"competencia": "08/2026", "status": "HISTORICO"})
    with pytest.raises(MonthlyParityError):
        check(old, new)
