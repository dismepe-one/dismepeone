"""No external access or SQL mutation; special metric parity and isolation."""
import copy

import pytest

from api.monthly_special_metrics import calculate, SpecialMetricsError
from api.home_publication import _special_metrics_changed, _partial_sales_changed


def rows(name, lab, metric, achieved, extra=None):
    part = {"metrica": metric, "realizado": achieved, "meta": 10,
            "premio": 0, "premioConfigurado": 50, "criterio": "Indicador"}
    if extra:
        part.update(extra)
    return {"__COMPETENCIA": "09/2026", "__COLABORADOR": name,
            "__LAB": lab, "__VENDA": 120, "__OBJETIVO": 200, "__linha": 3,
            "Premiação": 0, "metricasParcial": {"valor": 0, "pendente": False,
            "regra": {"valor": 0}, "componentes": [part]}}


def snapshot():
    return {"competencias": [{"competencia": "09/2026", "status": "ATUAL",
            "linkDrive": "https://docs.google.com/spreadsheets/d/17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4/edit"}],
        "dadosVendedores": [
            rows("ANA", "GLOBO", "POSITIVACAO_CLIENTES", 1),
            rows("ANA", "HERBAMED", "POSITIVACAO_CLIENTES", 1),
            rows("ANA", "BRG SUPLEMENTOS", "PONTUACAO_PRODUTO", 1,
                 {"metaPontosGerais": 400, "produtosPositivados": []})],
        "dadosTelevendas": [
            rows("BIA", "GLOBO", "POSITIVACAO_CLIENTES", 1),
            rows("BIA", "HERBAMED", "POSITIVACAO_CLIENTES", 1),
            rows("BIA", "BRG SUPLEMENTOS", "PONTUACAO_PRODUTO", 1,
                 {"metaPontosGerais": 400, "produtosPositivados": []})],
        "regrasPremiacao": [{"regra": "ORIGINAL"}]}


def sources():
    return {
        "GLOBO_CLIENTES": [
            ["ANA", "100", "Cliente", "Eletrônico", "1", "24/09/2026"],
            ["ANA", "101", "Cliente", "Eletrônico", "1", "25/09/2026"],
            ["ANA", "100", "Cliente", "Eletrônico", "1", "25/09/2026"],
            ["BIA", "200", "Cliente", "Televendas", "1", "25/09/2026"],
            ["BIA", "201", "Cliente", "Televendas", "1", "25/09/2026"],
            ["BIA", "999", "Cliente", "Televendas", "1", "25/08/2026"]],
        "METRICA_GLOBO": [
            ["ANA", "VENDEDORES", "2", "R$ 150,00"],
            ["BIA", "TELEVENDAS", "2", "R$ 70,00"]],
        "HERB_COM": [
            ["ANA", "C", "500", "", "HERBAMED", "X", "123", "25/09/2026", "1", "12", "Eletrônico"],
            ["ANA", "C", "500", "", "HERBAMED", "X", "123", "24/09/2026", "1", "12", "Eletrônico"],
            ["BIA", "C", "600", "", "HERBAMED", "X", "123", "25/09/2026", "1", "12", "Televendas"]],
        "INT_PONTOS": [
            ["25/09/2026", "Eletrônico", "ANA", "5772", "20", "SIM"],
            ["25/09/2026", "Televendas", "BIA", "5772", "10", "SIM"],
            ["25/09/2026", "Televendas", "BIA", "5772", "", "SIM"],
            ["25/08/2026", "Eletrônico", "ANA", "5772", "99", "SIM"]],
        "INTEGRAL_PRODUTOS": [["5772", "PRODUTO", "1"]],
        "INTEGRAL_FAIXAS": [["20", "50"], ["40", "100"]],
    }


def test_metrics_recalculate_only_open_month_preserve_commercial_financial():
    base, src = snapshot(), sources()
    copy_before, source_before = copy.deepcopy(base), copy.deepcopy(src)
    out = calculate(base, src)
    assert out["dadosVendedores"][0]["metricasParcial"]["componentes"][0]["realizado"] == 2
    assert out["dadosVendedores"][0]["Premiação"] == 150
    assert out["dadosTelevendas"][0]["Premiação"] == 70
    assert out["dadosVendedores"][1]["metricasParcial"]["componentes"][0]["realizado"] == 1
    assert out["dadosVendedores"][2]["metricasParcial"]["componentes"][0]["realizado"] == 20
    assert out["dadosTelevendas"][2]["metricasParcial"]["componentes"][0]["realizado"] == 10
    assert out["dadosVendedores"][2]["metricasParcial"]["componentes"][0]["pontosGerais"] == 30
    assert out["dadosVendedores"][2]["Premiação"] == 0  # general gate of 400
    assert out["dadosVendedores"][2]["metricasParcial"]["componentes"][0]["totalProdutosPositivados"] == 1
    assert out["dadosVendedores"][0]["__VENDA"] == 120
    assert out["regrasPremiacao"] == base["regrasPremiacao"]
    assert base == copy_before and src == source_before
    assert _special_metrics_changed({"mensal": base}, out)
    assert not _partial_sales_changed({"mensal": base}, out)
    assert not _special_metrics_changed({"mensal": out}, out)


def test_unchanged_historical_entries():
    base = snapshot()
    older = rows("ANA", "GLOBO", "POSITIVACAO_CLIENTES", 8)
    older["__COMPETENCIA"] = "08/2026"
    base["dadosVendedores"].append(older)
    result = calculate(base, sources())
    assert result["dadosVendedores"][-1] == older


def test_missing_source_or_closed_month_fails_without_data_mutation():
    base = snapshot()
    before = copy.deepcopy(base)
    broken = sources()
    broken["METRICA_GLOBO"] = []
    with pytest.raises(SpecialMetricsError):
        calculate(base, broken)
    assert base == before
    base["competencias"][0]["fechada"] = True
    with pytest.raises(SpecialMetricsError):
        calculate(base, sources())


def test_integer_points_and_unique_client():
    base, src = snapshot(), sources()
    src["INT_PONTOS"].append(["25/09/2026", "Eletrônico", "ANA", "5772", "2.5", "SIM"])
    src["HERB_COM"].append(src["HERB_COM"][0])
    out = calculate(base, src)
    assert out["dadosVendedores"][2]["metricasParcial"]["componentes"][0]["realizado"] == 20
    assert out["dadosVendedores"][1]["metricasParcial"]["componentes"][0]["realizado"] == 1
