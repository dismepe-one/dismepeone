from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def test_h6_version_and_badge():
    assert 'version="2.0.0-phase2i2"' in MAIN.read_text(encoding="utf-8")
    assert '"version": "2.0.0-phase2i2"' in MAIN.read_text(encoding="utf-8")
    assert 'HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA' in source()


def test_auth_me_response_is_explicitly_no_store():
    main = MAIN.read_text(encoding="utf-8")
    start = main.index('@app.get("/auth/me"')
    end = main.index('@app.get(', start + 10)
    block = main[start:end]
    assert 'response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"' in block
    assert 'response.headers["Pragma"] = "no-cache"' in block
    assert 'response.headers["Expires"] = "0"' in block


def test_f5_restore_uses_unique_no_store_auth_me_url():
    text = source()
    start = text.index('async function restoreV2Session()')
    end = text.index('// Acesso realmente novo:', start)
    block = text[start:end]
    assert "const restoreUrl='/auth/me?restore='+encodeURIComponent(" in block
    assert "String(Date.now())+'-'+String(i+1)" in block
    assert "const me=await v2ShellApi(restoreUrl,{cache:'no-store'});" in block
    assert "v2ShellApi('/auth/me')" not in block


def test_h6_records_last_restore_failure_without_token():
    text = source()
    start = text.index('async function restoreV2Session()')
    end = text.index('// Acesso realmente novo:', start)
    block = text[start:end]
    assert 'window.__v2F5AuthLastStatus' in block
    assert 'window.__v2F5AuthLastMessage' in block
    assert '[2H8 AUTH-ME]' in block
    assert 'authToken' not in block
