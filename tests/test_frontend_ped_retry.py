from pathlib import Path

def test_clientes_ped_primeiro_load_tem_retry_automatico():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")
    assert "const maxTentativas=3;" in html
    assert "fotografiaPareceNaoInicializada" in html
    assert "Confirmando a Base de Clientes PED..." in html
    assert "/data/clientes-ped" in html
