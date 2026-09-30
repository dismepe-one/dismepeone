/* DISMEPE ONE — card de falta para objetivo quando um laboratório é filtrado.
   Reutiliza os KPIs já calculados pela parcial mensal; não altera cálculos de campanha. */
(function(){
  'use strict';
  if(window.__DISMEPE_MONTHLY_FILTER_GAP_CARD_602__)return;
  window.__DISMEPE_MONTHLY_FILTER_GAP_CARD_602__=true;

  function parseBRL(value){
    let text=String(value||'').replace(/R\$/gi,'').replace(/\s/g,'').trim();
    if(!text)return 0;
    if(text.includes(',')&&text.includes('.'))text=text.replace(/\./g,'').replace(',','.');
    else if(text.includes(','))text=text.replace(',','.');
    const number=Number(text.replace(/[^0-9.-]/g,''));
    return Number.isFinite(number)?number:0;
  }

  function money(value){
    return Number(value||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  }

  function ensureStyle(){
    if(document.getElementById('monthly-filter-gap-card-602-style'))return;
    const style=document.createElement('style');
    style.id='monthly-filter-gap-card-602-style';
    style.textContent=`
      #kpiMetricsSection.d602-five-kpis{grid-template-columns:repeat(5,minmax(0,1fr))}
      #d602SupplierGapCard{border-color:rgba(244,63,94,.24)}
      #d602SupplierGapCard.d602-reached{border-color:rgba(16,185,129,.24)}
      #d602SupplierGapCard .d602-icon{background:rgba(244,63,94,.10);color:#fb7185}
      #d602SupplierGapCard.d602-reached .d602-icon{background:rgba(16,185,129,.10);color:#34d399}
      #d602SupplierGapValue{color:#fda4af}
      #d602SupplierGapCard.d602-reached #d602SupplierGapValue{color:#6ee7b7}
      @media(max-width:1200px){#kpiMetricsSection.d602-five-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
      @media(max-width:640px){#kpiMetricsSection.d602-five-kpis{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function ensureCard(){
    const host=document.getElementById('kpiMetricsSection');
    if(!host)return null;
    let card=document.getElementById('d602SupplierGapCard');
    if(card)return card;
    card=document.createElement('div');
    card.id='d602SupplierGapCard';
    card.className='card-glass p-5 rounded-2xl shadow-lg relative overflow-hidden hidden';
    card.innerHTML=`
      <div class="d602-icon absolute right-4 top-4 p-3 rounded-xl"><i class="fa-solid fa-flag-checkered text-xl"></i></div>
      <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Falta para o objetivo</p>
      <h3 id="d602SupplierGapValue" class="text-2xl font-bold mt-2">—</h3>
      <span id="d602SupplierGapSub" class="text-xs text-slate-400 mt-1 block">Selecione um laboratório</span>`;
    host.appendChild(card);
    return card;
  }

  function selectedLabLabel(){
    const select=document.getElementById('filterLab');
    if(!select)return '';
    const option=select.options?.[select.selectedIndex];
    return String(option?.textContent||select.value||'').trim();
  }

  function renderGapCard(){
    ensureStyle();
    const host=document.getElementById('kpiMetricsSection');
    const card=ensureCard();
    const select=document.getElementById('filterLab');
    if(!host||!card||!select)return;

    const selected=String(select.value||'ALL').trim();
    if(!selected||selected==='ALL'){
      card.classList.add('hidden');
      card.classList.remove('d602-reached');
      host.classList.remove('d602-five-kpis');
      return;
    }

    const objective=parseBRL(document.getElementById('kpiObjetivo')?.textContent);
    const sale=parseBRL(document.getElementById('kpiVenda')?.textContent);
    const gap=Math.max(objective-sale,0);
    const reached=objective>0 && sale>=objective;
    const value=document.getElementById('d602SupplierGapValue');
    const sub=document.getElementById('d602SupplierGapSub');

    card.classList.remove('hidden');
    card.classList.toggle('d602-reached',reached);
    host.classList.add('d602-five-kpis');

    if(objective<=0){
      if(value)value.textContent='—';
      if(sub)sub.textContent=selectedLabLabel()+' · fornecedor sem objetivo financeiro';
      return;
    }

    if(value)value.textContent=money(gap);
    if(sub)sub.textContent=reached
      ? selectedLabLabel()+' · objetivo atingido'
      : selectedLabLabel()+' · '+money(sale)+' de '+money(objective);
  }

  function wrapDashboard(){
    const original=window.updateDashboard;
    if(typeof original!=='function' || original.__d602GapWrapped)return false;
    const wrapped=function(){
      const result=original.apply(this,arguments);
      requestAnimationFrame(renderGapCard);
      return result;
    };
    wrapped.__d602GapWrapped=true;
    wrapped.__d602Original=original;
    window.updateDashboard=wrapped;
    return true;
  }

  function bind(){
    wrapDashboard();
    document.getElementById('filterLab')?.addEventListener('change',()=>requestAnimationFrame(renderGapCard));
    document.getElementById('filterColab')?.addEventListener('change',()=>requestAnimationFrame(renderGapCard));
    document.getElementById('filterStatus')?.addEventListener('change',()=>requestAnimationFrame(renderGapCard));
    renderGapCard();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});
  else bind();

  [100,500,1500,3500].forEach(delay=>setTimeout(()=>{wrapDashboard();renderGapCard();},delay));
})();
