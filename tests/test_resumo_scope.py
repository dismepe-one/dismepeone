from api.cache_reads import scope_resumo_ganhos


def payload():
    return {
        "registros": [
            {
                "colaborador": "A",
                "setor": "Vendedor",
                "laboratorio": "LAB",
                "premiacao": 100,
            }
        ],
        "totais": {"total": 100},
    }


def test_admin_can_read_summary():
    result = scope_resumo_ganhos(
        payload(),
        {"tipo": "ADMINISTRADOR", "permissoes": {}},
    )
    assert result["sucesso"] is True
    assert result["totais"]["total"] == 100


def test_finance_can_read_summary():
    result = scope_resumo_ganhos(
        payload(),
        {"tipo": "CONTAS A PAGAR", "permissoes": {}},
    )
    assert result["sucesso"] is True


def test_user_with_explicit_permission_can_read_summary():
    result = scope_resumo_ganhos(
        payload(),
        {
            "tipo": "VENDEDOR",
            "permissoes": {"RESUMO_PREMIACOES": True},
        },
    )
    assert result["sucesso"] is True


def test_user_without_permission_is_rejected():
    try:
        scope_resumo_ganhos(
            payload(),
            {"tipo": "VENDEDOR", "permissoes": {}},
        )
    except PermissionError:
        return
    assert False, "PermissionError expected"
