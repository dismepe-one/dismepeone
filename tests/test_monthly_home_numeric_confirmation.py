"""Regressão da confirmação da HOME após serialização de JSON na Edge Function."""
import copy

from api.home_publication import _partial_numbers, _partial_sales_changed, _partial_signature


def monthly(sale=100.0, goal=150.0):
    return {
        "dadosVendedores": [{
            "__COMPETENCIA": "09/2026", "__COLABORADOR": "ANA",
            "__LAB": "LABORATORIO", "__VENDA": sale, "__OBJETIVO": goal,
            "Venda": sale, "Vendas": sale, "Realizado": sale, "venda": sale,
            "__VENDA_FOCO": 0.0, "vendaFoco": 0.0,
            "__CODIGO_FOCO": "001",
        }],
        "dadosTelevendas": [{
            "__COMPETENCIA": "09/2026", "__COLABORADOR": "BIA",
            "__LAB": "LABORATORIO", "__VENDA": sale,
            "Venda": sale, "venda": sale, "__VENDA_FOCO": 0.0,
        }],
    }


def test_edge_json_roundtrip_does_not_create_false_difference():
    before = monthly(sale=100.0)
    after = monthly(sale=100)
    for key in ("dadosVendedores", "dadosTelevendas"):
        assert _partial_numbers(before, key) == _partial_numbers(after, key)
    assert _partial_signature(before) == _partial_signature(after)
    assert not _partial_sales_changed({"mensal": before}, after)


def test_real_sale_change_still_detected():
    old = monthly(sale=100)
    new = monthly(sale=101)
    assert _partial_signature(old) != _partial_signature(new)
    assert _partial_sales_changed({"mensal": old}, new)


def test_string_codes_not_coerced_and_bool_is_not_number():
    old = monthly()
    changed_code = copy.deepcopy(old)
    changed_code["dadosVendedores"][0]["__CODIGO_FOCO"] = "1"
    assert _partial_signature(old) != _partial_signature(changed_code)
    changed_type = copy.deepcopy(old)
    changed_type["dadosVendedores"][0]["__VENDA"] = True
    assert _partial_signature(old) != _partial_signature(changed_type)


def test_numeric_precision_beyond_equivalent_representation():
    assert _partial_signature(monthly(sale=100.0001)) != _partial_signature(monthly(sale=100))
