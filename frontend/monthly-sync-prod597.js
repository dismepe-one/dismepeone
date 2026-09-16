/* DISMEPE ONE — PROD5.9.7
   Correção exclusiva da Campanha Mensal.
   O worker legado é assíncrono; a tela só assume conclusão quando o
   horarioMensalISO retornado por /data/bootstrap (PostgreSQL) realmente avança.
   Campanhas Extras e demais módulos não são alterados por este patch. */
(function(){
  if(window.__dismepeMonthlySyncProd597Installed)return;
  window.__dismepeMonthlySyncProd597Installed=true;

  const previousPostApi=window.postApi;
  const directFetch=window.fetch.bind(window);
  if(typeof previousPostApi!=='function')return;

  let generation=0;
  const waits=[2500,6000,12000,25000,45000,65000,90000,120000,160000];

  function monthlyRequested(body){
    const action=String(body?.acao||body?.action||'').trim().toUpperCase();
    if(action!=='OPCACHE_ATUALIZAR')return false;
    const actions=Array.isArray(body?.acoes)?body.acoes:[];
    return actions.some(item=>
      item && typeof item==='object' &&
      String(item.modulo||'').trim().toUpperCase()==='MENSAL' &&
      item.atualizar!==false
    );
  }

  function millis(value){
    const s=String(value||'').trim();
    if(!s)return NaN;
    const br=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?/);
    if(br){
      return new Date(
        Number(br[3]),Number(br[2])-1,Number(br[1]),
        Number(br[4]),Number(br[5]),Number(br[6]||0)
      ).getTime();
    }
    const parsed=Date.parse(s);
    return Number.isFinite(parsed)?parsed:NaN;
  }

  function isNewer(next,previous){
    const a=millis(next);
    const b=millis(previous);
    if(Number.isFinite(a) && Number.isFinite(b))return a>b;
    const n=String(next||'').trim();
    const p=String(previous||'').trim();
    return !!n && !!p && n!==p;
  }

  function rememberedMonthly(){
    const live=String(window.__v2BootstrapHorarios?.mensal||'').trim();
    if(live)return live;
    try{
      const saved=JSON.parse(localStorage.getItem('DISMEPE_V2_HOME_TIMES')||'{}');
      return String(saved?.mensal||'').trim();
    }catch(e){return '';}
  }

  async function bootstrap(){
    try{
      const response=await directFetch('/data/bootstrap?_mensal597='+Date.now(),{
        method:'GET',
        credentials:'same-origin',
        cache:'no-store',
        headers:{'Accept':'application/json'}
      });
      if(!response.ok)return null;
      const data=await response.json();
      return data && typeof data==='object'?data:null;
    }catch(e){
      return null;
    }
  }

  function snapshotTime(payload){
    return String(payload?.horarioMensalISO||payload?.horarioMensal||'').trim();
  }

  async function applyMonthlySnapshot(payload){
    if(!payload || typeof payload!=='object')return;

    try{
      if(typeof v102SaveDataCache==='function')v102SaveDataCache(payload);
    }catch(e){}

    if(Array.isArray(payload.regrasPremiacao)){
      window.regrasPremiacaoPublicas=payload.regrasPremiacao.slice();
    }

    const mensal=String(payload.horarioMensal||payload.horarioMensalISO||'').trim();
    let current=(window.__v2BootstrapHorarios && typeof window.__v2BootstrapHorarios==='object')
      ?window.__v2BootstrapHorarios:{};
    if(!String(current.extras||'').trim()){
      try{
        const saved=JSON.parse(localStorage.getItem('DISMEPE_V2_HOME_TIMES')||'{}');
        if(saved && typeof saved==='object')current=Object.assign({},saved,current);
      }catch(e){}
    }

    window.__v2BootstrapHorarios={
      mensal:mensal||String(current.mensal||''),
      extras:String(current.extras||'')
    };
    try{
      localStorage.setItem('DISMEPE_V2_HOME_TIMES',JSON.stringify(window.__v2BootstrapHorarios));
    }catch(e){}

    try{
      window.setUpdatedLabel?.(
        '', '',
        window.__v2BootstrapHorarios.mensal,
        window.__v2BootstrapHorarios.extras
      );
    }catch(e){}

    try{
      const period=String(document.getElementById('cm18Period')?.value||'').trim();
      const monthlyManager=document.getElementById('monthlyCampaignManagerModule');
      if(period && monthlyManager && !monthlyManager.classList.contains('hidden')){
        await window.cm18SelectCompetence?.(period);
      }
    }catch(e){
      console.warn('[PROD5.9.7 Mensal refresh]',e);
    }

    try{
      window.dispatchEvent(new CustomEvent('dismepe:monthly-snapshot-updated',{detail:payload}));
    }catch(e){}
  }

  function watchMonthly(baseline){
    const myGeneration=++generation;
    let base=String(baseline||'').trim();

    waits.forEach(delay=>{
      setTimeout(async()=>{
        if(myGeneration!==generation)return;
        const payload=await bootstrap();
        if(!payload)return;
        const current=snapshotTime(payload);
        if(!current)return;

        if(!base){
          base=current;
          return;
        }
        if(!isNewer(current,base))return;

        generation++;
        await applyMonthlySnapshot(payload);
      },delay);
    });
  }

  window.postApi=async function(body){
    if(!monthlyRequested(body)){
      return previousPostApi.apply(this,arguments);
    }

    // Captura o timestamp persistido ANTES do pedido para não confundir o
    // horário do clique com a conclusão real do worker.
    const before=await bootstrap();
    const baseline=snapshotTime(before)||rememberedMonthly();

    try{
      return await previousPostApi.apply(this,arguments);
    }finally{
      // Mesmo se o transporte legado devolver 502 depois de ter aceitado o
      // trabalho, acompanhamos o PostgreSQL; só um snapshot realmente novo
      // atualiza o horário e os dados Mensais.
      watchMonthly(baseline);
    }
  };
})();
