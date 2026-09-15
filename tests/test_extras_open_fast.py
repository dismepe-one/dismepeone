from pathlib import Path


def test_extras_nao_carrega_all_automaticamente():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    start = html.index("window.loadCampanhasExtras=async function")
    end = html.index("window.loadExtraPartial=async function", start)
    block = html[start:end]

    assert "Selecione uma campanha para ver a parcial" in block
    assert "await loadExtraPartial()" not in block
    assert "carregar sob demanda" in block


def test_botao_tempos_continua_ausente():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")
    assert '<button id="v2PerfAlwaysVisible"' not in html
    assert '<button id="v2PerfBtn"' not in html
