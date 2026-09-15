from pathlib import Path


def test_overlay_aparece_mas_sai_apos_pintura():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    assert "v2GlobalLoadingReleaseAfterPaint" in html
    assert "requestAnimationFrame(function()" in html
    assert "setTimeout(release,350)" in html

    start = html.index("window.v2GlobalLoadingShow=function")
    end = html.index("window.v2GlobalLoadingHide=function", start)
    show_block = html[start:end]
    assert "classList.add('v2-show')" not in show_block
    assert "classList.remove('v2-show')" in show_block

    # Não pode existir regra que esconda o overlay permanentemente.
    assert "v2-global-loading-disabled-phase2f1" not in html


def test_async_wrapper_nao_espera_fetch_para_esconder_overlay():
    html = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")

    start = html.index("function wrapAsync(name,label)")
    end = html.index("// Installed at the very end", start)
    block = html[start:end]

    assert "v2GlobalLoadingReleaseAfterPaint()" in block
    assert "return await old.apply" not in block
