from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source() -> str:
    return HTML.read_text(encoding="utf-8")


def test_login_2_0_explicitly_kicks_history_after_home_open():
    text = source()
    login_start = text.index("window.login=async function()")
    auth_restore = text.index("window.addEventListener('load',async function()", login_start)
    login = text[login_start:auth_restore]
    assert "window.__v2Authenticated=true;" in login
    assert "v2OpenHomeImmediately();" in login
    assert "setTimeout(()=>window.hist39KickAutoRefresh?.('login'),0);" in login
    assert login.index("window.__v2Authenticated=true;") < login.index("v2OpenHomeImmediately();")
    assert login.index("v2OpenHomeImmediately();") < login.index("hist39KickAutoRefresh?.('login')")


def test_auth_me_restore_explicitly_kicks_same_history_path():
    text = source()
    restore_start = text.index("window.addEventListener('load',async function()")
    restore = text[restore_start:]
    assert "const me=await v2ShellApi(restoreUrl,{cache:'no-store'});" in restore
    assert "window.__v2Authenticated=true;" in restore
    assert "window.v2OpenHomeImmediately?.();" in restore
    assert "setTimeout(()=>window.hist39KickAutoRefresh?.('auth-me'),0);" in restore
    assert restore.index("window.__v2Authenticated=true;") < restore.index("window.v2OpenHomeImmediately?.();")
    assert restore.index("window.v2OpenHomeImmediately?.();") < restore.index("hist39KickAutoRefresh?.('auth-me')")


def test_public_kick_uses_existing_resilient_single_flight_scheduler():
    text = source()
    start = text.index('<script id="v39-history-system">')
    end = text.index('<style id="v40-extra-history-style">', start)
    block = text[start:end]
    assert "window.hist39KickAutoRefresh=function(source)" in block
    assert "return h39StartSessionRefreshOnce();" in block
    assert "h39AutoSessionRunningKey===requestKey" in block
    assert "h39PendingV185.key===requestKey" in block
    assert "H39_AUTO_RETRY_DELAYS" in block


def test_manual_button_remains_unchanged_and_uses_same_refresh_function():
    text = source()
    assert 'onclick="hist39RefreshHistoryList({preserveSelection:true,force:true})"' in text
    assert "window.hist39RefreshHistoryList=function(options)" in text
    assert "v2HistoryListDirect('mensal','HIST39_LISTAR',requestToken)" in text


def test_g9d_build_marker():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
