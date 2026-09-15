from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source() -> str:
    return PORTAL.read_text(encoding="utf-8")


def legacy_onload_block() -> str:
    html = source()
    start = html.index("window.onload=function(){")
    end = html.index("// Expostos para módulos", start)
    return html[start:end]


def auth_restore_block() -> str:
    html = source()
    start = html.index("window.addEventListener('load',async function(){")
    end = html.index("const oldLogout=window.logout;", start)
    return html[start:end]


def test_f5_legado_nao_dispara_load_data_antes_do_auth_me():
    block = legacy_onload_block()
    assert "__v2F5DataOwner='AUTH_ME_PENDING'" in block
    assert ".loadDataFromCloudV2?.()" not in block
    assert "loadDataFromCloudV2?.()" not in block
    assert "classList.remove('v67-local-session')" not in block


def test_auth_me_confirmado_assume_bootstrap_postgresql():
    block = auth_restore_block()
    success = block.index("window.__v2Authenticated=true")
    owner = block.index("__v2F5DataOwner='FASTAPI_POSTGRESQL'", success)
    bootstrap = block.index("window.v2LoadBootstrapFast({force:true})", owner)
    assert success < owner < bootstrap


def test_dados_legado_so_e_liberado_depois_da_falha_do_auth_me():
    block = auth_restore_block()
    catch = block.index("}catch(e){")
    legacy = block.index("if(legacyLocalReady){", catch)
    owner = block.index("__v2F5DataOwner='LEGACY_AFTER_AUTH_ME_FAILURE'", legacy)
    call = block.index("window.loadDataFromCloudV2?.()", owner)
    assert catch < legacy < owner < call
    assert "classList.remove('v67-local-session')" in block[owner:]


def test_fallback_legado_continua_preservado():
    html = source()
    assert "function v2RunLegacyDataFallback(token,competencias)" in html
    assert "return await v2RunLegacyDataFallback(token,competencias)" in html
    assert "LEGACY_AFTER_AUTH_ME_FAILURE" in html


def test_versao_h2():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
