from pathlib import Path

from api.monthly_rule_reads import monthly_rule_options

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return HTML.read_text(encoding="utf-8")


def test_version_and_badge_i2():
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()


def test_frontend_uses_direct_monthly_rules_first():
    html = source()
    direct = html.index("/data/monthly-rule-options?competencia=")
    legacy = html.index("acao:'CM70_LISTARMODELOSREGRAS'", direct)
    assert direct < legacy
    assert "[2I2 REGRAS ADMIN] fallback legado:" in html
    assert "response.status===401 || response.status===403" in html


def test_monthly_rule_options_scopes_competencia_and_labs():
    payload = {
        "competencias": [
            {"competencia": "08/2026"},
            {"competencia": "09/2026"},
        ],
        "dadosVendedores": [
            {"__COMPETENCIA": "09/2026", "__LAB": "LAB B"},
            {"__COMPETENCIA": "09/2026", "__LAB": "LAB A"},
            {"__COMPETENCIA": "08/2026", "__LAB": "LAB OLD"},
        ],
        "dadosTelevendas": [
            {"__COMPETENCIA": "09/2026", "laboratorio": "LAB C"},
        ],
        "regrasPremiacao": [
            {"id": "r1", "competencia": "09/2026", "laboratorio": "LAB A", "metrica": "FATURAMENTO"},
            {"id": "r2", "competencia": "08/2026", "laboratorio": "LAB OLD", "metrica": "FATURAMENTO"},
        ],
    }
    result = monthly_rule_options(
        payload=payload,
        profile={"tipo": "ADMINISTRADOR", "permissoes": {}},
        competencia="09/2026",
        snapshot_row={"versao": "M1", "atualizado_em": "2026-09-15T10:00:00Z"},
    )
    assert result["sucesso"] is True
    assert result["competencia"] == "09/2026"
    assert result["laboratorios"] == ["LAB A", "LAB B", "LAB C"]
    assert [r["id"] for r in result["regrasExistentes"]] == ["r1"]
    assert result["baseMensalImportada"] is True
    assert result["permiteMetricasSemBaseMensal"] is True
    assert result["transporte"] == "FASTAPI_MENSAL_REGRAS_SNAPSHOT"


def test_monthly_rule_options_permission():
    try:
        monthly_rule_options(
            payload={"regrasPremiacao": []},
            profile={"tipo": "VENDEDOR", "permissoes": {}},
            competencia="09/2026",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("perfil sem permissão não deveria receber opções administrativas")


def test_monthly_rule_options_permission_by_specific_flag():
    result = monthly_rule_options(
        payload={"regrasPremiacao": []},
        profile={
            "tipo": "GERENCIA",
            "permissoes": {"REGRAS_PREMIACAO_VISUALIZAR": True},
        },
        competencia="09/2026",
    )
    assert result["sucesso"] is True
