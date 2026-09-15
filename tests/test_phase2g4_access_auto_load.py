from pathlib import Path

def source():
    return (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

def test_first_access_uses_force_path():
    text=source()
    start=text.index("window.openAccessLog=async function()")
    end=text.index("window.closeAccessLog=function()",start)
    assert "force:true" in text[start:end]

def test_access_home_card_does_not_wait_for_legacy_token():
    text=source()
    assert "/openAccessLog\\s*\\(/.test(onclick)" in text

def test_single_flight_is_still_present():
    text=source()
    assert "if(accessLoadPromise) return accessLoadPromise;" in text

def test_manual_refresh_is_force_true():
    text=source()
    assert 'onclick="loadAccessLog({force:true})"' in text
