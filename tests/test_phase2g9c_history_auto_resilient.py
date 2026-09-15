from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source() -> str:
    return HTML.read_text(encoding="utf-8")


def history_block() -> str:
    text = source()
    start = text.index('<script id="v39-history-system">')
    end = text.index('<style id="v40-extra-history-style">', start)
    return text[start:end]


def test_v2_session_can_refresh_without_legacy_token():
    block = history_block()
    assert "function h39SessionKey()" in block
    assert "window.__v2Authenticated===true" in block
    assert "if(!requestToken)return Promise.resolve(false);" not in block
    assert "if(!requestKey)return Promise.resolve(false);" in block


def test_direct_route_does_not_start_legacy_fallback_without_token():
    block = history_block()
    assert "if(!requestToken){" in block
    assert "throw error;" in block
    assert "return await postApi" in block


def test_history_starts_from_real_public_home_path_not_unexported_local_function():
    block = history_block()
    assert "function h39InstallV2SessionHook()" in block
    assert "const old=window.openHome;" in block
    assert "window.openHome=wrapped;" in block
    assert "window.v2OpenHomeImmediately=wrapped;" not in block
    assert "h39StartSessionRefreshOnce();" in block
    assert "Date.now()-h39LastListRefreshAt>10000" in block
    assert "},400);" not in block


def test_auto_refresh_marks_session_complete_only_after_success():
    block = history_block()
    assert "let h39AutoSessionCompletedKey='';" in block
    assert "if(h39AutoSessionCompletedKey===requestKey)return false;" in block
    assert "if(ok===true){" in block
    assert "h39AutoSessionCompletedKey=requestKey;" in block
    assert "if(window.__v2Authenticated===true)" in block


def test_logout_rearms_auto_history_for_same_user_relogin():
    block = history_block()
    assert "function h39InstallLogoutHook()" in block
    assert "h39AutoSessionTargetKey='';" in block
    assert "h39AutoSessionCompletedKey='';" in block
    assert "h39AutoRetryCount=0;" in block
    assert "window.logout=wrapped;" in block


def test_single_flight_is_keyed_by_v2_session():
    block = history_block()
    assert "h39PendingV185.key===requestKey" in block
    assert "h39RefreshListV185_(" in block
    assert "h39SessionKey()!==requestKey" in block


def test_manual_and_automatic_refresh_converge_on_same_direct_request():
    block = history_block()
    assert 'onclick="hist39RefreshHistoryList({preserveSelection:true,force:true})"' in block
    assert "window.hist39RefreshHistoryList({" in block
    assert "automatic:true" in block
    assert block.count("v2HistoryListDirect('mensal','HIST39_LISTAR',requestToken)") == 1


def test_authenticated_body_state_is_observed_as_second_real_trigger():
    block = history_block()
    assert "function h39InstallAuthReadyObserver()" in block
    assert "new MutationObserver" in block
    assert "document.body.classList.contains('v51-auth-ready')" in block
    assert "h39InstallAuthReadyObserver();" in block


def test_auto_refresh_retries_transient_or_early_session_failures():
    block = history_block()
    assert "const H39_AUTO_RETRY_DELAYS=[250,700,1600,3500,7000];" in block
    assert "h39LastListErrorStatus=Number(e?.status||0);" in block
    assert "const definitive=status===400||status===403;" in block
    assert "h39ScheduleFastRefresh(retryDelay);" in block
    assert "return h39ScheduleFastRefresh(180);" in block


def test_auto_refresh_keeps_manual_path_unchanged():
    block = history_block()
    assert 'onclick="hist39RefreshHistoryList({preserveSelection:true,force:true})"' in block
    assert "v2HistoryListDirect('mensal','HIST39_LISTAR',requestToken)" in block


def test_g9c_build_marker():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
