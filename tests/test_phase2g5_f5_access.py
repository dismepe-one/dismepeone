from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return HTML.read_text(encoding="utf-8")


def test_access_first_load_does_not_depend_on_frontend_permission_sync():
    text = source()
    start = text.index("window.openAccessLog=async function()")
    end = text.index("window.closeAccessLog=function()", start)
    block = text[start:end]
    assert "if(!canManageAccessLog()) return false" not in block
    assert "force:true" in block


def test_access_load_has_no_duplicate_watchdog():
    text = source()
    assert "v2EnsureAccessFirstPaint" not in text


def test_access_green_processing_is_hidden():
    text = source()
    assert 'id="v2g5-access-no-green-processing"' in text
    assert "#accessLogModule #v68GlobalActivity" in text
    assert "window.v68ActivityEnd?.(true)" in text


def test_f5_always_restores_v2_cookie_even_with_legacy_session():
    text = source()
    assert "const legacyLocalReady=(" in text
    assert "await v2ShellApi(restoreUrl,{cache:'no-store'})" in text
    assert "window.v2LoadBootstrapFast({force:true})" in text
    assert "if(!legacyLocalReady)" in text


def test_home_times_are_persisted_and_restored():
    text = source()
    assert "DISMEPE_V2_HOME_TIMES" in text
    assert 'id="v2g5-home-times-f5"' in text


def test_backend_extras_time_has_memory_fallback():
    text = MAIN.read_text(encoding="utf-8")
    assert 'cached_extras = _EXTRAS_SNAPSHOT_CACHE.get("EXTRAS")' in text
