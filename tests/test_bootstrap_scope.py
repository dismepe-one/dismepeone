from api.cache_reads import scope_mensal_dashboard


def mensal():
    return {
        "competencias": [
            {"competencia": "08/2026", "diasUteisRestantes": 0},
            {"competencia": "09/2026", "diasUteisRestantes": 12},
        ],
        "diasUteisPorCompetencia": {
            "08/2026": 0,
            "09/2026": 12,
        },
        "dadosVendedores": [
            {
                "__COMPETENCIA": "09/2026",
                "__COLABORADOR": "VENDEDOR UM",
                "__LAB": "LAB A",
            },
            {
                "__COMPETENCIA": "09/2026",
                "__COLABORADOR": "VENDEDOR DOIS",
                "__LAB": "LAB B",
            },
            {
                "__COMPETENCIA": "08/2026",
                "__COLABORADOR": "VENDEDOR UM",
                "__LAB": "LAB A",
            },
        ],
        "dadosTelevendas": [
            {
                "__COMPETENCIA": "09/2026",
                "__COLABORADOR": "TLV UM",
                "__LAB": "LAB A",
            },
        ],
        "regrasPremiacao": [
            {"competencia": "09/2026", "laboratorio": "LAB A"},
            {"competencia": "08/2026", "laboratorio": "LAB B"},
        ],
        "versaoCalculoVendedores": "TEST",
    }


def test_admin_recebe_competencia_mais_recente():
    result = scope_mensal_dashboard(
        mensal(),
        {
            "tipo": "ADMINISTRADOR",
            "usuario": "admin",
            "permissoes": {},
        },
    )
    assert result["competenciaPrincipal"] == "09/2026"
    assert len(result["dadosVendedores"]) == 2
    assert len(result["dadosTelevendas"]) == 1
    assert result["diasUteisRestantes"] == 12
    assert len(result["regrasPremiacao"]) == 1


def test_vendedor_recebe_apenas_proprias_linhas():
    result = scope_mensal_dashboard(
        mensal(),
        {
            "tipo": "VENDEDOR",
            "usuario": "v1",
            "vendedor": "VENDEDOR UM",
            "permissoes": {},
        },
    )
    assert len(result["dadosVendedores"]) == 1
    assert result["dadosVendedores"][0]["__COLABORADOR"] == "VENDEDOR UM"
    assert len(result["dadosTelevendas"]) == 0


def test_competencia_solicitada():
    result = scope_mensal_dashboard(
        mensal(),
        {
            "tipo": "ADMINISTRADOR",
            "usuario": "admin",
            "permissoes": {},
        },
        competencia="08/2026",
    )
    assert result["competenciaPrincipal"] == "08/2026"
    assert len(result["dadosVendedores"]) == 1
