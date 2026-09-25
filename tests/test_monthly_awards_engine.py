"""Testes isolados do motor de premios em modo sombra (nunca publica)."""
from decimal import Decimal
import pytest

from api.monthly_awards_engine import (
    MonthlyAwardUnsupported, amount, group_rows, laboratory, rule_coverage, simple_award,
)


def _group(meta="100", venda="120", foco=False, lab="DELTA", comp="09/2026", canal="VENDEDOR"):
    return {
        "competencia": comp, "colaborador": "ANA", "laboratorio": lab, "canal": canal,
        "objetivo": Decimal(meta), "venda": Decimal(venda),
        "objetivo_foco": Decimal("10"), "venda_foco": Decimal("11"), "tem_foco": foco,
    }


def _rule(**changes):
    rule = {"id": "r1", "competencia": "09/2026", "laboratorio": "DELTA",
            "canal": "VENDEDOR", "metrica": "OBJETIVO",
            "tipo": "PERCENTUAL_OBJETIVO", "minAtingimento": 100,
            "maxAtingimento": None, "valor": 5, "ativo": True}
    rule.update(changes)
    return rule


def test_foco_agrupado_sem_duplicar_vendas():
    row = {"__COMPETENCIA": "09/2026", "__COLABORADOR": "Ana", "__LAB": "DELTA",
           "__CANAL": "VENDEDORES", "__OBJETIVO": 100, "__VENDA": 120, "__TEM_FOCO": False}
    focus = dict(row, __TEM_FOCO=True, __CODIGO_FOCO="6183",
                 __OBJETIVO=10, __VENDA=11, __OBJETIVO_FOCO=10, __VENDA_FOCO=11)
    group = group_rows([row, focus])[0]
    assert (group["objetivo"], group["venda"], group["objetivo_foco"],
            group["venda_foco"], group["tem_foco"]) == (100, 120, 10, 11, True)


def test_faturamento_premiacao_percentual_meta():
    assert simple_award(_group(), [_rule()]) == Decimal("5")


def test_gatilho_duplo_bloqueia_premio():
    assert simple_award(_group(venda="99", foco=True), [_rule()]) == 0


def test_regra_especial_nao_e_tratada_como_zero():
    with pytest.raises(MonthlyAwardUnsupported):
        simple_award(_group(), [_rule(metrica="POSITIVACAO_CLIENTES")])


def test_laboratorio_especial_exige_base_auxiliar():
    with pytest.raises(MonthlyAwardUnsupported):
        simple_award(_group(lab="HERBAMED"), [_rule(laboratorio="HERBAMED")])


def test_exige_foco_sem_linha_eh_bloqueado():
    with pytest.raises(MonthlyAwardUnsupported):
        simple_award(_group(), [_rule(exigeFoco=True)])


def test_uniphar_so_premia_apos_objetivo_individual():
    rule = _rule(laboratorio="UNIPHAR", metrica="FATURAMENTO")
    assert simple_award(_group(lab="UNIPHAR", venda="99"), [rule]) == 0


def test_arte_nativa_agosto_descarta_faixa_abaixo_objetivo():
    rule = _rule(competencia="08/2026", laboratorio="ARTE NATIVA",
                 metrica="FATURAMENTO", minAtingimento=50)
    assert simple_award(_group(comp="08/2026", lab="ARTE NATIVA"), [rule]) == 0


def test_prioridade_canal_especifico():
    assert simple_award(_group(), [_rule(canal="TODOS", valor=1),
                                   _rule(canal="VENDEDOR", valor=7)]) == 7


def test_regra_nao_migrada_identificada_no_inventario():
    report = rule_coverage([_rule(metrica="PONTUACAO_PRODUTO")])
    assert report["nao_migradas"]["PONTUACAO_PRODUTO/PERCENTUAL_OBJETIVO"] == 1
    assert report["publicacao_permitida"] is False


def test_registro_invalido_nao_e_aceito():
    with pytest.raises(MonthlyAwardUnsupported):
        group_rows([{"__COMPETENCIA": "09/2026", "__COLABORADOR": "ANA",
                     "__LAB": "DELTA", "__CANAL": "VENDEDORES", "__VENDA": "invalido"}])


def test_laboratorio_produto_foco():
    assert laboratory("DELTA - Prod. Foco (6183)") == "DELTA"


def test_valor_brasileiro():
    assert amount("R$ 1.234,56") == Decimal("1234.56")
