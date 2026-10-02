from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V22"


def install_commercial_intelligence_ui_v22() -> None:
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

    # Padronização do nome exibido. O campo continua sendo o Pc.Custo do mapa.
    text = text.replace("Preço médio", "Custo Médio")
    text = text.replace("Preço Médio", "Custo Médio")

    # No rascunho de promoção, transforma o markup em um campo editável.
    old_markup_cell = '<td><b>${promoMarkup(i.precoPromocional,i.custo).toFixed(2).replace(\'.\',\',\')}%</b></td>'
    new_markup_cell = '<td><input class="promo-markup-input" data-code="${esc(i.codigo)}" inputmode="decimal" value="${promoMarkup(i.precoPromocional,i.custo).toFixed(2).replace(\'.\',\',\')}"></td>'
    if old_markup_cell in text:
        text = text.replace(old_markup_cell, new_markup_cell, 1)

    # Preço -> markup: atualiza imediatamente enquanto digita e salva ao sair.
    old_price_wire = "E.promoItems.querySelectorAll('.promo-price-input').forEach(inp=>{inp.addEventListener('change',()=>{const item=items.find(i=>i.codigo===inp.dataset.code);if(item){const price=parsePrice(inp.value);if(price>0){item.precoPromocional=price;savePromo(p)}}})});"
    new_price_wire = r'''E.promoItems.querySelectorAll('.promo-price-input').forEach(inp=>{
      inp.addEventListener('input',()=>{
        const item=items.find(i=>i.codigo===inp.dataset.code);if(!item)return;
        const price=parsePrice(inp.value);const markup=promoMarkup(price,item.custo);
        const target=E.promoItems.querySelector('.promo-markup-input[data-code="'+CSS.escape(inp.dataset.code)+'"]');
        if(target&&price>0)target.value=markup.toFixed(2).replace('.',',');
      });
      inp.addEventListener('change',()=>{
        const item=items.find(i=>i.codigo===inp.dataset.code);if(item){const price=parsePrice(inp.value);if(price>0){item.precoPromocional=price;savePromo(p)}}
      });
    });
    E.promoItems.querySelectorAll('.promo-markup-input').forEach(inp=>{
      const syncPrice=()=>{
        const item=items.find(i=>i.codigo===inp.dataset.code);if(!item)return 0;
        const raw=String(inp.value||'').trim().replace('%','').replace(',','.');
        const markup=Number(raw);const cost=Number(item.custo||0);
        if(!Number.isFinite(markup)||cost<=0)return 0;
        const price=Math.max(0,cost*(1+(markup/100)));
        const target=E.promoItems.querySelector('.promo-price-input[data-code="'+CSS.escape(inp.dataset.code)+'"]');
        if(target)target.value=price.toFixed(2).replace('.',',');
        return price;
      };
      inp.addEventListener('input',syncPrice);
      inp.addEventListener('change',()=>{
        const item=items.find(i=>i.codigo===inp.dataset.code);if(!item)return;
        const price=syncPrice();if(price>0){item.precoPromocional=price;savePromo(p)}
      });
    });'''
    if old_price_wire in text:
        text = text.replace(old_price_wire, new_price_wire, 1)

    css_anchor = "</style>"
    css_patch = r'''
.promo-markup-input{width:94px;height:32px;border:1px solid var(--bd);border-radius:8px;padding:0 8px;text-align:right;font-weight:900;background:#fff;color:var(--tx)}
.promo-markup-input:focus{outline:none;border-color:#079b72;box-shadow:0 0 0 3px rgba(7,155,114,.10)}
@media(max-width:760px){.promo-markup-input{border:0!important;background:transparent!important;box-shadow:none!important;pointer-events:none!important;padding:0!important;width:72px!important}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v22.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
