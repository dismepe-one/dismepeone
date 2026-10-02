from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V16"


def install_commercial_intelligence_ui_v16() -> None:
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
/* Organização da área operacional da lista */
.hidden{display:none!important}
#supplier{display:none!important}
.ci-list-tools{background:#fff;border:1px solid var(--bd);border-radius:16px;padding:12px;display:grid;gap:10px}
.ci-list-tools-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.ci-list-tools-head b{font-size:11px;color:var(--tx)}
.ci-list-tools-head span{font-size:8px;color:var(--mut)}
.ci-list-tools .promo-toolbar{border:0;border-bottom:1px solid #e8efed;border-radius:0;padding:0 0 10px;background:transparent}
.ci-list-tools .filters{width:100%;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ci-list-tools .adv-filters{margin-top:0;padding-top:8px;border-top:1px solid #edf2f0}
.ci-list-tools #supplierMulti{min-width:210px}
.ci-list-tools .multi-btn{width:100%}
#complementToolbar{padding:8px 10px}
#complementToolbar .complement-main small{max-width:760px}
.promo-back-btn{display:inline-flex;align-items:center;gap:6px}
body.ci-promotion-mode #execDashboard,
body.ci-promotion-mode .kpis,
body.ci-promotion-mode #complementToolbar,
body.ci-promotion-mode .panel{display:none!important}
body.ci-promotion-mode .ci-list-tools .filters,
body.ci-promotion-mode .ci-list-tools .adv-filters{display:none!important}
body.ci-promotion-mode .ci-list-tools{padding-bottom:10px}
body.ci-promotion-mode #promoPanel{margin:0;padding:0;max-width:none}
@media(max-width:760px){
  .ci-list-tools{padding:10px}
  .ci-list-tools .filters>*{width:100%!important;min-width:0!important}
  .ci-list-tools #supplierMulti{width:100%;min-width:0}
  .promo-main,.promo-main>*{width:100%}
  .promo-main select,.promo-main .promo-btn{width:100%;min-width:0}
  #complementToolbar{padding:8px}
}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V16
(function(){
  function $(id){return document.getElementById(id)}

  function ensureListTools(){
    if($('ciListTools'))return $('ciListTools');
    const panel=document.querySelector('main > .panel');
    if(!panel)return null;
    const wrap=document.createElement('section');
    wrap.id='ciListTools';
    wrap.className='ci-list-tools';
    wrap.innerHTML='<div class="ci-list-tools-head"><div><b>Produtos e filtros</b><br><span>Filtros, fornecedor e promoções ficam aqui, junto da lista.</span></div></div>';
    panel.parentNode.insertBefore(wrap,panel);
    return wrap;
  }

  function moveControls(){
    const wrap=ensureListTools();
    if(!wrap)return;
    const promo=$('promoToolbar');
    const filters=document.querySelector('.hero .filters')||document.querySelector('.filters');
    const adv=$('advFilters');
    if(promo&&promo.parentNode!==wrap)wrap.appendChild(promo);
    if(filters&&filters.parentNode!==wrap)wrap.appendChild(filters);
    if(adv&&adv.parentNode!==wrap)wrap.appendChild(adv);

    const nativeSupplier=$('supplier');
    if(nativeSupplier){
      nativeSupplier.style.display='none';
      nativeSupplier.setAttribute('aria-hidden','true');
      nativeSupplier.tabIndex=-1;
    }
  }

  function moveComplement(){
    const comp=$('complementToolbar');
    const tools=$('ciListTools');
    const panel=document.querySelector('main > .panel');
    if(comp&&tools&&panel){
      // Base complementar separada, logo acima da área operacional da lista.
      tools.parentNode.insertBefore(comp,tools);
    }
  }

  function ensurePromoBack(){
    const actions=document.querySelector('#promoPanel .promo-actions');
    if(!actions||$('promoBack'))return;
    const btn=document.createElement('button');
    btn.type='button';
    btn.id='promoBack';
    btn.className='promo-btn promo-back-btn';
    btn.innerHTML='<i class="fa-solid fa-arrow-left"></i> Voltar aos produtos';
    actions.insertBefore(btn,actions.firstChild);

    const open=$('promoOpen');
    if(open){
      open.addEventListener('click',()=>{
        const view=$('viewSelect');
        const current=view?.value||'overview';
        btn.dataset.returnView=(current&&current!=='promotion')?current:'overview';
      },true);
    }

    btn.addEventListener('click',()=>{
      const view=$('viewSelect');
      const target=btn.dataset.returnView||'overview';
      document.body.classList.remove('ci-promotion-mode');
      if(view){
        view.value=target;
        view.dispatchEvent(new Event('change',{bubbles:true}));
      }
      setTimeout(()=>document.querySelector('main > .panel')?.scrollIntoView({behavior:'smooth',block:'start'}),80);
    });
  }

  function syncMode(){
    const view=$('viewSelect');
    const promotion=view?.value==='promotion';
    document.body.classList.toggle('ci-promotion-mode',promotion);
    if(promotion){
      setTimeout(()=>$('promoPanel')?.scrollIntoView({behavior:'smooth',block:'start'}),60);
    }
  }

  function bindMode(){
    const view=$('viewSelect');
    if(view&&!view.dataset.ciModeBound){
      view.dataset.ciModeBound='1';
      view.addEventListener('change',()=>setTimeout(syncMode,0));
    }
    const open=$('promoOpen');
    if(open&&!open.dataset.ciModeBound){
      open.dataset.ciModeBound='1';
      open.addEventListener('click',()=>setTimeout(syncMode,0));
    }
  }

  function organize(){
    moveControls();
    moveComplement();
    ensurePromoBack();
    bindMode();
    syncMode();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',organize,{once:true});else organize();
  setTimeout(organize,250);
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v16.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
