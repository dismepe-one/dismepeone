from pathlib import Path

def source():
    return (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

def test_access_waits_until_module_is_painted():
    text=source()
    assert "function accessNextPaint()" in text
    start=text.index("window.openAccessLog=async function()")
    end=text.index("window.closeAccessLog=function()",start)
    assert "await accessNextPaint();" in text[start:end]

def test_first_open_loads_directly():
    text=source()
    start=text.index("window.openAccessLog=async function()")
    end=text.index("window.closeAccessLog=function()",start)
    block=text[start:end]
    assert "window.loadAccessLog" in block
    assert "force:true" in block

def test_fetch_success_uses_snapshot_renderer():
    text=source()
    start=text.index("window.loadAccessLog=function(options)")
    end=text.index("window.restoreViewState=function()",start)
    block=text[start:end]
    assert "window.v2FetchAccessLog()" in block
    assert "renderAccessSnapshot(r);" in block
