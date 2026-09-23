"""Regressão do filtro por fornecedor e identificação do operador logístico."""
from api import positivacao_geral as pos


def _example(monkeypatch):
    sheets = {
        "vendedores": [
            ["Vendedor", "Cliente", "Cód. Cliente", "Positivação", "CNPJ", "Pedidos Por", "Fornecedor", "Operador Pedido"],
            ["ANA", "Farmácia 1", "101", "1", "12345678000100", "Vendedor", "GEOLAB", "ANA"],
            ["ANA", "Farmácia 1", "101", "1", "12345678000100", "Vendedor", "NEO QUIMICA", "RUNNING"],
            ["ANA", "Farmácia 2", "102", "1", "12345678000101", "Vendedor", "NEO QUIMICA", "PDVLINK"],
        ],
        "televendas": [
            ["Televendas", "Cliente", "Cód. Cliente", "Positivação", "CNPJ", "Pedidos Por", "Fornecedor", "Operador Pedido"],
            ["BIA", "Farmácia 1", "101", "1", "12345678000100", "Televendas", "NEO QUIMICA", "BIA"],
        ],
        "diretoria e sup": [
            ["Vendedor", "Cliente", "Cód. Cliente", "Positivação", "CNPJ", "Pedidos Por", "Fornecedor"],
            ["DIRETORIA", "Farmácia 3", "103", "1", "", "Vendedor", "GEOLAB"],
        ],
    }
    monkeypatch.setattr(pos, "_read_sheet", lambda raw, tab: sheets[tab])
    sales, info = pos._parse_sales(b"example")
    portfolio = {
        str(code): {
            "cliente": f"Farmácia {code-100}", "vendedoresPdf": ["ANA"],
            "televendasPdf": ["BIA"], "bloqueado": False,
            "cidade": "Recife", "uf": "PE", "vinculos": [{}],
        }
        for code in (101, 102, 103)
    }
    data = pos._consolidate(portfolio, sales, {"ANA": "ANA"}, {"BIA": "BIA"})
    return sales, data


def test_ol_sem_credito_individual(monkeypatch):
    sales, data = _example(monkeypatch)
    assert sales["102"]["origens"] == ["OL"]
    assert sales["102"]["atoresPorOrigem"] == {}
    row = next(x for x in data["clientes"] if x["codigo"] == "102")
    assert row["status"] == "Positivado"
    assert row["origens"] == ["OL"]
    assert row["positivacoesVendedor"] == []
    assert row["porFornecedor"]["NEO QUIMICA"]["origens"] == ["OL"]


def test_fornecedor_sem_alterar_positivacao_geral(monkeypatch):
    _, data = _example(monkeypatch)
    general = pos._selected(data, "positivados", "ANA", "")
    neo = pos._selected(data, "positivados", "ANA", "", fornecedor="NEO QUIMICA")
    geolab = pos._selected(data, "positivados", "ANA", "", fornecedor="GEOLAB")
    assert {r["codigo"] for r in general} == {"101", "102", "103"}
    assert {r["codigo"] for r in neo} == {"101", "102"}
    assert {r["codigo"] for r in geolab} == {"101", "103"}
    assert pos._selected(data, "nao-positivados", "ANA", "", fornecedor="GEOLAB")[0]["codigo"] == "102"


def test_canais_na_visao_individual_sem_credito_ol(monkeypatch):
    _, data = _example(monkeypatch)
    context = {"view_all": False, "pessoa": "ANA", "canal": "Vendedor", "setor": "ANA",
               "admin": False, "rights": {}, "profile": {}}
    own = pos._visible_data(data, context)
    ol = pos._selected(own, "todos", "ANA", "", fornecedor="NEO QUIMICA")
    client = next(x for x in ol if x["codigo"] == "102")
    assert client["status"] == "Positivado"
    assert client["origensDetalhadas"] == ["OL"]
    assert client["creditoIndividual"] is False
    assert own["geralEmpresa"]["positivados"] == 3
    assert all(x["codigo"] in {"101", "102", "103"} for x in own["clientes"])

def test_filtro_positivador_isola_origem_sem_duplicar_cliente(monkeypatch):
    _, data = _example(monkeypatch)
    assert {r["codigo"] for r in pos._selected(data, "todos", "ANA", "")} == {"101", "102", "103"}
    ol = pos._selected(data, "todos", "ANA", "", positivador="OL")
    assert {r["codigo"] for r in ol} == {"101", "102"}
    assert pos._selected(data, "todos", "ANA", "", positivador="Televendas")[0]["codigo"] == "101"
    assert pos._selected(data, "todos", "ANA", "", positivador="Vendedor")[0]["codigo"] == "101"
    assert pos._selected(data, "todos", "ANA", "", fornecedor="GEOLAB", positivador="OL") == []
    assert [r["codigo"] for r in pos._selected(data, "todos", "ANA", "",
                                                fornecedor="NEO QUIMICA", positivador="OL")] == ["101", "102"]
    assert pos._selected(data, "nao-positivados", "ANA", "", positivador="OL") == []


def test_filtro_positivador_carteira_individual_e_parametro_invalido(monkeypatch):
    _, data = _example(monkeypatch)
    context = {"view_all": False, "pessoa": "ANA", "canal": "Vendedor", "setor": "ANA",
               "admin": False, "rights": {}, "profile": {}}
    own = pos._visible_data(data, context)
    ol = pos._selected(own, "todos", "ANA", "", fornecedor="NEO QUIMICA", positivador="OL")
    assert {r["codigo"] for r in ol} == {"101", "102"}
    assert all(r["status"] == "Positivado" for r in ol)
    assert not next(r for r in ol if r["codigo"] == "102")["creditoIndividual"]
    from fastapi import HTTPException
    try:
        pos._selected(own, "todos", "ANA", "", positivador="DIRETORIA")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("O backend deve rejeitar positivador desconhecido")


def test_resumo_positivador_mantem_denominador_da_carteira(monkeypatch):
    import asyncio
    import json
    _, data = _example(monkeypatch)
    async def viewer(session):
        return {"view_all": True, "admin": True, "profile": {}, "setor": "",
                "rights": {}}
    async def snapshot(profile):
        return data
    monkeypatch.setattr(pos, "_viewer_context", viewer)
    monkeypatch.setattr(pos, "_get_data", snapshot)
    async def summary():
        response = await pos.positivacao_filtered_summary(
            setor="ANA", fornecedor="NEO QUIMICA", positivador="OL", session="test")
        return json.loads(response.body)
    result = asyncio.run(summary())
    assert result["indicadores"]["carteira"] == 3
    assert result["indicadores"]["positivados"] == 2
    assert result["indicadores"]["naoPositivados"] == 1
    assert result["origens"]["OL"] == 2
