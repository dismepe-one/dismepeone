from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V20"


def install_commercial_intelligence_ui_v20() -> None:
    from . import commercial_intelligence as ci

    page = getattr(ci, "PAGE_FILE", None)
    if not isinstance(page, Path):
        return
    try:
        text = page.read_text(encoding="utf-8")
    except Exception:
        return
    if _MARKER in text:
        return

    # Qtd. última entrada representa unidades inteiras. Não usa formatação
    # pt-BR para evitar ponto/vírgula como separadores visuais.
    text = text.replace(
        "${fmt(x.quantidadeUltimaEntrada||0)}",
        "${String(Math.max(0,Math.round(Number(x.quantidadeUltimaEntrada||0))))}",
    )

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v20.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
