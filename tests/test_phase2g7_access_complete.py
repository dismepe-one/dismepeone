from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/"frontend"/"portal-v2-homolog.html"
MAIN=ROOT/"api"/"main.py"

def source():
    return HTML.read_text(encoding="utf-8")

def test_access_single_flight_preserved():
    text=source()
    assert "let accessLoadPromise=null;" in text
    assert "if(accessLoadPromise) return accessLoadPromise;" in text

def test_access_direct_flow_replaces_g7_preload():
    text=source()
    assert "v2PrimeAccessLog" not in text
    assert 'id="v2g7-access-visible-autoload"' not in text
    start=text.index("window.openAccessLog=async function()")
    end=text.index("window.closeAccessLog=function()",start)
    assert "force:true" in text[start:end]

def test_portal_html_is_no_store():
    text=MAIN.read_text(encoding="utf-8")
    assert "no-store, no-cache, must-revalidate, max-age=0" in text

def test_g8_visible_badge():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
