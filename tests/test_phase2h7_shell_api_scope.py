from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def shell_block():
    text = source()
    start = text.index('<script id="v2-phase1b-shell">')
    end = text.index('</script>', start)
    return text[start:end]


def test_h7_version_and_badge():
    main = MAIN.read_text(encoding="utf-8")
    assert '2.0.0-phase2i2' in main
    assert 'HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA' in source()


def test_shell_defines_its_own_api_helper_before_restore_listener():
    block = shell_block()
    assert 'async function v2ShellApi(path,options={})' in block
    assert block.index('async function v2ShellApi(path,options={})') < block.index("window.addEventListener('load',async function(){")
    assert "credentials:'include'" in block
    assert "const err=new Error(message);" in block
    assert "err.status=response.status;" in block


def test_restore_uses_shell_local_helper_not_permission_iife_helper():
    block = shell_block()
    start = block.index('async function restoreV2Session(){')
    end = block.index('// Acesso realmente novo:', start)
    restore = block[start:end]
    assert "const me=await v2ShellApi(restoreUrl,{cache:'no-store'});" in restore
    assert 'await v2Api(' not in restore
    assert "'/auth/me?restore='" in restore


def test_shell_logout_uses_same_local_helper():
    block = shell_block()
    assert "v2ShellApi('/auth/logout',{method:'POST'})" in block
    assert "v2Api('/auth/logout',{method:'POST'})" not in block


def test_h7_keeps_h6_no_store_and_diagnostics():
    block = shell_block()
    assert "cache:'no-store'" in block
    assert 'window.__v2F5AuthLastStatus' in block
    assert 'window.__v2F5AuthLastMessage' in block
    assert '[2H8 AUTH-ME]' in block
