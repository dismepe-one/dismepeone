from pathlib import Path


def test_access_screen_uses_python_api():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    start = html.index("window.v2FetchAccessLog")
    end = html.index("window.restoreViewState", start)
    block = html[start:end]

    assert "/data/access-log" in block
    assert "/data/access-user" in block
    assert "callAdminAction('listarAcessos')" not in block
    assert "callAdminAction('detalhesAcesso'" not in block


def test_access_is_migrated_module():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    assert "target.id==='btnAccessLog'" in html
    assert "Preparando Controle de Acessos..." in html
