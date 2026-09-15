from api.extras_reads import extras_api_response


def extras_payload():
    return {
        "campanhas": [
            {
                "id": "CE-1",
                "nome": "Campanha Teste",
                "laboratorio": "LAB TESTE",
                "status": "ATIVA",
                "dataInicio": "2026-09-01",
                "dataFim": "2026-09-30",
                "metrica": "META_FATURAMENTO",
                "objetivo": 1000,
                "regra": {"valor": 100},
                "vendedoresModo": "TODOS",
                "televendasModo": "TODOS",
                "vendedoresExceto": [],
                "televendasExceto": [],
            }
        ],
        "vendasPorCampanha": {
            "CE-1": [
                {
                    "colaborador": "VENDEDOR TESTE",
                    "laboratorio": "LAB TESTE",
                    "data": "2026-09-10",
                    "venda": 1200,
                    "codigoProduto": "",
                    "quantidade": 0,
                }
            ]
        },
    }


def users_payload():
    return {
        "usuarios": [
            {
                "usuario": "vendteste",
                "nome": "VENDEDOR TESTE",
                "vendedor": "VENDEDOR TESTE",
                "perfil": "VENDEDOR",
                "setor": "01",
            }
        ]
    }


def admin():
    return {
        "usuario": "admin",
        "nome": "ADMIN",
        "tipo": "ADMINISTRADOR",
        "permissoes": {},
    }


def test_lista_extras_direta():
    r = extras_api_response(
        extras_payload=extras_payload(),
        users_payload=users_payload(),
        profile=admin(),
        campaign_id="LIST",
    )
    assert r["sucesso"] is True
    assert len(r["campanhas"]) == 1


def test_parcial_all_rapida_calculada_no_python():
    r = extras_api_response(
        extras_payload=extras_payload(),
        users_payload=users_payload(),
        profile=admin(),
        campaign_id="ALL",
    )
    assert r["totais"]["venda"] == 1200
    assert r["totais"]["premiacao"] == 100
    assert r["totais"]["participantes"] == 1
    assert r["totais"]["premiados"] == 1


def test_parcial_individual():
    r = extras_api_response(
        extras_payload=extras_payload(),
        users_payload=users_payload(),
        profile=admin(),
        campaign_id="CE-1",
    )
    assert r["campanha"]["id"] == "CE-1"
    assert r["registros"][0]["status"] == "PREMIADO"
