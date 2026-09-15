from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source() -> str:
    return PORTAL.read_text(encoding="utf-8")


def commercial_loader_block() -> str:
    html = source()
    start = html.index("window.loadDataFromCloudV2=function(){")
    end = html.index("window.loadDataFromCloud=window.loadDataFromCloudV2;", start)
    return html[start:end]


def test_sessao_2_0_prefere_postgresql_mesmo_com_token_legado():
    block = commercial_loader_block()
    direct_if = block.index("if(window.__v2Authenticated===true)")
    direct_call = block.index("window.v2LoadBootstrapFast?.(")
    fallback_call = block.index("return await v2RunLegacyDataFallback(token,competencias)")

    assert direct_if < direct_call < fallback_call
    assert "if(!token && window.__v2Authenticated===true)" not in block
    assert "FASTAPI_POSTGRESQL" in block


def test_dados_legado_fica_apenas_como_fallback_controlado():
    block = commercial_loader_block()
    assert "function v2RunLegacyDataFallback(token,competencias)" not in block
    # helper is outside the wrapper, while the wrapper only reaches it after a direct failure
    assert "PostgreSQL indisponível; avaliando fallback legado" in block
    assert "return await v2RunLegacyDataFallback(token,competencias)" in block


def test_helper_legado_e_single_flight_direto_existem():
    html = source()
    assert "function v2RunLegacyDataFallback(token,competencias)" in html
    assert "let v2DirectDataPending=null;" in html
    assert "v2DirectDataPending && v2DirectDataPending.key===directKey" in html


def test_bootstrap_aplica_marcador_de_transporte_sql():
    html = source()
    apply_start = html.index("function v2ApplyBootstrapData(payload)")
    apply_end = html.index("window.v2LoadBootstrapFast=async function", apply_start)
    block = html[apply_start:apply_end]
    assert "window.__v2CommercialTransport='FASTAPI_POSTGRESQL';" in block


def test_bootstrap_http_e_no_cache_e_versao_h1():
    main = MAIN.read_text(encoding="utf-8")
    endpoint_start = main.index('@app.get("/data/bootstrap")')
    endpoint_end = main.index('@app.get("/data/history-list")', endpoint_start)
    block = main[endpoint_start:endpoint_end]

    assert 'response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"' in block
    assert "scope_mensal_dashboard(" in block
    assert 'version="2.0.0-phase2i2"' in main
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
