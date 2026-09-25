"""Valida requisitos das fontes de premiação sem acesso a dados de clientes."""
import pytest

from api.monthly_auxiliary_sources import MonthlyAuxiliaryError, parse_auxiliary_tab


@pytest.mark.parametrize("name,header,row", [
    ("METRICA_GLOBO", ["VENDEDOR_TELEVENDAS", "TIPO", "META_CLIENTES", "PREMIO"],
     ["VENDEDOR A", "VENDEDOR", 10, 50]),
    ("GLOBO_CLIENTES", ["Vendedor", "Cód. Cliente", "Pedidos Por", "Positivação", "Data"],
     ["VENDEDOR A", "100", "Eletrônico", 1, 46274]),
    ("HERBAMED_REGRAS", ["INDICADOR", "META", "PREMIO"],
     ["CLIENTESPOSITIVADOS", 10, 30]),
    ("HERB_COM", ["Vendedor", "Cód. Cliente", "CNPJ", "Data", "Pedidos Por"],
     ["VENDEDOR A", "100", "", 46274, "Eletrônico"]),
    ("INTEGRAL_PRODUTOS", ["Cód. Produto", "PONTOS"],
     ["6183", 3]),
    ("INTEGRAL_FAIXAS", ["PONTOS", "PREMIO"], [20, "R$ 50,00"]),
    ("INT_PONTOS", ["Data", "Pedidos Por", "Vendedor", "Cód. Produto", "Total Unidade", "Faturado"],
     [46274, "Eletrônico", "VENDEDOR A", "6183", 3, "SIM"]),
])
def test_cabecalhos_reais(name, header, row):
    result = parse_auxiliary_tab(name, [header, row])
    assert result["registros"] == 1
    assert result["validos"] == 1
    assert result["cabecalhoVerificado"] is True
    assert result["calculoConcluido"] is False


def test_linha_incompleta_herb_com_e_ignorada_sem_derrubar_base():
    header = ["Vendedor", "Cód. Cliente", "CNPJ", "Data", "Pedidos Por"]
    rows = [["VENDEDOR A", "100", "", 46274, "Eletrônico"],
            ["VENDEDOR A", "", "", "", ""]]
    result = parse_auxiliary_tab("HERB_COM", [header, *rows])
    assert result["validos"] == 1
    assert result["ignorados"] == 1


def test_todas_linhas_incompletas_bloqueiam():
    header = ["Vendedor", "Cód. Cliente", "CNPJ", "Data", "Pedidos Por"]
    with pytest.raises(MonthlyAuxiliaryError):
        parse_auxiliary_tab("HERB_COM", [header, ["VENDEDOR A", "", "", "", ""]])


def test_coluna_faltando_bloqueia():
    with pytest.raises(MonthlyAuxiliaryError):
        parse_auxiliary_tab("INT_PONTOS", [["Data", "Vendedor"], [46274, "VENDEDOR A"]])


def test_indicador_geral_nao_e_calculado_por_presuncao():
    result = parse_auxiliary_tab(
        "HERBAMED_REGRAS",
        [["INDICADOR", "META", "PREMIO"], ["CLIENTESGERAL", 200, 150]],
    )
    assert result["calculoConcluido"] is False
