from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def test_i1_build_markers():
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()


def test_extra_admin_campaign_list_prefers_fastapi_snapshot():
    text = source()
    start = text.index("async function loadExtraAdminData()")
    end = text.index("window.renderExtraAdminList", start)
    block = text[start:end]
    assert "fetch('/data/campanhas-extras?id=LIST'" in block
    assert "credentials:'include'" in block
    assert "cache:'no-store'" in block
    assert "LISTARCAMPANHASEXTRAS" in block  # fallback preservado


def test_extra_admin_users_prefers_fastapi_snapshot():
    text = source()
    start = text.index("window.loadExtraUsers=async function()")
    end = text.index("function extraUserDisplayName", start)
    block = text[start:end]
    assert "fetch('/data/extras-users'" in block
    assert "LISTARUSUARIOSCAMPANHASEXTRAS" in block  # fallback preservado
    assert "response.status===401||response.status===403" in block


def test_extras_users_endpoint_is_read_only_and_permission_guarded():
    main = MAIN.read_text(encoding="utf-8")
    start = main.index('@app.get("/data/extras-users")')
    end = main.index('@app.get("/data/resumo-ganhos")', start)
    block = main[start:end]
    assert 'cache_get(modulo="USUARIOS"' in block
    assert 'status_code=403' in block
    assert '"CAMPANHAS_EXTRAS_CRIAR"' in block
    assert '"transporte": "FASTAPI_USUARIOS_SNAPSHOT"' in block
