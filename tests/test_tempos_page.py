from pathlib import Path


def test_tempos_page_existe():
    root = Path(__file__).resolve().parents[1]
    page = (root / "frontend" / "tempos-v2.html").read_text(encoding="utf-8")
    assert "TEMPOS 2.0" in page
    assert "DISMEPE_V2_PERF_LAST" in page


def test_tempos_so_por_url_sem_botao_flutuante():
    root = Path(__file__).resolve().parents[1]
    html = (root / "frontend" / "portal-v2-homolog.html").read_text(encoding="utf-8")
    page = (root / "frontend" / "tempos-v2.html").read_text(encoding="utf-8")
    assert 'id="v2PerfAlwaysVisible"' not in html
    assert 'id="v2PerfBtn"' not in html
    assert "TEMPOS 2.0" in page
