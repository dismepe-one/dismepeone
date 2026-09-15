from pathlib import Path


def test_resumo_usa_endpoint_v2_e_nao_admin_action():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    start = html.index("window.loadResumoPremiacoes=async function")
    end = html.index("window.renderResumoPremiacoes=function", start)
    block = html[start:end]

    assert "/data/resumo-ganhos" in block or "v2FetchResumoGanhos" in block
    assert "callAdminAction('RESUMOPREMIACOES')" not in block
    assert "callAdminAction('RESUMOPREMIACOES')" not in block
