/* DISMEPE ONE 2.0 — PROD4
   Central de Atualizações: transporte dedicado pelo FastAPI.
   Não altera regras de atualização; evita o gateway 404 em OPCACHE_ATUALIZAR
   e preserva na Home o horário confirmado pela própria Central. */
(function(){
  if(window.__dismepeUpdateCenterProd4Installed)return;
  window.__dismepeUpdateCenterProd4Installed=true;

  const originalPostApi=window.postApi;
  if(typeof originalPostApi!=='function'){
    console.warn('[PROD4 UPDATE CENTER] postApi não disponível.');
    return;
  }

  function persistTimes(result){
    if(!result || typeof result!=='object')return;
    const mensal=String(result.horarioMensal||result.horarioMensalISO||'').trim();
    const extras=String(result.horarioExtras||result.horarioExtrasISO||'').trim();
    if(!mensal && !extras)return;

    const current=(window.__v2BootstrapHorarios && typeof window.__v2BootstrapHorarios==='object')
      ? window.__v2BootstrapHorarios : {};
    window.__v2BootstrapHorarios={
      mensal:mensal || String(current.mensal||''),
      extras:extras || String(current.extras||'')
    };

    try{
      localStorage.setItem('DISMEPE_V2_HOME_TIMES',JSON.stringify(window.__v2BootstrapHorarios));
    }catch(e){}
    try{
      window.setUpdatedLabel?.('', '',window.__v2BootstrapHorarios.mensal,window.__v2BootstrapHorarios.extras);
    }catch(e){}
  }

  window.postApi=async function(body){
    const action=String(body?.acao||body?.action||'').trim().toUpperCase();
    if(action!=='OPCACHE_STATUS' && action!=='OPCACHE_ATUALIZAR'){
      return originalPostApi.apply(this,arguments);
    }
    if(typeof window.v2Api!=='function'){
      throw new Error('Canal 2.0 indisponível para o Centro de Atualizações.');
    }
    const result=await window.v2Api('/admin/update-center',{
      method:'POST',
      body:JSON.stringify(Object.assign({},body||{}))
    });
    if(action==='OPCACHE_ATUALIZAR')persistTimes(result);
    return result;
  };

  console.log('[PROD4 UPDATE CENTER] Transporte dedicado ativo.');
})();
