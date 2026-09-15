from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def test_phase_version_and_badge():
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()


def test_cm19_dormant_fallback_was_removed():
    s = source()
    assert "async function cm19FallbackDados" not in s
    assert "cm19FallbackDados(" not in s


def test_cm20_is_local_only_and_has_no_dados_request():
    s = source()
    start = s.index("async function cm20LoadManagerFromDados")
    end = s.index("function cm20CompetenciasFromPayload", start) if "function cm20CompetenciasFromPayload" in s[start:] else start + 12000
    block = s[start:end]
    assert "payloadPronto=null" not in block
    assert "payloadPronto || await postApi" not in block
    assert "acao:'DADOS'" not in block
    assert 'acao:"DADOS"' not in block
    assert "const payload=payloadPronto;" in block


def test_all_active_cm20_callers_pass_second_argument():
    s = source()
    # Declaration + exactly three calls are expected in this phase.
    occurrences = [m.start() for m in re.finditer(r"cm20LoadManagerFromDados\(", s)]
    assert len(occurrences) == 4
    call_positions = occurrences[1:]
    for pos in call_positions:
        tail = s[pos:pos+600]
        # Every active call must visibly contain a comma before its closing call.
        assert "," in tail.split(");", 1)[0]


def test_real_legacy_fallback_remains_available():
    s = source()
    assert "function v2RunLegacyDataFallback" in s or "const v2RunLegacyDataFallback" in s or "async function v2RunLegacyDataFallback" in s
    assert "acao:'dados'" in s
