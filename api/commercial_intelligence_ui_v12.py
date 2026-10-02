from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V12"


def install_commercial_intelligence_ui_v12() -> None:
    from . import commercial_intelligence as ci

    page = getattr(ci, "PAGE_FILE", None)
    if not isinstance(page, Path):
        return
    try:
        text = page.read_text(encoding="utf-8")
    except Exception:
        return
    if _MARKER in text:
        from .commercial_intelligence_ui_v13 import install_commercial_intelligence_ui_v13
        install_commercial_intelligence_ui_v13()
        return

    # Coluna de custo na tabela principal, imediatamente antes do preço promocional.
    old_cols = "['acao','Ação'],['promoPrice','Preço promoção']"
    new_cols = "['acao','Ação'],['preco','Custo'],['promoPrice','Preço promoção']"
    if old_cols in text:
        text = text.replace(old_cols, new_cols, 1)

    old_price_cell = '<td><div class="promo-price-cell"><input class="price-entry" data-code="${esc(x.codigo)}" inputmode="decimal" placeholder="R$ 0,00"><span class="promo-live-markup" data-code="${esc(x.codigo)}">—</span></div></td>'
    new_price_cell = '<td class="num"><b>${money(x.preco||0)}</b></td>' + old_price_cell
    if old_price_cell in text:
        text = text.replace(old_price_cell, new_price_cell, 1)

    # Custo também aparece dentro da promoção montada, apenas para conferência.
    # Continua propositalmente fora das exportações Excel/PDF.
    old_promo_header = '<th>Código</th><th>Produto</th><th>Preço promoção</th><th>Markup promoção</th><th></th>'
    new_promo_header = '<th>Código</th><th>Produto</th><th>Custo</th><th>Preço promoção</th><th>Markup promoção</th><th></th>'
    if old_promo_header in text:
        text = text.replace(old_promo_header, new_promo_header, 1)

    old_promo_row = "<td>${esc(i.codigo)}</td><td>${esc(i.produto||'')}</td><td><input class=\"promo-price-input\""
    new_promo_row = "<td>${esc(i.codigo)}</td><td>${esc(i.produto||'')}</td><td><b>${promoCurrency(i.custo||0)}</b></td><td><input class=\"promo-price-input\""
    if old_promo_row in text:
        text = text.replace(old_promo_row, new_promo_row, 1)

    css_anchor = '</style>'
    css_patch = r'''
.table td.num b{font-variant-numeric:tabular-nums}.promo-items-table td:nth-child(3){white-space:nowrap;font-weight:800;color:#35554d}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v12.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        return

    from .commercial_intelligence_ui_v13 import install_commercial_intelligence_ui_v13
    install_commercial_intelligence_ui_v13()
