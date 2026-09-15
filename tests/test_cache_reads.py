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
