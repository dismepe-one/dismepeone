from pathlib import Path
import asyncio

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"
HISTORY = ROOT / "api" / "history_reads.py"


def source():
    return HTML.read_text(encoding="utf-8")


def test_history_list_has_fastapi_route():
    text = MAIN.read_text(encoding="utf-8")
    assert '@app.get("/data/history-list")' in text
    assert "history_list(" in text


def test_monthly_history_uses_direct_route_first():
    text = source()
    assert "v2HistoryListDirect('mensal','HIST39_LISTAR',requestToken)" in text


def test_extras_history_uses_direct_route_first():
    text = source()
    assert "'HIST40_LISTAREXTRAS'" in text
    assert "'extras'" in text
    assert "v2HistoryListDirect" in text


def test_history_keeps_legacy_only_as_fallback():
    text = source()
    start = text.index("async function v2HistoryListDirect")
    end = text.index("function h39$", start) if "function h39$" in text[start:] else start + 5000
    block = text[start:end]
    assert "/data/history-list?kind=" in block
    assert "fallback legado" in block
    assert "return await postApi" in block


def test_auth_errors_do_not_fallback():
    text = source()
    assert "Number(error?.status||0)===401" in text
    assert "Number(error?.status||0)===403" in text


def test_backend_reads_sql_snapshots():
    text = HISTORY.read_text(encoding="utf-8")
    assert '"HISTORICO_MENSAL"' in text
    assert '"HISTORICO_EXTRAS"' in text
    assert "cache_get(" in text


def test_only_three_history_items_returned():
    text = HISTORY.read_text(encoding="utf-8")
    assert "items = items[:3]" in text
    assert '"limiteHistorico": 3' in text


def test_g9_build():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
