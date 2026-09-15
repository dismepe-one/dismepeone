from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def test_h4_version_markers():
    assert '2.0.0-phase2i2' in MAIN.read_text(encoding="utf-8")
    assert 'HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA' in source()


def test_bootstrap_observability_counters_and_snapshot_exist():
    s = source()
    assert 'window.__v2Obs=window.__v2Obs||{' in s
    assert 'window.v2ObservabilitySnapshot=function()' in s
    assert 'bootstrapStarted:0' in s
    assert 'bootstrapSucceeded:0' in s
    assert 'bootstrapFailed:0' in s
    assert 'bootstrapSingleFlightReused:0' in s
    assert 'bootstrapOverlapDetected:0' in s
    assert "v2ObsEvent('bootstrap_start'" in s
    assert "v2ObsEvent('bootstrap_ok'" in s
    assert "v2ObsEvent('bootstrap_failed'" in s


def test_observability_does_not_change_single_flight_semantics():
    s = source()
    start = s.index('window.v2LoadBootstrapFast=async function(opts={}){')
    end = s.index('async function v2AwaitLegacySession()', start)
    block = s[start:end]
    assert 'if(window.__v2BootstrapPromise){' in block
    assert 'if(!options.force){' in block
    assert 'return await window.__v2BootstrapPromise;' in block
    assert "v2ObsEvent('bootstrap_overlap_detected'" in block


def test_legacy_fallback_is_observed_but_still_centralized():
    s = source()
    assert "function v2RunLegacyDataFallback(token,competencias)" in s
    assert "v2ObsEvent('legacy_fallback_start'" in s
    assert "v2ObsEvent('legacy_fallback_ok'" in s
    assert "v2ObsEvent('legacy_fallback_failed'" in s
    assert "'bootstrap_sql_failed'" in s
    assert "'session_not_v2_authenticated'" in s
    assert "acao:'dados'" in s  # fallback operacional preservado no core legado


def test_backend_bootstrap_observability_headers_and_logs_exist():
    s = MAIN.read_text(encoding="utf-8")
    assert 'logger = logging.getLogger("uvicorn.error")' in s
    assert 'request.state.request_id = request_id' in s
    assert '"[2H4 OBS] bootstrap_http request_id=%s status=%s elapsed_ms=%s competencia=%s"' in s
    assert '"[2H4 OBS] bootstrap_ok request_id=%s elapsed_ms=%s competencia=%s mensal_versao=%s"' in s
    assert '"[2H4 OBS] bootstrap_failed request_id=%s elapsed_ms=%s competencia=%s error=%s"' in s
    assert 'response.headers["X-DISMEPE-Bootstrap-Ms"]' in s
    assert 'response.headers["X-DISMEPE-Bootstrap-Competencia"]' in s
