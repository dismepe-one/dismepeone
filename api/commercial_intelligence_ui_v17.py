from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V17"


def install_commercial_intelligence_ui_v17() -> None:
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
.ci-main-tabs{display:flex;gap:6px;background:#fff;border:1px solid var(--bd);border-radius:14px;padding:6px;position:sticky;top:6px;z-index:45;box-shadow:0 6px 18px rgba(0,63,54,.06)}
.ci-main-tab{height:38px;border:0;border-radius:9px;background:transparent;color:#60746f;padding:0 14px;font-size:9px;font-weight:950;cursor:pointer;display:inline-flex;align-items:center;gap:7px;white-space:nowrap}
.ci-main-tab.active{background:#087864;color:#fff}
.ci-main-tab i{font-size:10px}
.ci-view-section{display:none}
body.ci-main-products #ciProductsView,
body.ci-main-stats #ciStatsView,
body.ci-main-promotion #ciPromotionView{display:block}
#ciProductsView>*+*{margin-top:10px}
#ciStatsView>*+*{margin-top:10px}
#ciPromotionView{margin-top:10px}
#ciPromotionView #promoPanel{display:block!important;margin:0;padding:0;max-width:none}
body.ci-main-products #execDashboard,
body.ci-main-products .kpis{display:none!important}
body.ci-main-stats #complementToolbar,
body.ci-main-stats #ciListTools,
body.ci-main-stats main>.panel{display:none!important}
body.ci-main-promotion #complementToolbar,
body.ci-main-promotion #ciListTools,
body.ci-main-promotion main>.panel,
body.ci-main-promotion #execDashboard,
body.ci-main-promotion .kpis{display:none!important}
#promoOpen{display:none!important}
#viewSelect option[value="promotion"]{display:none}
@media(max-width:760px){
  .ci-main-tabs{position:static;display:grid;grid-template-columns:1fr 1fr 1fr;padding:5px}
  .ci-main-tab{justify-content:center;padding:0 6px;font-size:8px}
  .ci-main-tab span{display:none}
  .ci-main-tab::after{content:attr(data-short)}
}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V17
(function(){
  const $=id=>document.getElementById(id);
  let currentMain='products';
  let lastProductView='overview';

  function ensureShell(){
    if($('ciMainTabs'))return;
    const main=document.querySelector('main');
    if(!main)return;
    const first=$('complementToolbar')||$('ciListTools')||main.querySelector('.panel')||main.firstElementChild;

    const tabs=document.createElement('nav');
    tabs.id='ciMainTabs';
    tabs.className='ci-main-tabs';
    tabs.innerHTML=`
      <button type="button" class="ci-main-tab active" data-main="products" data-short="Produtos"><i class="fa-solid fa-boxes-stacked"></i><span>Produtos</span></button>
      <button type="button" class="ci-main-tab" data-main="stats" data-short="Estatísticas"><i class="fa-solid fa-chart-column"></i><span>Estatísticas</span></button>
      <button type="button" class="ci-main-tab" data-main="promotion" data-short="Montar Promoção"><i class="fa-solid fa-tags"></i><span>Montar Promoção</span></button>`;
    main.insertBefore(tabs,first);

    const products=document.createElement('section');
    products.id='ciProductsView';
    products.className='ci-view-section';
    main.insertBefore(products,tabs.nextSibling);

    const stats=document.createElement('section');
    stats.id='ciStatsView';
    stats.className='ci-view-section';
    main.insertBefore(stats,products.nextSibling);

    const promotion=document.createElement('section');
    promotion.id='ciPromotionView';
    promotion.className='ci-view-section';
    main.insertBefore(promotion,stats.nextSibling);
  }

  function moveSections(){
    const products=$('ciProductsView'),stats=$('ciStatsView'),promotion=$('ciPromotionView');
    if(!products||!stats||!promotion)return;
    const comp=$('complementToolbar'),tools=$('ciListTools'),panel=document.querySelector('main > .panel');
    if(comp&&comp.parentNode!==products)products.appendChild(comp);
    if(tools&&tools.parentNode!==products)products.appendChild(tools);
    if(panel&&panel.parentNode!==products)products.appendChild(panel);

    const kpis=document.querySelector('.kpis');
    const dashboard=$('execDashboard');
    if(kpis&&kpis.parentNode!==stats)stats.appendChild(kpis);
    if(dashboard&&dashboard.parentNode!==stats)stats.appendChild(dashboard);

    const promo=$('promoPanel');
    if(promo&&promo.parentNode!==promotion)promotion.appendChild(promo);
  }

  function updateTabs(){
    document.querySelectorAll('.ci-main-tab').forEach(btn=>btn.classList.toggle('active',btn.dataset.main===currentMain));
    document.body.classList.remove('ci-main-products','ci-main-stats','ci-main-promotion','ci-promotion-mode');
    document.body.classList.add('ci-main-'+currentMain);
  }

  function leavePromotionIfNeeded(done){
    const view=$('viewSelect');
    if(view?.value==='promotion'){
      view.value=lastProductView||'overview';
      view.dispatchEvent(new Event('change',{bubbles:true}));
      setTimeout(done,60);
    }else done();
  }

  function openMain(name){
    const view=$('viewSelect');
    if(name==='promotion'){
      if(view&&view.value&&view.value!=='promotion')lastProductView=view.value;
      currentMain='promotion';
      if(view){view.value='promotion';view.dispatchEvent(new Event('change',{bubbles:true}));}
      updateTabs();
      setTimeout(()=>$('ciPromotionView')?.scrollIntoView({behavior:'smooth',block:'start'}),80);
      return;
    }
    leavePromotionIfNeeded(()=>{
      currentMain=name;
      updateTabs();
      setTimeout(()=>$(name==='stats'?'ciStatsView':'ciProductsView')?.scrollIntoView({behavior:'smooth',block:'start'}),60);
    });
  }

  function bindTabs(){
    document.querySelectorAll('.ci-main-tab').forEach(btn=>{
      if(btn.dataset.bound)return;
      btn.dataset.bound='1';
      btn.addEventListener('click',()=>openMain(btn.dataset.main));
    });
    const back=$('promoBack');
    if(back&&!back.dataset.mainTabsBound){
      back.dataset.mainTabsBound='1';
      back.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();openMain('products')},true);
    }
    const view=$('viewSelect');
    if(view&&!view.dataset.mainTabsTrack){
      view.dataset.mainTabsTrack='1';
      view.addEventListener('change',()=>{
        if(view.value&&view.value!=='promotion')lastProductView=view.value;
      });
    }
  }

  function hidePromotionOption(){
    const opt=document.querySelector('#viewSelect option[value="promotion"]');
    if(opt){opt.hidden=true;opt.setAttribute('aria-hidden','true')}
  }

  function organize(){
    ensureShell();
    moveSections();
    hidePromotionOption();
    bindTabs();
    updateTabs();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',organize,{once:true});else organize();
  setTimeout(organize,300);
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v17.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
