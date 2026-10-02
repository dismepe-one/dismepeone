from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V11"


def install_commercial_intelligence_ui_v11() -> None:
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

    # Mostra o markup ao lado do preço promocional na linha do produto.
    old_input = '<input class="price-entry" data-code="${esc(x.codigo)}" inputmode="decimal" placeholder="R$ 0,00">'
    new_input = '<div class="promo-price-cell"><input class="price-entry" data-code="${esc(x.codigo)}" inputmode="decimal" placeholder="R$ 0,00"><span class="promo-live-markup" data-code="${esc(x.codigo)}">—</span></div>'
    if old_input in text:
        text = text.replace(old_input, new_input, 1)

    css_anchor = '</style>'
    css_patch = r'''
.promo-price-cell{display:flex;align-items:center;gap:7px;min-width:165px}.promo-live-markup{display:inline-flex;align-items:center;justify-content:center;min-width:58px;height:27px;padding:0 7px;border-radius:7px;background:#eef5f2;color:#35554d;font-size:8px;font-weight:950;font-variant-numeric:tabular-nums}.promo-live-markup.positive{background:#ecfdf5;color:#047857}.promo-live-markup.negative{background:#fff1f2;color:#be123c}.promo-live-markup.zero{background:#fffbeb;color:#b45309}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    # Atualiza o markup em tempo real enquanto o preço é digitado e mantém Enter
    # como confirmação para adicionar/atualizar o item na promoção ativa.
    old_wire = "function wirePriceEntries(){E.content?.querySelectorAll('.price-entry').forEach(inp=>{inp.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();const price=parsePrice(inp.value);if(price<=0){inp.focus();return}const product=S.all.find(x=>String(x.codigo)===String(inp.dataset.code));if(!product)return;await addToPromo(product,price);inp.value='';inp.placeholder='Adicionado';setTimeout(()=>inp.placeholder='R$ 0,00',1200)})})}"
    new_wire = r'''function wirePriceEntries(){E.content?.querySelectorAll('.price-entry').forEach(inp=>{const code=String(inp.dataset.code||'');const product=S.all.find(x=>String(x.codigo)===code);const badge=E.content?.querySelector(`.promo-live-markup[data-code="${CSS.escape(code)}"]`);const refresh=()=>{if(!badge)return;const price=parsePrice(inp.value);const cost=Number(product?.preco||0);if(price<=0||cost<=0){badge.textContent='—';badge.className='promo-live-markup';return}const markup=((price/cost)-1)*100;badge.textContent=`${markup.toFixed(2).replace('.',',')}%`;badge.className='promo-live-markup '+(markup>0?'positive':markup<0?'negative':'zero')};inp.addEventListener('input',refresh);inp.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();const price=parsePrice(inp.value);if(price<=0){inp.focus();return}if(!product)return;await addToPromo(product,price);refresh();inp.placeholder='Adicionado';setTimeout(()=>inp.placeholder='R$ 0,00',1200)});refresh()})}'''
    if old_wire in text:
        text = text.replace(old_wire, new_wire, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v11.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
