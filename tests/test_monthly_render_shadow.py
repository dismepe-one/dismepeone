"""Testes do leitor-sombra mensal: segurança antes de qualquer ativação."""
import pytest

from api.monthly_render_shadow import (
    MonthlyShadowError, _current_source, _header_index,
    _sheet_file_id, _source_stats,
)


def test_link_google_valido():
    assert _sheet_file_id(
        "https://docs.google.com/spreadsheets/d/1A2345678901234567890abcDEF/edit#gid=0"
    ) == "1A2345678901234567890abcDEF"


@pytest.mark.parametrize("link", [
    "", "https://example.com/spreadsheets/d/1A2345678901234567890abcDEF/edit",
    "http://docs.google.com/spreadsheets/d/1A2345678901234567890abcDEF/edit",
    "https://docs.google.com.evil.test/spreadsheets/d/1A2345678901234567890abcDEF/edit",
])
def test_link_google_invalido(link):
    with pytest.raises(MonthlyShadowError):
        _sheet_file_id(link)


def test_uma_unica_competencia_atual():
    rows = {
        "competencias": [
            {"competencia": "08/2026", "status": "HISTORICO"},
            {
                "competencia": "09/2026", "status": "ATUAL",
                "linkDrive": "https://docs.google.com/spreadsheets/d/1A2345678901234567890abcDEF/edit",
                "fechada": False, "congelada": False,
            },
        ],
    }
    source = _current_source(rows)
    assert source.competence == "09/2026"
    assert source.frozen is False
    rows["competencias"][1]["congelada"] = True
    with pytest.raises(MonthlyShadowError):
        _current_source(rows)


def test_proibido_atual_ambiguo():
    rows = {"competencias": [
        {"competencia": "09/2026", "status": "ATUAL"},
        {"competencia": "08/2026", "status": "ATUAL"},
    ]}
    with pytest.raises(MonthlyShadowError):
        _current_source(rows)


def test_cabecalho_fora_primeira_linha_e_dados_vazios():
    matrix = [
        ["Relatório de campanhas"],
        ["VENDEDOR", "LABORATÓRIO", "OBJETIVO", "VENDA"],
        ["ALEX", "LAB TESTE", 100, 50],
    ]
    assert _header_index(matrix, "CAMPANHA VEND") == 1
    assert _source_stats(matrix, "CAMPANHA VEND") == {
        "linhas": 1, "linhaCabecalho": 2,
    }
    with pytest.raises(MonthlyShadowError):
        _source_stats(matrix[:2], "CAMPANHA VEND")
