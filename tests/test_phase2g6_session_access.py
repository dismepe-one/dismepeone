from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/"frontend"/"portal-v2-homolog.html"
MAIN=ROOT/"api"/"main.py"

def source():
    return HTML.read_text(encoding="utf-8")

def test_session_hint_lifecycle():
    text=source()
    assert "DISMEPE_V2_SESSION_HINT" in text
    assert "v2SaveSessionHint();" in text
    assert "window.v2ClearSessionHint?.();" in text

def test_f5_auth_me_has_retries():
    text=source()
    assert "const retryAtMs=[0,120,350,800,1500,2500,4000,6000];" in text
    assert "const me=await v2ShellApi(restoreUrl,{cache:'no-store'});" in text

def test_legacy_boot_respects_v2_session_hint():
    text=source()
    assert "const hasV2Hint=window.v2HasRecentSessionHint?.()===true;" in text

def test_access_is_direct_not_prefetched():
    text=source()
    assert "v2PrimeAccessLog" not in text
    assert "window.openAccessLog=async function()" in text

def test_health_version_g8():
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
