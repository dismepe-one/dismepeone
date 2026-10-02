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

    # Mantém o markup editável também dentro da promoção já montada.
    old_markup_cell = '<td><b>${promoMarkup(i.precoPromocional,i.custo).toFixed(2).replace(\'.\',\',\')}%</b></td>'
    new_markup_cell = '<td><input class="promo-markup-input" data-code="${esc(i.codigo)}" inputmode="decimal" value="${promoMarkup(i.precoPromocional,i.custo).toFixed(2).replace(\'.\',\',\')}"></td>'
    if old_markup_cell in text:
        text = text.replace(old_markup_cell, new_markup_cell, 1)

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
.promo-markup-input{width:94px;height:32px;border:1px solid var(--bd);border-radius:8px;padding:0 8px;text-align:right;font-weight:900;background:#fff;color:var(--tx);pointer-events:auto;cursor:text}
.promo-markup-input:focus{outline:none;border-color:#079b72;box-shadow:0 0 0 3px rgba(7,155,114,.10)}
/* Markup editável na própria linha de criação do preço */
input.promo-live-markup{display:inline-block;min-width:76px;width:82px;height:31px;border:1px solid #a9cfc4;border-radius:8px;padding:0 7px;background:#f9fffd;color:var(--tx);font-size:9px;font-weight:900;text-align:right;font-variant-numeric:tabular-nums;cursor:text}
input.promo-live-markup:focus{outline:none;border-color:#079b72;box-shadow:0 0 0 3px rgba(7,155,114,.10)}
@media(max-width:760px){.promo-markup-input{border:0!important;background:transparent!important;box-shadow:none!important;pointer-events:none!important;padding:0!important;width:72px!important}input.promo-live-markup{display:none!important}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    runtime = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_MARKUP_EDITOR_V22
(function(){
  'use strict';

  function numberPt(value){
    let s=String(value??'').trim().replace(/R\$\s?/gi,'').replace(/%/g,'').replace(/\s/g,'');
    if(!s)return 0;
    if(s.includes(','))s=s.replace(/\./g,'').replace(',','.');
    const n=Number(s.replace(/[^0-9+\-.]/g,''));
    return Number.isFinite(n)?n:0;
  }
  function fmt2(n){return Number(n||0).toFixed(2).replace('.',',')}
  function norm(value){
    return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toLowerCase();
  }

  // ===== Lista principal: Custo Médio | Preço promoção + Markup (%) =====
  function mainCostIndex(table){
    const headers=Array.from(table?.querySelectorAll('thead th')||[]).map(th=>norm(th.textContent));
    let idx=headers.findIndex(x=>x==='custo medio');
    if(idx<0)idx=headers.findIndex(x=>x==='preco medio');
    if(idx<0)idx=headers.findIndex(x=>x==='custo');
    return idx;
  }

  function enhanceMainRow(row,costIndex){
    const price=row.querySelector('.price-entry');
    if(!price)return;
    const holder=price.closest('.promo-price-cell')||price.parentElement;
    if(!holder)return;
    const code=String(price.dataset.code||'');
    const costCell=costIndex>=0?row.cells?.[costIndex]:null;

    let markup=holder.querySelector('.promo-live-markup');
    if(!(markup instanceof HTMLInputElement)){
      const input=document.createElement('input');
      input.type='text';
      input.inputMode='decimal';
      input.className='promo-live-markup';
      input.dataset.code=code;
      input.placeholder='Markup %';
      input.setAttribute('aria-label','Markup percentual');
      if(markup)markup.replaceWith(input);else holder.appendChild(input);
      markup=input;
    }

    if(price.dataset.mainMarkupBound!=='1'){
      price.dataset.mainMarkupBound='1';
      price.addEventListener('input',function(){
        const cost=numberPt(costCell?.textContent||'0');
        const value=numberPt(price.value);
        if(cost<=0||value<=0){markup.value='';return;}
        markup.value=fmt2(((value/cost)-1)*100);
      });
    }

    if(markup.dataset.mainPriceBound!=='1'){
      markup.dataset.mainPriceBound='1';
      markup.addEventListener('input',function(){
        const cost=numberPt(costCell?.textContent||'0');
        const pct=numberPt(markup.value);
        if(cost<=0||!String(markup.value||'').trim())return;
        price.value=fmt2(Math.max(0,cost*(1+(pct/100))));
      });
      markup.addEventListener('keydown',function(event){
        if(event.key!=='Enter')return;
        event.preventDefault();
        const cost=numberPt(costCell?.textContent||'0');
        const pct=numberPt(markup.value);
        if(cost<=0||!String(markup.value||'').trim())return;
        price.value=fmt2(Math.max(0,cost*(1+(pct/100))));
        price.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true,cancelable:true}));
      });
    }

    // Caso a linha já venha com preço preenchido, sincroniza o markup ao renderizar.
    const current=numberPt(price.value);
    const cost=numberPt(costCell?.textContent||'0');
    if(current>0&&cost>0&&!String(markup.value||'').trim())markup.value=fmt2(((current/cost)-1)*100);
  }

  function enhanceMainTable(){
    const tables=document.querySelectorAll('#ciProductsView table.table,#content table.table');
    tables.forEach(table=>{
      const costIndex=mainCostIndex(table);
      table.querySelectorAll('tbody tr').forEach(row=>enhanceMainRow(row,costIndex));
    });
  }

  // ===== Promoção já montada: mantém edição bidirecional =====
  function enhancePromoRow(row){
    const price=row.querySelector('.promo-price-input');
    if(!price)return;
    const priceCell=price.closest('td');
    const cells=Array.from(row.cells||[]);
    const priceIndex=cells.indexOf(priceCell);
    if(priceIndex<0||priceIndex+1>=cells.length)return;
    const costCell=priceIndex>0?cells[priceIndex-1]:null;
    const markupCell=cells[priceIndex+1];
    const code=price.dataset.code||'';

    let markup=markupCell.querySelector('.promo-markup-input');
    if(!markup){
      const initial=numberPt(markupCell.textContent||'0');
      markup=document.createElement('input');
      markup.type='text';
      markup.inputMode='decimal';
      markup.className='promo-markup-input';
      markup.dataset.code=code;
      markup.value=fmt2(initial);
      markup.setAttribute('aria-label','Markup percentual');
      markupCell.textContent='';
      markupCell.appendChild(markup);
    }

    if(markup.dataset.syncBound!=='1'){
      markup.dataset.syncBound='1';
      markup.addEventListener('input',function(){
        const pct=numberPt(markup.value);
        const cost=numberPt(costCell?.textContent||'0');
        if(cost<=0||!Number.isFinite(pct))return;
        price.value=fmt2(Math.max(0,cost*(1+(pct/100))));
      });
      markup.addEventListener('change',function(){
        const pct=numberPt(markup.value);
        const cost=numberPt(costCell?.textContent||'0');
        if(cost<=0||!Number.isFinite(pct))return;
        price.value=fmt2(Math.max(0,cost*(1+(pct/100))));
        price.dispatchEvent(new Event('change',{bubbles:true}));
      });
    }

    if(price.dataset.markupSyncBound!=='1'){
      price.dataset.markupSyncBound='1';
      price.addEventListener('input',function(){
        const cost=numberPt(costCell?.textContent||'0');
        const value=numberPt(price.value);
        if(cost<=0||value<=0)return;
        const target=row.querySelector('.promo-markup-input');
        if(target)target.value=fmt2(((value/cost)-1)*100);
      });
    }
  }

  function enhance(){
    enhanceMainTable();
    document.querySelectorAll('#promoItems .promo-items-table tbody tr').forEach(enhancePromoRow);
  }

  function start(){
    enhance();
    const root=document.getElementById('ciProductsView')||document.getElementById('content')||document.body;
    if(root&&typeof MutationObserver!=='undefined'){
      new MutationObserver(function(){requestAnimationFrame(enhance)}).observe(root,{childList:true,subtree:true});
    }
    const promoRoot=document.getElementById('promoItems');
    if(promoRoot&&promoRoot!==root&&typeof MutationObserver!=='undefined'){
      new MutationObserver(function(){requestAnimationFrame(enhance)}).observe(promoRoot,{childList:true,subtree:true});
    }
    document.addEventListener('click',function(event){
      if(event.target.closest('[data-main="promotion"],#promoOpen,#promoSelect'))setTimeout(enhance,30);
    },true);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
  setTimeout(enhance,250);
  setTimeout(enhance,800);
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + runtime + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v22.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
