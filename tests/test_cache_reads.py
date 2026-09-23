from api.cache_reads import scope_clientes_ped


def payload():
    return {
        "clientes": [
            {
                "codigoSetor": "01",
                "setor": "SETOR 01",
                "vendedor": "VENDEDOR UM",
                "televendas": "TLV UM",
                "status": "POSITIVADO",
            },
            {
                "codigoSetor": "02",
                "setor": "SETOR 02",
                "vendedor": "VENDEDOR DOIS",
                "televendas": "TLV DOIS",
                "status": "PENDENTE",
            },
        ],
        "setores": [
            {"codigoSetor": "01", "setor": "SETOR 01", "vendedor": "VENDEDOR UM"},
            {"codigoSetor": "02", "setor": "SETOR 02", "vendedor": "VENDEDOR DOIS"},
        ],
        "setoresMeta": [
            {
                "codigoSetor": "01",
                "setor": "SETOR 01",
                "vendedor": "VENDEDOR UM",
                "metaQuantidade": 10,
                "realizadoQuantidade": 5,
            },
            {
                "codigoSetor": "02",
                "setor": "SETOR 02",
                "vendedor": "VENDEDOR DOIS",
                "metaQuantidade": 20,
                "realizadoQuantidade": 7,
            },
        ],
        "metaFamilias": [],
        "metaEmpresa": {"metaGeral": 30, "podeEditar": True},
        "vendasPorSetor": {"01": 100, "02": 200},
    }


def test_admin_gets_full_snapshot_but_read_only():
    result = scope_clientes_ped(
        payload(),
        {
            "tipo": "ADMINISTRADOR",
            "permissoes": {},
        },
    )
    assert len(result["clientes"]) == 2
    assert result["metaEmpresa"]["podeEditar"] is False
    assert result["escopoAcesso"] == "GESTAO"


def test_vendor_never_gets_other_sector():
    result = scope_clientes_ped(
        payload(),
        {
            "tipo": "VENDEDOR",
            "vendedor": "VENDEDOR UM",
            "setor": "01",
            "permissoes": {"CLIENTES_PED_VISUALIZAR": True},
        },
    )
    assert len(result["clientes"]) == 1
    assert result["clientes"][0]["codigoSetor"] == "01"
    assert result["setoresAcesso"] == ["01"]


def test_no_permission_is_rejected():
    try:
        scope_clientes_ped(
            payload(),
            {
                "tipo": "VENDEDOR",
                "vendedor": "VENDEDOR UM",
                "permissoes": {},
            },
        )
    except PermissionError:
        return
    assert False, "PermissionError expected"


def test_patricia_peds_only_marcos_pair_in_all_sections():
    source = {
        "clientes": [
            {"codigoCliente": "1", "codigoSetor": "SET046", "codigoSetorMeta": "SET046",
             "setorMeta": "MARCOS FELIPE FERREIRA LIMA + PATRICIA GOMES",
             "vendedor": "MARCOS FELIPE FERREIRA LIMA", "televendas": "PATRICIA GOMES",
             "status": "POSITIVADO"},
            {"codigoCliente": "2", "codigoSetor": "SET010",
             "vendedor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA",
             "televendas": "PATRICIA GOMES", "status": "PENDENTE"},
            {"codigoCliente": "3", "codigoSetor": "", "vendedor": "",
             "televendas": "PATRICIA GOMES", "status": "PENDENTE"},
        ],
        "setores": [
            {"codigoSetor": "SET046", "setor": "MARCOS FELIPE FERREIRA LIMA + PATRICIA GOMES",
             "vendedor": "MARCOS FELIPE FERREIRA LIMA", "televendas": "PATRICIA GOMES"},
            {"codigoSetor": "SET010", "setor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA + PATRICIA GOMES",
             "vendedor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA", "televendas": "PATRICIA GOMES"},
        ],
        "setoresMeta": [
            {"codigoSetor": "SET046", "setor": "MARCOS FELIPE FERREIRA LIMA + PATRICIA GOMES",
             "vendedor": "MARCOS FELIPE FERREIRA LIMA", "televendas": "PATRICIA GOMES",
             "metaQuantidade": 10, "realizadoQuantidade": 5},
            {"codigoSetor": "SET010", "setor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA + PATRICIA GOMES",
             "vendedor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA", "televendas": "PATRICIA GOMES",
             "metaQuantidade": 20, "realizadoQuantidade": 7},
        ],
        "metaFamilias": [{"familia": "EXEMPLO", "setores": {
            "SET046": {"metaSetor": 5, "realizadoSetor": 3},
            "SET010": {"metaSetor": 8, "realizadoSetor": 7},
        }}],
        "vendasPorSetor": {"SET046": 100, "SET010": 200},
        "metaEmpresa": {"metaGeral": 30, "podeEditar": True},
    }
    profile = {"usuario": "PATRICIA", "vendedor": "PATRICIA GOMES",
               "tipo": "TELEVENDAS", "setor": "",
               "permissoes": {"CLIENTES_PED_VISUALIZAR": True}}
    result = scope_clientes_ped(source, profile)
    assert [x["codigoCliente"] for x in result["clientes"]] == ["1"]
    assert result["setoresAcesso"] == ["SET046"]
    assert len(result["setores"]) == len(result["setoresMeta"]) == 1
    assert result["setores"][0]["codigoSetor"] == "SET046"
    assert result["vendasPorSetor"] == {"SET046": 100}
    assert list(result["metaFamilias"][0]["setores"]) == ["SET046"]
    assert result["resumo"]["total"] == 1


def test_patricia_peds_fails_closed_without_official_pair():
    base = {
        "clientes": [{"codigoSetor": "SET010", "vendedor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA",
                      "televendas": "PATRICIA GOMES", "status": "POSITIVADO"}],
        "setores": [{"codigoSetor": "SET010", "vendedor": "CLAUDIA FABIANA SILVA COSTA OLIVEIRA",
                    "televendas": "PATRICIA GOMES"}],
        "setoresMeta": [], "vendasPorSetor": {"SET010": 999},
        "metaFamilias": [], "metaEmpresa": {},
    }
    profile = {"usuario": "PATRICIA", "vendedor": "PATRICIA GOMES",
               "tipo": "TELEVENDAS", "permissoes": {"CLIENTES_PED_VISUALIZAR": True}}
    scoped = scope_clientes_ped(base, profile)
    assert scoped["clientes"] == []
    assert scoped["setoresAcesso"] == []
    assert scoped["setores"] == []
    assert scoped["vendasPorSetor"] == {}


def test_other_televendas_scope_not_changed_by_patricia_rule():
    source = payload()
    source["clientes"].append({
        "codigoSetor": "03", "setor": "SETOR 03", "vendedor": "VENDEDOR TRES",
        "televendas": "PATRICIA GOMES", "status": "POSITIVADO",
    })
    result = scope_clientes_ped(source, {
        "usuario": "OUTRA", "vendedor": "TLV UM", "tipo": "TELEVENDAS",
        "permissoes": {"CLIENTES_PED_VISUALIZAR": True},
    })
    assert [r["codigoSetor"] for r in result["clientes"]] == ["01"]
