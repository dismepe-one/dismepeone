/* DISMEPE ONE 2.0 — PROD4.2
   Central de Atualizações: transporte dedicado pelo FastAPI.
   Mantém as regras existentes e usa a sessão HttpOnly do DISMEPE ONE 2.0. */
(function(){
  if(window.__dismepeUpdateCenterProd4Installed)return;
  window.__dismepeUpdateCenterProd4Installed=true;

  const originalPostApi=window.postApi;

  if(typeof originalPostApi!=='function'){
    console.warn('[PROD4.2 UPDATE CENTER] postApi não disponível.');
    return;
  }

  function persistTimes(result){
    if(!result || typeof result!=='object')return;

    const mensal=String(
      result.horarioMensal ||
      result.horarioMensalISO ||
      ''
    ).trim();

    const extras=String(
      result.horarioExtras ||
      result.horarioExtrasISO ||
      ''
    ).trim();

    if(!mensal && !extras)return;

    const current=
      window.__v2BootstrapHorarios &&
      typeof window.__v2BootstrapHorarios==='object'
        ? window.__v2BootstrapHorarios
        : {};

    window.__v2BootstrapHorarios={
      mensal: mensal || String(current.mensal||''),
      extras: extras || String(current.extras||'')
    };

    try{
      localStorage.setItem(
        'DISMEPE_V2_HOME_TIMES',
        JSON.stringify(window.__v2BootstrapHorarios)
      );
    }catch(e){}

    try{
      window.setUpdatedLabel?.(
        '',
        '',
        window.__v2BootstrapHorarios.mensal,
        window.__v2BootstrapHorarios.extras
      );
    }catch(e){}
  }

  async function updateCenterApi(body){
    const response=await fetch('/admin/update-center',{
      method:'POST',
      headers:{
        'Content-Type':'application/json;charset=utf-8',
        'Accept':'application/json'
      },
      credentials:'same-origin',
      cache:'no-store',
      body:JSON.stringify(Object.assign({},body||{}))
    });

    const text=await response.text();
    let result={};

    try{
      result=text ? JSON.parse(text) : {};
    }catch(e){
      throw new Error(
        'Resposta inválida do servidor da Central de Atualizações.'
      );
    }

    if(!response.ok){
      throw new Error(
        result?.detail ||
        result?.erro ||
        result?.error ||
        ('Falha no Centro de Atualizações (HTTP '+response.status+').')
      );
    }

    return result;
  }

  window.postApi=async function(body){
    const action=String(
      body?.acao ||
      body?.action ||
      ''
    ).trim().toUpperCase();

    if(
      action!=='OPCACHE_STATUS' &&
      action!=='OPCACHE_ATUALIZAR'
    ){
      return originalPostApi.apply(this,arguments);
    }

    const result=await updateCenterApi(body);

    if(action==='OPCACHE_ATUALIZAR'){
      persistTimes(result);
    }

    return result;
  };

  console.log(
    '[PROD4.2 UPDATE CENTER] Transporte FastAPI direto ativo.'
  );
})();
