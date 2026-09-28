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


def test_produto_por_unidade_com_gatilho():
    payload = extras_payload()
    payload["campanhas"][0].update(
        {
            "metrica": "PRODUTO_UNIDADE_GATILHO",
            "objetivo": 0,
            "codigoProdutoFoco": "1234",
            "objetivoProdutoFoco": 50,
            "regra": {"valorUnidade": 1.5},
        }
    )
    payload["vendasPorCampanha"]["CE-1"] = [
        {
            "colaborador": "VENDEDOR TESTE",
            "laboratorio": "LAB TESTE",
            "data": "2026-09-10",
            "venda": 600,
            "codigoProduto": "1234",
            "quantidade": 60,
        }
    ]
    r = extras_api_response(
        extras_payload=payload,
        users_payload=users_payload(),
        profile=admin(),
        campaign_id="CE-1",
    )
    row = r["registros"][0]
    assert row["quantidadeProdutoFoco"] == 60
    assert row["premiacao"] == 90
    assert row["status"] == "PREMIADO"


def test_produto_por_unidade_nao_premia_antes_do_gatilho():
    payload = extras_payload()
    payload["campanhas"][0].update(
        {
            "metrica": "PRODUTO_UNIDADE_GATILHO",
            "objetivo": 0,
            "codigoProdutoFoco": "1234",
            "objetivoProdutoFoco": 50,
            "regra": {"valorUnidade": 1.5},
        }
    )
    payload["vendasPorCampanha"]["CE-1"][0].update(
        {"codigoProduto": "1234", "quantidade": 49}
    )
    r = extras_api_response(
        extras_payload=payload,
        users_payload=users_payload(),
        profile=admin(),
        campaign_id="CE-1",
    )
    assert r["registros"][0]["premiacao"] == 0
    assert r["registros"][0]["status"] == "EM ANDAMENTO"


def test_faturamento_percentual_com_meta_individual():
    payload = extras_payload()
    payload["campanhas"][0].update(
        {
            "metrica": "FATURAMENTO_INDIVIDUAL_PERCENTUAL",
            "objetivo": 0,
            "regra": {
                "metasIndividuais": [
                    {
                        "usuario": "vendteste",
                        "nome": "VENDEDOR TESTE",
                        "tipo": "VENDEDOR",
                        "objetivo": 1000,
                        "percentual": 5,
                    }
                ]
            },
        }
    )
    r = extras_api_response(
        extras_payload=payload,
        users_payload=users_payload(),
        profile=admin(),
        campaign_id="CE-1",
    )
    row = r["registros"][0]
    assert row["objetivo"] == 1000
    assert row["atingimento"] == 120
    assert row["percentualIndividual"] == 5
    assert row["premiacao"] == 50
    assert row["status"] == "PREMIADO"
