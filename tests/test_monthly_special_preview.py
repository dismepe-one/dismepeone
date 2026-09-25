"""Prévia especial isolada não pode publicar ou expor dados pessoais."""
from api.monthly_special_preview import preview_special_awards


def test_previa_calcula_componentes_e_proibe_publicacao():
    base = {
        "dadosVendedores": [
            {"__COMPETENCIA": "09/2026", "__COLABORADOR": "ANA",
             "__LAB": "GLOBO", "__CANAL": "VENDEDOR",
             "__OBJETIVO": 100, "__VENDA": 130},
            {"__COMPETENCIA": "09/2026", "__COLABORADOR": "ANA",
             "__LAB": "HERBAMED", "__CANAL": "VENDEDOR",
             "__OBJETIVO": 100, "__VENDA": 130},
            {"__COMPETENCIA": "09/2026", "__COLABORADOR": "ANA",
             "__LAB": "BRG SUPLEMENTOS NUTRICIONAIS LTDA", "__CANAL": "VENDEDOR",
             "__OBJETIVO": 100, "__VENDA": 130},
        ],
        "dadosTelevendas": [],
        "regrasPremiacao": [
            {"id": "g", "competencia": "09/2026", "laboratorio": "GLOBO",
             "canal": "TODOS", "metrica": "POSITIVACAO_CLIENTES", "ativo": True},
            {"id": "h", "competencia": "09/2026", "laboratorio": "HERBAMED",
             "canal": "TODOS", "metrica": "POSITIVACAO_CLIENTES", "ativo": True},
            {"id": "b", "competencia": "09/2026", "laboratorio": "BRG SUPLEMENTOS NUTRICIONAIS LTDA",
             "canal": "TODOS", "metrica": "PONTUACAO_PRODUTO", "ativo": True,
             "exigeSomaLaboratorio": True, "somaLabMinimo": 6},
        ],
    }
    aux = {
        "METRICA_GLOBO": [["VENDEDOR_TELEVENDAS", "TIPO", "META_CLIENTES", "PREMIO"],
                         ["ANA", "VENDEDOR", 1, 50]],
        "GLOBO_CLIENTES": [["Vendedor", "Cód. Cliente", "Pedidos Por", "Positivação", "Data"],
                          ["ANA", "101", "Eletrônico", 1, 46274]],
        "HERBAMED_REGRAS": [["INDICADOR", "META", "PREMIO"],
                           ["CLIENTESPOSITIVADOS", 1, 5]],
        "HERB_COM": [["Vendedor", "Cód. Cliente", "CNPJ", "Data", "Pedidos Por"],
                     ["ANA", "101", "", 46274, "Eletrônico"]],
        "INTEGRAL_PRODUTOS": [["Cód. Produto", "PONTOS"], ["6183", 3]],
        "INTEGRAL_FAIXAS": [["PONTOS", "PREMIO"], [6, 50]],
        "INT_PONTOS": [["Data", "Pedidos Por", "Vendedor", "Cód. Produto",
                       "Total Unidade", "Faturado"],
                      [46274, "Eletrônico", "ANA", "6183", 2, "SIM"]],
    }
    report = preview_special_awards(base, aux, {}, "09/2026")
    assert report["componentesPorLaboratorio"] == {
        "GLOBO": 1, "HERBAMED": 1, "INTEGRALMEDICA": 1,
    }
    assert report["componentesPendentesPorLaboratorio"] == {}
    assert report["publicacaoAutorizada"] is False
    assert report["premiacoesComparadasComMesmaRevisao"] is False
    assert "ANA" not in str(report) and "101" not in str(report)
