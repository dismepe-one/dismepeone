import os

os.environ["DISMEPE_SUPABASE_PUBLISHABLE_KEY"] = "pk_test"
os.environ["DISMEPE_EDGE_TOKEN"] = "edge_test"
os.environ["DISMEPE_AUTH_PEPPER"] = "pepper_test"
os.environ["DISMEPE_JWT_SECRET"] = "x" * 48
os.environ["DISMEPE_CORS_ORIGINS"] = "http://localhost:8080"
os.environ["DISMEPE_COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient

from api.config import get_settings
get_settings.cache_clear()

import api.main as main
from api.legacy_bridge import clear_state, mark_pending


async def fake_login_via_edge(*, usuario, senha, settings):
    if senha == "errada":
        raise main.InvalidCredentials("Usuário ou senha incorretos.")
    return {
        "usuario": usuario,
        "nome": "Usuário Teste",
        "vendedor": "Usuário Teste",
        "tipo": "VENDEDOR",
        "setor": "Vendedores",
        "permissoes": {"VENDEDORES": True, "CLIENTES_PED_VISUALIZAR": True, "RESUMO_PREMIACOES": True, "CAMPANHAS_EXTRAS_VISUALIZAR": True, "CONTROLE_DE_ACESSOS": True},
    }


main.login_via_edge = fake_login_via_edge


async def fake_run_legacy_login(*, session_key, usuario, senha, settings):
    # O teste de integração do bridge real fica isolado do ambiente externo.
    return None

main.run_legacy_login = fake_run_legacy_login


async def fake_cache_get(*, modulo, settings):
    if modulo == "MENSAL":
        return (
            {
                "competencias": [
                    {
                        "competencia": "09/2026",
                        "diasUteisRestantes": 10,
                    }
                ],
                "diasUteisPorCompetencia": {"09/2026": 10},
                "dadosVendedores": [
                    {
                        "__COMPETENCIA": "09/2026",
                        "__COLABORADOR": "Usuário Teste",
                        "__LAB": "LAB TESTE",
                    }
                ],
                "dadosTelevendas": [],
                "regrasPremiacao": [],
                "versaoCalculoVendedores": "TEST",
            },
            {
                "atualizado_em": "2026-09-15T00:00:00-03:00",
                "versao": "TEST_MENSAL",
            },
        )

    if modulo == "EXTRAS":
        return (
            {
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
                            "colaborador": "Usuário Teste",
                            "laboratorio": "LAB TESTE",
                            "data": "2026-09-10",
                            "venda": 1200,
                            "codigoProduto": "",
                            "quantidade": 0,
                        }
                    ]
                },
            },
            {
                "atualizado_em": "2026-09-15T00:01:00-03:00",
                "versao": "TEST_EXTRAS",
            },
        )

    if modulo == "USUARIOS":
        return (
            {
                "usuarios": [
                    {
                        "usuario": "teste",
                        "nome": "Usuário Teste",
                        "vendedor": "Usuário Teste",
                        "perfil": "VENDEDOR",
                        "setor": "01",
                    }
                ]
            },
            {
                "atualizado_em": "2026-09-15T00:01:00-03:00",
                "versao": "TEST_USUARIOS",
            },
        )
    if modulo == "RESUMO_PREMIACOES":
        return (
            {
                "registros": [
                    {
                        "colaborador": "Usuário Teste",
                        "setor": "Vendedor",
                        "laboratorio": "LAB TESTE",
                        "competencia": "09/2026",
                        "premiacao": 100.0,
                    }
                ],
                "totais": {
                    "total": 100.0,
                    "vendedores": 100.0,
                    "televendas": 0.0,
                    "colaboradores": 1,
                    "laboratorios": 1,
                },
            },
            {
                "atualizado_em": "2026-09-15T00:00:00-03:00",
                "versao": "TEST_RESUMO",
            },
        )

    return (
        {
            "clientes": [
                {
                    "codigoSetor": "01",
                    "setor": "SETOR 01",
                    "vendedor": "Usuário Teste",
                    "televendas": "TLV Teste",
                    "status": "POSITIVADO",
                }
            ],
            "setores": [
                {
                    "codigoSetor": "01",
                    "setor": "SETOR 01",
                    "vendedor": "Usuário Teste",
                    "televendas": "TLV Teste",
                }
            ],
            "setoresMeta": [
                {
                    "codigoSetor": "01",
                    "setor": "SETOR 01",
                    "vendedor": "Usuário Teste",
                    "televendas": "TLV Teste",
                    "metaQuantidade": 10,
                    "realizadoQuantidade": 5,
                }
            ],
            "metaFamilias": [],
            "metaEmpresa": {"metaGeral": 10, "podeEditar": True},
            "vendasPorSetor": {"01": 100.0},
            "equipeCampanhas": {},
        },
        {
            "atualizado_em": "2026-09-15T00:00:00-03:00",
            "versao": "TEST",
        },
    )

