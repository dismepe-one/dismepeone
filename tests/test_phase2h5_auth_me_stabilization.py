from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def restore_block():
    text = source()
    start = text.index("async function restoreV2Session(){")
    end = text.index("    // Acesso realmente novo: mantém o login normal.", start)
    return text[start:end]


def test_h5_version_and_badge():
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()


def test_auth_me_retry_window_extends_to_six_seconds_without_cumulative_waits():
    block = restore_block()
    assert "const retryAtMs=[0,120,350,800,1500,2500,4000,6000];" in block
    assert "retryAtMs[i]-elapsed" in block
    assert "setTimeout(r,wait)" in block
    assert "const delays=[0,120,350,800]" not in block


def test_session_absent_remains_retryable_but_expired_or_invalid_is_definitive():
    block = restore_block()
    assert "isDefinitiveSessionError" in block
    assert "sessão expirada" in block
    assert "sessão inválida" in block
    assert "sessão ausente" not in block.lower().split("function isdefinitivesessionerror",1)[1].split("for(let i=0",1)[0]
    assert "if(isDefinitiveSessionError(e))" in block


def test_fallback_remains_after_restore_attempts_not_in_parallel():
    text = source()
    listener_start = text.index("window.addEventListener('load',async function(){", text.index("async function restoreV2Session") - 500)
    listener_end = text.index("  const oldLogout=window.logout;", listener_start)
    block = text[listener_start:listener_end]
    assert "const me=await restoreV2Session();" in block
    assert "window.__v2F5DataOwner='FASTAPI_POSTGRESQL';" in block
    assert "window.__v2F5DataOwner='LEGACY_AFTER_AUTH_ME_FAILURE';" in block
    assert block.index("const me=await restoreV2Session();") < block.index("LEGACY_AFTER_AUTH_ME_FAILURE")


def test_h5_exposes_restore_diagnostics_without_tokens():
    block = restore_block()
    assert "window.__v2F5AuthRestoreAttempt" in block
    assert "window.__v2F5AuthRestoreMs" in block
    assert "window.__v2F5AuthRestoreStatus" in block
    assert "[2H8 AUTH-ME]" in block
    assert "authToken" not in block
