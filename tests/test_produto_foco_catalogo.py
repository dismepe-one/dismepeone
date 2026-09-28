from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_produto_foco_label_usa_catalogo_mapa_e_primeiro_nome_fornecedor():
    js = (ROOT / "frontend" / "produto-foco-labels.js").read_text(encoding="utf-8")

    assert "/data/produto-foco-catalogo?codigos=" in js
    assert "catalog?.fornecedor" in js
    assert "catalog?.descricao" in js
    assert "clean.split(' ')[0]" in js
    assert "' - COD '+code" in js


def test_campanhas_extras_continua_usando_codigo_estruturado():
    py = (ROOT / "api" / "extras_reads.py").read_text(encoding="utf-8")

    assert 'campaign.get("codigoProdutoFoco")' in py
    assert '"codigoProdutoFoco"' in py
