from pathlib import Path


def source():
    return (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")


def test_legacy_access_autoloads_are_disabled():
    text = source()
    assert "__v70AccessAutoLoadDisabledByV2" in text
    assert "__v2108AccessAutoloadDisabledByV2" in text

    v70 = text[text.index('<script id="v70-access-log-auto-load-final">'):
               text.index('</script>', text.index('<script id="v70-access-log-auto-load-final">'))]
    assert "ensureAccessLoaded" not in v70
    assert "visibilitychange" not in v70

    v2108 = text[text.index('<script id="v2108-access-autoload-resilient">'):
                 text.index('</script>', text.index('<script id="v2108-access-autoload-resilient">'))]
    assert "MutationObserver" not in v2108
    assert "setTimeout(step" not in v2108


def test_access_load_is_single_flight():
    text = source()
    assert "let accessLoadPromise=null;" in text
    assert "if(accessLoadPromise) return accessLoadPromise;" in text
    assert "accessLoadPromise=null;" in text


def test_access_charts_do_not_redraw_same_snapshot():
    text = source()
    assert "let accessChartsSignature='';" in text
    assert "nextSignature===accessChartsSignature" in text
    assert text.count("animation:false") >= 2


def test_manual_refresh_is_explicit_force():
    text = source()
    assert 'onclick="loadAccessLog({force:true})"' in text
