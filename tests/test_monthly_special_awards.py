"""Testes puros das regras especiais mensais (sem acesso a dados reais)."""
from decimal import Decimal
import pytest

from api.monthly_special_awards import (
    SpecialAwardError, channel, competence, component, globo,
    herbamed_clients, herbamed_general, integral_points, money, records,
)


def test_competencia_google_sheets_serial_e_canal():
    assert competence(46274) == "09/2026"
    assert channel("Eletrônico") == "VENDEDOR"


def test_globo_clientes_unicos_e_gatilho():
    rule = {"id": "globo", "metrica": "POSITIVACAO_CLIENTES"}
    team = records([["VENDEDOR_TELEVENDAS", "TIPO", "META_CLIENTES", "PREMIO"],
                    ["ANA", "VENDEDOR", 2, 50]])
    clients = records([["Vendedor", "Cód. Cliente", "Pedidos Por", "Positivação", "Data"],
                       ["ANA", "01", "Eletrônico", 1, 46274],
                       ["ANA", "01", "Eletrônico", 1, 46275],
                       ["ANA", "02", "Eletrônico", 1, 46275],
                       ["ANA", "03", "Eletrônico", 1, None]])
    result = globo("09/2026", "VENDEDOR", "ANA", rule, team, clients)
    assert result["realizado"] == 2
    assert result["premio"] == 50
    assert not result["pendente"]


def test_globo_meta_ausente_nao_premia_zero_silenciosamente():
    result = globo("09/2026", "VENDEDOR", "ANA", {}, [], [])
    assert result["pendente"] and result["realizado"] is None


def test_herbamed_meta_multipla_e_cnpj_fallback():
    rule = {"id": "herb", "metrica": "POSITIVACAO_CLIENTES"}
    base = records([["Vendedor", "Cód. Cliente", "CNPJ", "Data", "Pedidos Por"],
                    ["ANA", "100", "", 46274, "Eletrônico"],
                    ["ANA", "100", "", 46275, "Eletrônico"],
                    ["ANA", "", "200", 46275, "Eletrônico"],
                    ["ANA", "", "300", 46275, "Eletrônico"],
                    ["ANA", "400", "", None, "Eletrônico"]])
    result = herbamed_clients("09/2026", "VENDEDOR", "ANA", rule, Decimal(1), Decimal(5), base)
    assert result["realizado"] == 3
    assert result["premio"] == 15


def test_herbamed_manual_nao_inventa_valor():
    result = herbamed_general({}, "POSITIVACAO_GERAL", Decimal(200), Decimal(100), {})
    assert result["pendente"] and result["realizado"] is None


def test_herbamed_manual_preserva_gatilho():
    result = herbamed_general({}, "POSITIVACAO_GERAL", Decimal(200), Decimal(100),
                              {"POSITIVACAO_GERAL_MANUAL": 335})
    assert result["premio"] == 100


def test_valor_financeiro_invalido_bloqueia():
    with pytest.raises(SpecialAwardError):
        money("erro")


def test_regra_geral_desconhecida_bloqueia():
    with pytest.raises(SpecialAwardError):
        herbamed_general({}, "DESCONHECIDO", Decimal(1), Decimal(1), {})


def test_integral_pontos_individual_faixas_e_gatilho_geral():
    rule = {"id": "brg", "metrica": "PONTUACAO_PRODUTO",
            "exigeSomaLaboratorio": True, "somaLabMinimo": 12}
    products = records([["Cód. Produto", "PONTOS"], ["6183", 3]])
    tiers = records([["PONTOS", "PREMIO"], [6, "R$ 50,00"], [12, "R$ 100,00"]])
    movements = records([["Data", "Pedidos Por", "Vendedor", "Cód. Produto",
                          "Total Unidade", "Faturado"],
                         [46274, "Eletrônico", "ANA", "6183", 4, "SIM"],
                         [46274, "Eletrônico", "OUTRO", "6183", 1, "SIM"],
                         [None, "Eletrônico", "ANA", "6183", 9, "SIM"]])
    result = integral_points("09/2026", "VENDEDOR", "ANA", rule, movements, products, tiers)
    assert result["realizado"] == 12
    assert result["premio"] == 100
    assert result["pontosGerais"] == 15
    assert result["totalProdutosPositivados"] == 1
    assert not result["pendente"]


def test_integral_gatilho_geral_bloqueia_faixa_individual():
    rule = {"exigeSomaLaboratorio": True, "somaLabMinimo": 20}
    movements = records([["Data", "Pedidos Por", "Vendedor", "Cód. Produto",
                          "Total Unidade", "Faturado"],
                         [46274, "Eletrônico", "ANA", "6183", 4, "SIM"]])
    products = records([["Cód. Produto", "PONTOS"], ["6183", 3]])
    tiers = records([["PONTOS", "PREMIO"], [6, 50]])
    result = integral_points("09/2026", "VENDEDOR", "ANA", rule, movements, products, tiers)
    assert result["realizado"] == 12
    assert result["premio"] == 0
    assert result["gatilhoGeralOK"] is False


def test_integral_base_incompleta_marca_pendente():
    rule = {"exigeSomaLaboratorio": True, "somaLabMinimo": 5}
    movements = records([["Data", "Pedidos Por", "Vendedor", "Cód. Produto",
                          "Total Unidade", "Faturado"],
                         [None, "Eletrônico", "ANA", "6183", 4, "SIM"]])
    products = records([["Cód. Produto", "PONTOS"], ["6183", 3]])
    tiers = records([["PONTOS", "PREMIO"], [6, 50]])
    result = integral_points("09/2026", "VENDEDOR", "ANA", rule, movements, products, tiers)
    assert result["pendente"] and result["realizado"] is None