main.cache_get = fake_cache_get


async def fake_list_accesses(*, profile, settings):
    return {
        "sucesso": True,
        "origem": "SUPABASE",
        "transporte": "FASTAPI_LOG_SQL",
        "acessos": [
            {
                "data": "2026-09-15T10:00:00+00:00",
                "usuario": "teste",
                "setor": "ADMINISTRADOR",
                "acao": "LOGIN",
            }
        ],
        "usuarios": [],
        "usuariosDetalhados": [],
        "semAcessoRecente": [],
        "ranking": [],
        "acessosPorSetor": {},
        "acessosPorDia": [],
        "resumo": {
            "totalAcessos": 1,
            "totalHoje": 1,
            "total7Dias": 1,
            "usuariosCadastrados": 1,
            "usuariosHoje": 1,
            "ultimoLogin": None,
        },
    }


async def fake_access_user(*, profile, usuario, settings):
    return {
        "sucesso": True,
        "usuario": usuario,
        "acessos": [],
        "origem": "SUPABASE",
        "transporte": "FASTAPI_LOG_SQL",
    }


main.list_accesses = fake_list_accesses
main.access_user = fake_access_user
client = TestClient(main.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_login_me_logout():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200
    assert r.json()["sucesso"] is True
    assert r.json()["usuario"]["usuario"] == "teste"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["autenticado"] is True

    logout = client.post("/auth/logout")
    assert logout.status_code == 200


def test_invalid_credentials():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "errada"},
    )
    assert r.status_code == 401


def test_portal_homologacao():
    r = client.get("/")
    assert r.status_code == 200
    assert "DISMEPE ONE" in r.text
    assert "__DISMEPE_V2_HOMOLOG" in r.text


def test_legacy_status_pending_after_login():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    status = client.get("/auth/legacy-status")
    assert status.status_code == 200
    assert status.json()["status"] in {"PENDING", "MISSING"}


def test_clientes_ped_snapshot_autorizado():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    ped = client.get("/data/clientes-ped")
    assert ped.status_code == 200
    data = ped.json()
    assert data["sucesso"] is True
    assert data["transporte"] == "FASTAPI_SUPABASE_CACHE_GET"
    assert data["metaEmpresa"]["podeEditar"] is False


def test_resumo_ganhos_snapshot():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    resumo = client.get("/data/resumo-ganhos")
    assert resumo.status_code == 200
    data = resumo.json()
    assert data["sucesso"] is True
    assert data["transporte"] == "FASTAPI_SUPABASE_CACHE_GET"
    assert len(data["registros"]) == 1
    assert data["totais"]["total"] == 100.0


def test_bootstrap_dashboard():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    b = client.get("/data/bootstrap")
    assert b.status_code == 200
    data = b.json()
    assert data["sucesso"] is True
    assert data["transporte"] == "FASTAPI_BOOTSTRAP_MENSAL"
    assert data["competenciaPrincipal"] == "09/2026"
    assert len(data["dadosVendedores"]) == 1
    assert data["horarioMensal"]
    assert data["horarioExtras"]
    assert isinstance(data["bootstrapMs"], int)


def test_login_ja_entrega_bootstrap():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["sucesso"] is True
    assert isinstance(data["elapsedMs"], int)
    assert isinstance(data["authMs"], int)
    assert isinstance(data["bootstrapMs"], int)
    assert data["bootstrap"] is not None
    assert data["bootstrap"]["transporte"] == "FASTAPI_BOOTSTRAP_MENSAL"


def test_campanhas_extras_snapshot_direto():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    lista = client.get("/data/campanhas-extras?id=LIST")
    assert lista.status_code == 200
    assert lista.json()["transporte"] == "FASTAPI_EXTRAS_SNAPSHOT"

    parcial = client.get("/data/campanhas-extras?id=ALL")
    assert parcial.status_code == 200
    data = parcial.json()
    assert data["sucesso"] is True
    assert data["totais"]["venda"] == 1200
    assert data["totais"]["premiacao"] == 100
    assert data["elapsedMs"] >= 0


def test_access_log_direct_endpoint():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    a = client.get("/data/access-log")
    assert a.status_code == 200
    data = a.json()
    assert data["sucesso"] is True
    assert data["transporte"] == "FASTAPI_LOG_SQL"
    assert data["elapsedMs"] >= 0


def test_access_user_direct_endpoint():
    r = client.post(
        "/auth/login",
        json={"usuario": "teste", "senha": "1234"},
    )
    assert r.status_code == 200

    a = client.get("/data/access-user?usuario=teste")
    assert a.status_code == 200
    assert a.json()["usuario"] == "teste"
