from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V18"


def install_commercial_intelligence_ui_v18() -> None:
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

    css_anchor = "</style>"
    css_patch = r'''
/* Mobile: produtos em cards e promoção exclusiva do desktop */
@media(max-width:760px){
  .ci-main-tabs{grid-template-columns:1fr 1fr!important}
  .ci-main-tab[data-main="promotion"]{display:none!important}
  #promoToolbar,#promoPanel,.price-entry,.promo-price-input{display:none!important}
  body.ci-main-promotion #ciPromotionView{display:none!important}
  body.ci-main-promotion #ciProductsView{display:block!important}

  #ciProductsView .panel{overflow:visible!important;border:0!important;background:transparent!important}
  #ciProductsView .panel-head{background:#fff;border:1px solid var(--bd);border-radius:14px;margin-bottom:8px;padding:11px 12px}
  #ciProductsView .table-wrap{max-height:none!important;overflow:visible!important}
  #ciProductsView .table{display:block!important;width:100%!important;min-width:0!important;border-collapse:separate!important}
  #ciProductsView .table thead{display:none!important}
  #ciProductsView .table tbody{display:grid!important;gap:9px!important;width:100%!important}
  #ciProductsView .table tr{display:block!important;width:100%!important;background:#fff!important;border:1px solid var(--bd)!important;border-radius:14px!important;padding:9px 10px!important;box-shadow:0 2px 8px rgba(0,63,54,.035)!important}
  #ciProductsView .table td{display:flex!important;align-items:flex-start!important;justify-content:space-between!important;gap:12px!important;width:100%!important;padding:5px 0!important;border:0!important;text-align:right!important;font-size:10px!important;white-space:normal!important}
  #ciProductsView .table td::before{content:attr(data-label);font-size:8px!important;line-height:1.35!important;font-weight:900!important;text-transform:uppercase!important;letter-spacing:.04em!important;color:var(--mut)!important;text-align:left!important;flex:0 0 41%!important}
  #ciProductsView .table td.ci-mobile-product{display:block!important;text-align:left!important;padding:4px 0 8px!important;border-bottom:1px solid #edf2f0!important}
  #ciProductsView .table td.ci-mobile-product::before{display:block!important;margin-bottom:3px!important;content:attr(data-label)!important;flex:none!important}
  #ciProductsView .table td.ci-mobile-code{font-weight:950!important;color:var(--g)!important}
  #ciProductsView .table td.ci-mobile-hide{display:none!important}
  #ciProductsView .spark{justify-content:flex-end}
  #ciProductsView .pager{border:0!important;background:transparent!important;padding:10px 0!important}
  #ciProductsView .formula{border:1px solid var(--bd)!important;border-radius:10px!important;margin-top:8px!important}

  /* Filtros realmente mobile */
  #ciListTools .promo-toolbar{display:none!important}
  #ciListTools .filters,#ciListTools .adv-filters{display:grid!important;grid-template-columns:1fr!important;gap:7px!important}
  #ciListTools .filters>*,#ciListTools .adv-filters>*{width:100%!important;min-width:0!important;max-width:none!important}
  #supplierMulti{width:100%!important;min-width:0!important}
  .multi-panel{left:0!important;right:0!important;width:auto!important;max-width:none!important}
  #complementToolbar .complement-actions{width:100%!important}
  #complementToolbar .complement-actions .promo-btn{width:100%!important}
}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V18
(function(){
  const MOBILE=()=>window.matchMedia('(max-width:760px)').matches;

  function labelMobileRows(){
    if(!MOBILE())return;
    document.querySelectorAll('#ciProductsView table.table').forEach(table=>{
      const labels=[...table.querySelectorAll('thead th')].map(th=>(th.textContent||'').trim());
      table.querySelectorAll('tbody tr').forEach(row=>{
        [...row.children].forEach((td,i)=>{
          const label=labels[i]||'';
          td.dataset.label=label;
          td.classList.toggle('ci-mobile-code',i===0);
          td.classList.toggle('ci-mobile-product',i===1);
          const normalized=label.toLowerCase();
          const hidePromo=normalized.includes('preço promoção')||normalized.includes('markup promoção');
          const hideHistory=/^(jul|ago|set|out|nov|dez|jan|fev|mar|abr|mai|jun)\b/i.test(normalized)||normalized==='histórico';
          td.classList.toggle('ci-mobile-hide',hidePromo||hideHistory);
        });
      });
    });
  }

  function enforceDesktopOnlyPromotion(){
    if(!MOBILE())return;
    const promoTab=document.querySelector('.ci-main-tab[data-main="promotion"]');
    if(promoTab)promoTab.style.display='none';
    const view=document.getElementById('viewSelect');
    if(view?.value==='promotion'){
      view.value='overview';
      view.dispatchEvent(new Event('change',{bubbles:true}));
    }
    document.body.classList.remove('ci-main-promotion','ci-promotion-mode');
    document.body.classList.add('ci-main-products');
    document.querySelectorAll('.ci-main-tab').forEach(b=>b.classList.toggle('active',b.dataset.main==='products'));
  }

  function refresh(){enforceDesktopOnlyPromotion();labelMobileRows()}

  function observe(){
    const target=document.getElementById('content');
    if(!target)return;
    new MutationObserver(()=>setTimeout(labelMobileRows,0)).observe(target,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{refresh();observe()},{once:true});else{refresh();observe()}
  window.addEventListener('resize',()=>setTimeout(refresh,80));
  setTimeout(refresh,350);
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v18.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
