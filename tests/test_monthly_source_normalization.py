"""Normalização independente das abas comerciais, sem substituir fotografia."""
from decimal import Decimal
import pytest

from api.monthly_source_normalization import (
    MonthlySourceInvalid, candidate_from_sheets, sheet_to_monthly_rows,
)


def _sheet(channel="VENDEDOR", sale=3931852):
    return [
        ["Acompanhamento"],
        [],
        ["", channel, "Laboratório", "Objetivo", "Venda", "VENDA F.", "%", "Premiação"],
        ["", "ANA", "GLOBO", 7300, sale, 0, 0, "Pendente"],
        ["", "ANA", "GLOBO - Prod. Foco (5640)", 10, None, 0, 0, ""],
    ]


def test_venda_alterada_na_fonte_nao_e_trocada_pela_fotografia_antiga():
    rows = sheet_to_monthly_rows(_sheet(), "CAMPANHA VEND", "09/2026")
    assert rows[0]["__VENDA"] == Decimal(3931852)
    assert rows[0]["__linha"] == 4
    assert rows[0]["Premiação"] == "Pendente"


def test_produto_foco_e_linha_com_venda_vazia():
    rows = sheet_to_monthly_rows(_sheet(), "CAMPANHA VEND", "09/2026")
    assert rows[1]["__TEM_FOCO"]
    assert rows[1]["__CODIGO_FOCO"] == "5640"
    assert rows[1]["__OBJETIVO_FOCO"] == 10
    assert rows[1]["__VENDA_FOCO"] == 0
    assert rows[1]["__VENDA"] == 0


def test_monta_canais_independentes():
    candidate = candidate_from_sheets(_sheet(), _sheet("Televendas", 120), "09/2026")
    assert len(candidate["dadosVendedores"]) == 2
    assert len(candidate["dadosTelevendas"]) == 2
    assert candidate["dadosTelevendas"][0]["__CANAL"] == "TELEVENDAS"


def test_rejeita_cabecalho_ambiguo():
    sheet = _sheet()
    sheet[2][0] = "Venda"
    with pytest.raises(MonthlySourceInvalid):
        sheet_to_monthly_rows(sheet, "CAMPANHA VEND", "09/2026")


def test_linha_incompleta_nao_gera_premio():
    sheet = _sheet()
    sheet[3][1] = ""
    with pytest.raises(MonthlySourceInvalid):
        sheet_to_monthly_rows(sheet, "CAMPANHA VEND", "09/2026")


def test_aba_desconhecida_bloqueada():
    with pytest.raises(MonthlySourceInvalid):
        sheet_to_monthly_rows(_sheet(), "OUTRA", "09/2026")
