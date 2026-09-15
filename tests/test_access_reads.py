from api.access_reads import build_access_panel


def test_build_access_panel():
    data = [
        {
            "data_hora": "2026-09-15T10:00:00-03:00",
            "usuario": "admin",
            "setor": "ADMINISTRADOR",
            "acao": "LOGIN",
        },
        {
            "data_hora": "2026-09-14T09:00:00-03:00",
            "usuario": "admin",
            "setor": "ADMINISTRADOR",
            "acao": "LOGIN",
        },
        {
            "data_hora": "2026-09-15T08:00:00-03:00",
            "usuario": "vend1",
            "setor": "VENDEDOR",
            "acao": "LOGIN",
        },
    ]

    panel = build_access_panel(data)
    assert len(panel["acessos"]) == 3
    assert len(panel["usuariosDetalhados"]) == 2
    assert panel["usuariosDetalhados"][0]["total"] >= 1
    assert len(panel["acessosPorDia"]) == 30
    assert "resumo" in panel


def test_empty_panel():
    panel = build_access_panel([])
    assert panel["resumo"]["totalAcessos"] == 0
    assert panel["usuariosDetalhados"] == []
