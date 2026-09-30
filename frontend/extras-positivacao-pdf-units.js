/* DISMEPE ONE — Campanha CE-20260930-154538-472167: clientes, não unidades. */
(function(){
  'use strict';
  const TARGET='CE-20260930-154538-472167';
  const METRIC='RANKING_POSITIVACAO_PRODUTOS';

  function isTarget(row){
    const campaign=String(document.getElementById('extraCampaignSelect')?.value||'').trim();
    const metric=String(row?.metrica||row?.metric||'').trim().toUpperCase();
    return campaign===TARGET && metric===METRIC;
  }

  function clientes(value, sufixo){
    const n=Math.max(0,Math.round(Number(value)||0));
    return n+' '+(n===1?'cliente':sufixo||'clientes');
  }

  function install(){
    if(typeof window.extraPartialObjectiveText==='function' && !window.extraPartialObjectiveText.__clientesFix){
      const original=window.extraPartialObjectiveText;
      const fn=function(row){
        if(isTarget(row)) return clientes(row?.objetivo ?? row?.meta ?? 0,'clientes');
        return original.apply(this,arguments);
      };
      fn.__clientesFix=true;
      window.extraPartialObjectiveText=fn;
    }

    if(typeof window.extraPartialRealizedText==='function' && !window.extraPartialRealizedText.__clientesFix){
      const original=window.extraPartialRealizedText;
      const fn=function(row){
        if(isTarget(row)) return clientes(row?.clientesPositivadosValidos ?? row?.realizado ?? 0,'clientes positivados');
        return original.apply(this,arguments);
      };
      fn.__clientesFix=true;
      window.extraPartialRealizedText=fn;
    }

    try{
      if(typeof window.renderExtraRows==='function') window.renderExtraRows();
    }catch(e){}
  }

  let i=0;
  const timer=setInterval(()=>{
    install();
    if(++i>100) clearInterval(timer);
  },100);
})();