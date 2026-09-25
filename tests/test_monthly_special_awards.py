"""Testes puros das regras especiais mensais (sem acesso a dados reais)."""
from decimal import Decimal
import pytest

from api.monthly_special_awards import (
    SpecialAwardError, channel, competence, component, globo,
    herbamed_clients, herbamed_general, money, records,
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
