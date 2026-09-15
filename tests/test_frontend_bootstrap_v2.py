from pathlib import Path


def test_frontend_usa_bootstrap_direto():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    assert "/data/bootstrap" in html
    assert "v2LoadBootstrapFast" in html
    assert "__v2BootstrapReady" in html
    assert "FASTAPI_BOOTSTRAP_MENSAL" not in html  # backend marker only
    assert "DISMEPE_V2_PERF_LAST" in html
