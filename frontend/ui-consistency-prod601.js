(function(){
  'use strict';

  if(window.__dismepeUiConsistency601)return;
  window.__dismepeUiConsistency601=true;

  const LABELS={loading:'Carregando',success:'Atualizado',warning:'Atenção',error:'Erro'};

  function ensureStyle(){
    if(document.getElementById('dismepe-ui-consistency-601-style'))return;
    const style=document.createElement('style');
    style.id='dismepe-ui-consistency-601-style';
    style.textContent=`
      .d1-state-host{display:inline-flex!important;align-items:center;gap:6px;flex-wrap:wrap}
      .d1-state-host::before{content:attr(data-d1-state-label);display:inline-flex;align-items:center;min-height:19px;padding:2px 7px;border-radius:999px;font-size:9px;line-height:1.1;font-weight:900;letter-spacing:.035em;text-transform:uppercase;border:1px solid transparent;white-space:nowrap}
      .d1-state-host[data-d1-state="loading"]::before{color:#075985;background:#e0f2fe;border-color:#bae6fd}
      .d1-state-host[data-d1-state="success"]::before{color:#065f46;background:#d1fae5;border-color:#a7f3d0}
      .d1-state-host[data-d1-state="warning"]::before{color:#92400e;background:#fef3c7;border-color:#fde68a}
      .d1-state-host[data-d1-state="error"]::before{color:#991b1b;background:#fee2e2;border-color:#fecaca}
      .d1-metric-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
      .d1-metric-action{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;border:1px solid #a7d7c9;border-radius:8px;background:#fff;color:#075548!important;font-size:10px;font-weight:900;text-decoration:none!important;cursor:pointer;transition:.15s ease}
      .d1-metric-action:hover,.d1-metric-action:focus-visible{background:#eaf7f2;border-color:#62b59d;outline:2px solid rgba(7,85,72,.16);outline-offset:1px}
      .v171-component>.d1-inline-state{display:inline-flex;margin:0 6px 4px 0;padding:2px 6px;border-radius:999px;font-size:8px;font-weight:900;letter-spacing:.035em;text-transform:uppercase;vertical-align:middle}
      .v171-component>.d1-inline-state.success{background:#d1fae5;color:#065f46}
      .v171-component>.d1-inline-state.warning{background:#fef3c7;color:#92400e}
      @media(max-width:640px){.d1-state-host::before{font-size:8px;padding:2px 6px}.d1-metric-action{font-size:9px}}
    `;
    document.head.appendChild(style);
  }

  function inferState(text){
    const value=String(text||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();
    if(/ERRO|FALHA|INDISPONIVEL|NAO FOI POSSIVEL/.test(value))return 'error';
    if(/AGUARDANDO|ATENCAO|PENDENTE|PRESERVAD|VERIFICANDO/.test(value))return 'warning';
    if(/CARREGANDO|ATUALIZANDO|PREPARANDO|PROCESSANDO/.test(value))return 'loading';
    return 'success';
  }

  function setState(target,state){
    const el=typeof target==='string'?document.getElementById(target):target;
    if(!el)return;
    const safe=LABELS[state]?state:'success';
    el.classList.add('d1-state-host');
    el.dataset.d1State=safe;
    el.dataset.d1StateLabel=LABELS[safe];
  }

  function formatTimestamp(value){
    if(!value)return '';
    const date=new Date(value);
    if(Number.isNaN(date.getTime()))return String(value);
    return date.toLocaleString('pt-BR',{
      timeZone:'America/Recife',
      day:'2-digit',month:'2-digit',year:'numeric',
      hour:'2-digit',minute:'2-digit'
    }).replace(',', ' às');
  }

  function decorateKnownStatuses(){
    ['sumPremStatus','clientesPEDUpdated','hist39HistoryStatus','hist40ExtraStatus'].forEach(id=>{
      const el=document.getElementById(id);
      if(!el)return;
      const text=String(el.textContent||'').trim();
      if(!text)return;
      if(id==='clientesPEDUpdated' && /^Última atualização:\s*(?!—)/i.test(text)){
        el.textContent=text.replace(/^Última atualização:\s*/i,'Atualizado em ');
      }
      setState(el,inferState(el.textContent));
    });

    const homeIds=['homeLastUpdated','homeLastUpdatedMonthly','homeLastUpdatedExtras','lastUpdatedValue'];
    homeIds.forEach(id=>{
      const el=document.getElementById(id);
      if(!el)return;
      const text=String(el.textContent||'').trim();
      if(text && text!=='—' && !/carreg/i.test(text))setState(el,'success');
    });
  }

  function wrapMonthlyMetrics(){
    if(window.__d1V171Wrapped || typeof window.v171Details!=='function')return;
    window.__d1V171Wrapped=true;
    const original=window.v171Details;

    window.v171Details=function(item){
      const html=original.apply(this,arguments);
      if(!html)return html;
      try{
        const calc=item&&item.metricasParcial;
        if(!calc||!Array.isArray(calc.componentes))return html;
        const box=document.createElement('div');
        box.innerHTML=html;
        const nodes=Array.from(box.querySelectorAll('.v171-component'));

        calc.componentes.forEach((component,index)=>{
          const node=nodes[index];
          if(!node||!component)return;

          const badge=document.createElement('span');
          const pending=component.pendente===true;
          badge.className='d1-inline-state '+(pending?'warning':'success');
          badge.textContent=pending?'Atenção':'Atualizado';
          node.insertBefore(badge,node.firstChild);

          if(String(component.metrica||'').toUpperCase()!=='POSITIVACAO_GERAL' || pending)return;
          const actual=Math.max(0,Number(component.realizado)||0);
          const laboratory=String(item?.lab||item?.laboratorio||'').trim();
          const laboratoryParam=laboratory?'&laboratorio='+encodeURIComponent(laboratory):'';
          const contextLabel=laboratory?' de '+laboratory:'';
          const actions=document.createElement('div');
          actions.className='d1-metric-actions';
          actions.innerHTML=
            '<a class="d1-metric-action" href="/positivacoes?status=positivados'+laboratoryParam+'" title="Abrir clientes positivados'+contextLabel+'">'+
              actual.toLocaleString('pt-BR')+' positivados ↗</a>'+
            '<a class="d1-metric-action" href="/positivacoes?status=nao-positivados'+laboratoryParam+'" title="Abrir clientes ainda não positivados'+contextLabel+'">Ver não positivados ↗</a>';
          node.appendChild(actions);
        });
        return box.innerHTML;
      }catch(error){
        console.warn('[UI 601] Não foi possível enriquecer a métrica mensal.',error);
        return html;
      }
    };
  }

  function refresh(){
    ensureStyle();
    wrapMonthlyMetrics();
    decorateKnownStatuses();
  }

  let scheduled=false;
  function schedule(){
    if(scheduled)return;
    scheduled=true;
    requestAnimationFrame(()=>{scheduled=false;refresh();});
  }

  window.DismepeUIState={
    set:setState,
    infer:inferState,
    formatTimestamp:formatTimestamp,
    refresh:schedule
  };

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh,{once:true});
  else refresh();

  new MutationObserver(schedule).observe(document.documentElement,{
    childList:true,subtree:true,characterData:true
  });
})();