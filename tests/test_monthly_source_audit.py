"""Testes de auditoria da fonte mensal viva versus fotografia legada.

Não atualizam MENSAL, HOME nem calculam premiações.
"""
import pytest

from api.monthly_render_shadow import MonthlyShadowError, audit_source_rows


def _matrix(sale=3931852):
    return [
        ["Acompanhamento mensal"],
        [],
        ["", "Vendedor", "Laboratório", "Objetivo", "Venda"],
        ["", "COLAB A", "LAB A", 7300, sale],
        ["", "COLAB B", "LAB B", 1500, 200],
    ]


def _official(sale=3931.64):
    return [
        {"__COMPETENCIA": "09/2026", "__linha": 4, "__OBJETIVO": 7300, "__VENDA": sale},
        {"__COMPETENCIA": "09/2026", "__linha": 5, "__OBJETIVO": 1500, "__VENDA": 200},
    ]


def test_diferenca_real_fica_visivel_nao_publica():
    result = audit_source_rows(_matrix(), _official(), "CAMPANHA VEND", "09/2026")
    assert result["linhasAlteradas"] == 1
    assert result["numerosLinhasAlteradas"] == [4]
    assert result["valoresConferidos"] is False
    assert result["vendaFonte"] == "3932052"
    assert result["vendaFotografia"] == "4131.64"


def test_igualdade_so_mesma_revisao():
    result = audit_source_rows(_matrix(3931.64), _official(), "CAMPANHA VEND", "09/2026")
    assert result["valoresConferidos"] is True
    assert result["linhasAlteradas"] == 0


def test_linha_nova_nao_e_ignorada():
    matrix = _matrix()
    matrix.append(["", "COLAB C", "LAB C", 1000, 500])
    result = audit_source_rows(matrix, _official(), "CAMPANHA VEND", "09/2026")
    assert result["linhasAdicionadas"] == 1
    assert result["valoresConferidos"] is False


def test_fotografia_sem_competencia_nao_aceita():
    with pytest.raises(MonthlyShadowError):
        audit_source_rows(_matrix(), _official(), "CAMPANHA VEND", "08/2026")


def test_linha_com_venda_invalida_bloqueada():
    matrix = _matrix()
    matrix[3][4] = "erro"
    with pytest.raises(MonthlyShadowError):
        audit_source_rows(matrix, _official(), "CAMPANHA VEND", "09/2026")


def test_cabecalho_ambiguo_bloqueado():
    matrix = _matrix()
    matrix[2][0] = "Venda"
    with pytest.raises(MonthlyShadowError):
        audit_source_rows(matrix, _official(), "CAMPANHA VEND", "09/2026")
