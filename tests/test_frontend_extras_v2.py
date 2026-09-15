from pathlib import Path


def test_extras_tela_principal_nao_usa_gateway():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    start = html.index("window.loadCampanhasExtras=async function")
    end = html.index("window.renderExtraRows=function", start)
    block = html[start:end]

    assert "v2FetchCampanhasExtras" in block
    assert "LISTARCAMPANHASEXTRAS" not in block
    assert "PARCIALTODASCAMPANHASEXTRAS" not in block
    assert "PARCIALCAMPANHAEXTRA" not in block


def test_sem_botao_tempos_flutuante():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    assert '<button id="v2PerfAlwaysVisible"' not in html
    assert '<button id="v2PerfBtn"' not in html
