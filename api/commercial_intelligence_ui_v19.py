from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V19"


def install_commercial_intelligence_ui_v19() -> None:
    from . import commercial_intelligence as ci
    from .commercial_intelligence_quantity_fix import install_commercial_intelligence_quantity_fix
    from .commercial_intelligence_dde_fix import install_commercial_intelligence_dde_fix
    from .commercial_intelligence_promotion_export_details import install_commercial_intelligence_promotion_export_details
    from .commercial_intelligence_ui_v20 import install_commercial_intelligence_ui_v20

    # Correções de dados são instaladas aqui porque a V19 já roda depois do
    # backend complementar/promoções no startup oficial.
    install_commercial_intelligence_quantity_fix()
    install_commercial_intelligence_dde_fix()
    install_commercial_intelligence_promotion_export_details()

    page = getattr(ci, "PAGE_FILE", None)
    if not isinstance(page, Path):
        return
    try:
        text = page.read_text(encoding="utf-8")
    except Exception:
        return
    if _MARKER in text:
        install_commercial_intelligence_ui_v20()
        return

    css_anchor = "</style>"
    css_patch = r'''
/* Mobile: Montar Promoção disponível apenas para consulta/exportação */
@media(max-width:760px){
  .ci-main-tabs{grid-template-columns:1fr 1fr 1fr!important}
  .ci-main-tab[data-main="promotion"]{display:inline-flex!important}
  body.ci-main-promotion #ciPromotionView{display:block!important}
  body.ci-main-promotion #ciProductsView{display:none!important}
  #ciPromotionView #promoPanel{display:block!important}

  /* Tudo que cria, altera ou exclui promoção fica exclusivo do desktop */
  #promoNew,#promoOpen,#promoDelete,.promo-name-row,.promo-row-remove{display:none!important}
  #ciProductsView .price-entry{display:none!important}
  #ciPromotionView .promo-price-input{display:none!important}
  #ciPromotionView .promo-actions{width:100%!important;display:grid!important;grid-template-columns:1fr 1fr!important;gap:7px!important}
  #ciPromotionView #promoBack{grid-column:1/-1!important}
  #ciPromotionView #promoXlsx,#ciPromotionView #promoPdf,#ciPromotionView #promoBack{width:100%!important}
  #ciPromotionView .promo-panel-head{align-items:stretch!important}
  #ciPromotionView .promo-panel-head>div:first-child{width:100%!important}
  #ciPromotionView .promo-items-wrap{overflow:visible!important;border-radius:12px!important}
  #ciPromotionView .promo-items-table{min-width:0!important;width:100%!important}
  #ciPromotionView .promo-items-table th:nth-child(3),
  #ciPromotionView .promo-items-table th:nth-child(5),
  #ciPromotionView .promo-items-table td:nth-child(5){display:none!important}
  #ciPromotionView .promo-items-table th,
  #ciPromotionView .promo-items-table td{font-size:8px!important;padding:7px 5px!important}
  #ciPromotionView .mobile-promo-price{font-weight:950;color:var(--g);white-space:nowrap}
  #ciMobilePromoChooser{display:grid!important;gap:5px;background:#fff;border:1px solid var(--bd);border-radius:12px;padding:10px;margin-bottom:9px}
  #ciMobilePromoChooser label{font-size:8px;font-weight:950;color:#5e746e;text-transform:uppercase;letter-spacing:.06em}
  #ciMobilePromoSelect{height:40px;border:1px solid var(--bd);border-radius:9px;background:#fff;padding:0 10px;font-weight:850;color:var(--tx);width:100%}
  #ciMobilePromoHint{font-size:8px;color:var(--mut);line-height:1.45}
}
@media(min-width:761px){#ciMobilePromoChooser{display:none!important}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V19
(function(){
  const MOBILE=()=>window.matchMedia('(max-width:760px)').matches;
  const $=id=>document.getElementById(id);

  function ensureChooser(){
    if(!MOBILE())return;
    const view=$('ciPromotionView');
    const panel=$('promoPanel');
    if(!view||!panel||$('ciMobilePromoChooser'))return;
    const box=document.createElement('div');
    box.id='ciMobilePromoChooser';
    box.innerHTML='<label for="ciMobilePromoSelect">Promoção</label><select id="ciMobilePromoSelect"></select><div id="ciMobilePromoHint">No celular esta área é somente para consulta e exportação. A criação e edição de promoções ficam disponíveis apenas no computador.</div>';
    view.insertBefore(box,panel);
    $('ciMobilePromoSelect').addEventListener('change',()=>{
      const original=$('promoSelect');
      if(!original)return;
      original.value=$('ciMobilePromoSelect').value;
      original.dispatchEvent(new Event('change',{bubbles:true}));
      setTimeout(syncChooser,40);
    });
  }

  function syncChooser(){
    if(!MOBILE())return;
    ensureChooser();
    const original=$('promoSelect'), mobile=$('ciMobilePromoSelect');
    if(!original||!mobile)return;
    const value=original.value;
    mobile.innerHTML=[...original.options].map(o=>`<option value="${String(o.value).replace(/"/g,'&quot;')}">${o.textContent||''}</option>`).join('');
    mobile.value=value;
  }

  function makeItemsReadonly(){
    if(!MOBILE())return;
    const table=document.querySelector('#ciPromotionView .promo-items-table');
    if(!table)return;
    table.querySelectorAll('tbody tr').forEach(row=>{
      const priceCell=row.children[2];
      const input=priceCell?.querySelector('.promo-price-input');
      if(priceCell&&input&&!priceCell.querySelector('.mobile-promo-price')){
        const span=document.createElement('span');
        span.className='mobile-promo-price';
        const raw=String(input.value||'0').replace(',','.');
        const n=Number(raw)||0;
        span.textContent=n.toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
        priceCell.appendChild(span);
      }
    });
  }

  function enforceExportOnly(){
    if(!MOBILE())return;
    const promoTab=document.querySelector('.ci-main-tab[data-main="promotion"]');
    if(promoTab)promoTab.style.removeProperty('display');
    ensureChooser();
    syncChooser();
    makeItemsReadonly();
  }

  function observe(){
    const root=$('ciPromotionView')||document.body;
    new MutationObserver(()=>setTimeout(()=>{syncChooser();makeItemsReadonly()},0)).observe(root,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{enforceExportOnly();observe()},{once:true});else{enforceExportOnly();observe()}
  window.addEventListener('resize',()=>setTimeout(enforceExportOnly,120));
  setTimeout(enforceExportOnly,500);
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v19.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        return

    install_commercial_intelligence_ui_v20()
