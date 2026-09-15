from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'frontend' / 'portal-v2-homolog.html'
MAIN = ROOT / 'api' / 'main.py'


def source():
    return HTML.read_text(encoding='utf-8')


def v44_block():
    s = source()
    start = s.index('<script id="v44-mobile-chart-adapter">')
    end = s.index('</script>', start)
    return s[start:end]


def test_phase2h9_markers():
    assert '2.0.0-phase2i2' in MAIN.read_text(encoding='utf-8')
    assert 'HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA' in source()


def test_v44_no_longer_forces_chart_resize():
    block = v44_block()
    assert 'chart.resize(' not in block
    assert 'responsive=true' in block


def test_v44_has_reentry_guard_and_idempotent_updates():
    block = v44_block()
    assert 'const adaptingCharts=new WeakSet();' in block
    assert 'adaptingCharts.has(chart)' in block
    assert 'adaptingCharts.add(chart)' in block
    assert 'adaptingCharts.delete(chart)' in block
    assert 'setIfChanged' in block
    assert "if(optionChanged){\n        chart.update('none');" in block


def test_v44_preserves_mobile_height_logic_and_resize_listener():
    block = v44_block()
    assert "Math.max(320,labels.length*40)+'px'" in block
    assert "Math.max(280,Math.min(420,labels.length*30))+'px'" in block
    assert "window.addEventListener(\n    'resize'" in block
    assert 'window.v44AdaptCharts?.();' in block
