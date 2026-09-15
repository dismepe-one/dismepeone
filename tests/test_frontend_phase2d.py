from pathlib import Path


def test_login_aplica_bootstrap_antes_de_abrir_home():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    apply_pos = html.index("v2ApplyBootstrapData(result.bootstrap)")
    open_pos = html.index("v2OpenHomeImmediately();", apply_pos)
    assert apply_pos < open_pos


def test_botao_tempos_removido_do_portal():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    assert '<button id="v2PerfBtn"' not in html
    assert '<button id="v2PerfAlwaysVisible"' not in html


def test_mede_telas():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    assert "v2-screen-performance" in html
    assert "Resumo de Ganhos" in html
    assert "Clientes PED" in html
