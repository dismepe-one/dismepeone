from api.my_campaigns import (
    _apply_projection,
    _build_campaign_rows,
    _build_summary,
    _weekday_total,
    can_view_my_campaigns,
)


def test_access_is_limited_to_fernanda_and_danton():
    assert can_view_my_campaigns({"usuario": "FERNANDA", "tipo": "SUP TELEVENDAS"})
    assert can_view_my_campaigns({"usuario": "DANTON", "tipo": "ADMINISTRADOR"})
    assert not can_view_my_campaigns({"usuario": "ALVARO", "tipo": "SUP VENDAS"})
    assert not can_view_my_campaigns({"usuario": "OUTRO", "tipo": "ADMINISTRADOR"})


def test_normal_campaign_uses_only_televendas_and_ignores_non_sales_rows():
    payload = {
        "dadosTelevendas": [
            {"__LAB": "GEOLAB", "__COMPETENCIA": "09/2026", "__OBJETIVO": 1000, "__VENDA": 400},
            {"__LAB": "GEOLAB", "__COMPETENCIA": "09/2026", "__OBJETIVO": 500, "__VENDA": 300},
            {"__LAB": "GEOLAB - Prod. Foco (2239)", "__COMPETENCIA": "09/2026", "__OBJETIVO": 90, "__VENDA": 42},
            {"__LAB": "BRG SUPLEMENTOS", "__COMPETENCIA": "09/2026", "__OBJETIVO": 400, "__VENDA": 280},
        ]
    }
    rows, warnings = _build_campaign_rows(payload, "09/2026", general_sales_getter=lambda *_: None)
    assert warnings == []
    assert len(rows) == 1
    row = rows[0]
    assert row["laboratorio"] == "GEOLAB"
    assert row["escopo"] == "TELEVENDAS"
    assert row["objetivo"] == 1500
    assert row["venda"] == 700
    assert row["atingimento"] == 46.67
    assert row["falta"] == 800


def test_herbamed_and_natulab_use_general_sales_and_fixed_objectives():
    payload = {
        "dadosTelevendas": [
            {"__LAB": "HERBAMED", "__COMPETENCIA": "09/2026", "__OBJETIVO": 60000, "__VENDA": 64000},
            {"__LAB": "NATULAB", "__COMPETENCIA": "09/2026", "__OBJETIVO": 150000, "__VENDA": 164000},
        ]
    }
    general = {
        "HERBAMED": {"venda": 105785.47, "atualizadoEm": "29/09/2026 17:00"},
        "NATULAB": {"venda": 326258.79, "atualizadoEm": "29/09/2026 17:00"},
    }
    rows, warnings = _build_campaign_rows(
        payload,
        "09/2026",
        general_sales_getter=lambda lab, _comp: general[lab],
    )
    assert warnings == []
    by_lab = {row["laboratorio"]: row for row in rows}
    assert by_lab["HERBAMED"]["objetivo"] == 160000
    assert by_lab["HERBAMED"]["venda"] == 105785.47
    assert by_lab["HERBAMED"]["escopo"] == "VENDA_GERAL"
    assert by_lab["NATULAB"]["objetivo"] == 700000
    assert by_lab["NATULAB"]["venda"] == 326258.79
    assert by_lab["NATULAB"]["escopo"] == "VENDA_GERAL"


def test_general_sale_never_falls_back_to_televendas():
    payload = {
        "dadosTelevendas": [
            {"__LAB": "HERBAMED", "__COMPETENCIA": "09/2026", "__OBJETIVO": 60000, "__VENDA": 64813.38},
        ]
    }
    rows, warnings = _build_campaign_rows(payload, "09/2026", general_sales_getter=lambda *_: None)
    assert rows[0]["venda"] is None
    assert rows[0]["status"] == "SEM_VENDA_GERAL"
    assert warnings


def test_projection_and_required_daily_sale_use_same_campaign_scope_values():
    rows = [
        {"objetivo": 1000, "venda": 600, "falta": 400, "status": "ABAIXO_META"},
        {"objetivo": 500, "venda": 550, "falta": 0, "status": "META_ATINGIDA"},
    ]
    _apply_projection(rows, total_days=22, remaining_days=2, elapsed_days=21)
    assert rows[0]["vendaDiaNecessaria"] == 200
    assert rows[0]["projecao"] == 628.57
    assert rows[0]["projecaoAtingeMeta"] is False
    assert rows[1]["vendaDiaNecessaria"] == 0
    assert rows[1]["projecao"] == 576.19
    assert rows[1]["projecaoAtingeMeta"] is True


def test_weekday_total_for_september_2026():
    assert _weekday_total("09/2026") == 22


def test_summary_reports_only_operational_counts():
    rows = [
        {"objetivo": 100, "venda": 120, "status": "META_ATINGIDA"},
        {"objetivo": 200, "venda": 100, "status": "ABAIXO_META"},
        {"objetivo": 0, "venda": 10, "status": "SEM_OBJETIVO"},
    ]
    summary = _build_summary(rows)
    assert summary == {
        "campanhas": 3,
        "metaAtingida": 1,
        "abaixoMeta": 1,
        "semObjetivo": 1,
        "dadosIncompletos": 0,
    }
    assert "objetivo" not in summary
    assert "venda" not in summary
    assert "atingimento" not in summary
