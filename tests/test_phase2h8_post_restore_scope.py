from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/'frontend'/'portal-v2-homolog.html'
MAIN=ROOT/'api'/'main.py'

def source():
    return HTML.read_text(encoding='utf-8')

def permission_block():
    s=source()
    a=s.index('<script id="permission-system">')
    b=s.index('</script>',a)
    return s[a:b]

def shell_block():
    s=source()
    a=s.index('<script id="v2-phase1b-shell">')
    b=s.index('</script>',a)
    return s[a:b]

def test_h8_markers():
    assert '2.0.0-phase2i2' in MAIN.read_text(encoding='utf-8')
    assert 'HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA' in source()

def test_core_helpers_are_explicitly_exported_before_shell():
    core=permission_block()
    for name in (
        'v2SetPortalStatus',
        'v2RenderImmediateNavigation',
        'v2AwaitLegacySession',
        'v2OpenHomeImmediately',
    ):
        assert f'window.{name} = {name};' in core

def test_restored_path_uses_window_helpers_not_hidden_identifiers():
    block=shell_block()
    restored=block[block.index("window.__v2F5AuthRestoreStatus='RESTORED'"):]
    assert 'window.v2OpenHomeImmediately?.();' in restored
    assert 'window.v2RenderImmediateNavigation?.();' in restored
    assert 'window.v2SetPortalStatus?.(' in restored
    assert 'window.v2AwaitLegacySession?.();' in restored

def test_bootstrap_is_scheduled_after_restored_path_without_hidden_helper_calls():
    block=shell_block()
    assert "window.__v2F5DataOwner='FASTAPI_POSTGRESQL';" in block
    assert 'await window.v2LoadBootstrapFast({force:true});' in block
    # These unqualified helpers were the H7 failure mode.
    for bad in (
        '\n      v2OpenHomeImmediately();',
        '\n      v2RenderImmediateNavigation();',
        '\n      v2SetPortalStatus(',
        'setTimeout(()=>{ v2AwaitLegacySession(); },0);',
    ):
        assert bad not in block

def test_h7_shell_api_fix_remains_intact():
    block=shell_block()
    assert 'async function v2ShellApi(path,options={})' in block
    assert "const me=await v2ShellApi(restoreUrl,{cache:'no-store'});" in block
