"""Comparacao agregada: testes locais, sem acesso ao Google ou ao banco."""
from api.monthly_commercial_compare import compare_rows


def row(line, sale=100, name="ANA", focus=False):
    return {"__COMPETENCIA": "09/2026", "__linha": line, "__COLABORADOR": name,
            "__LAB": "LAB A", "__OBJETIVO": 100, "__VENDA": sale,
            "__TEM_FOCO": focus}


def test_equivalencia():
    result = compare_rows([row(4)], [row(4)], "09/2026")
    assert result["fonte"] == result["sql"] == 1
    assert result["numerosDivergentes"] == result["identidadesDivergentes"] == 0


def test_identifica_venda_nova_sem_substituir_sql():
    result = compare_rows([row(4, 250), row(5)], [row(4)], "09/2026")
    assert result["numerosDivergentes"] == 1
    assert result["novas"] == 1


def test_identifica_colaborador_e_foco():
    result = compare_rows([row(4, name="BIA", focus=True)], [row(4)], "09/2026")
    assert result["identidadesDivergentes"] == 1
    assert result["focoDivergente"] == 1
