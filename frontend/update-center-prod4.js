/* DISMEPE ONE 2.0 — PROD4.3
   Consistência da Central + Gestão Mensal.
   - Central usa FastAPI para OPCACHE.
   - Horários são derivados da resposta confirmada e sincronizados com o snapshot.
   - Histórico não pode transformar campanha administrativa ativa em "fechada".
   - Após gravação de métrica, a lista é relida no legado para read-after-write. */
(function(){
  if(window.__dismepeUpdateCenterProd43Installed)return;
  window.__dismepeUpdateCenterProd43Installed=true;

  const originalPostApi=window.postApi;
  const originalFetch=window.fetch.bind(window);

  if(typeof originalPostApi!=='function'){
    console.warn('[PROD4.3] postApi não disponível.');
    return;
  }

  function compKey(value){
    const s=String(value||'').trim();
    let m=s.match(/^(\d{1,2})[\/-](20\d{2})$/);
    if(m)return String(Number(m[1])).padStart(2,'0')+'/'+m[2];
    m=s.match(/^(20\d{2})[\/-](\d{1,2})$/);
    if(m)return String(Number(m[2])).padStart(2,'0')+'/'+m[1];
    return s;
  }

  function tokenNow(){
    try{
      if(typeof authToken!=='undefined' && authToken)return String(authToken);
    }catch(e){}
    try{return String(localStorage.getItem('painelToken')||'');}catch(e){return '';}
  }

  function localMonthlyPayload(){
    try{
      if(typeof v102ReadDataCache==='function'){
        const value=v102ReadDataCache();
        if(value && typeof value==='object')return value;
      }
    }catch(e){}
    return {};
  }

  function activeMonthlyCompetences(){
    const payload=localMonthlyPayload();
    const active=new Set();

    const add=item=>{
      if(!item || typeof item!=='object')return;
      const c=compKey(item.competencia||item.COMPETENCIA||'');
      if(!c)return;
      if(item.fechada===true || item.congelada===true)return;
      const status=String(item.status||'').trim().toUpperCase();
      if(status.includes('HIST') || status==='FECHADA')return;
      active.add(c);
    };

    const managed=Array.isArray(payload.gestaoCampanhasMensaisLista)
      ?payload.gestaoCampanhasMensaisLista:[];
    managed.forEach(add);

    if(payload.campanhaMensalAtual && typeof payload.campanhaMensalAtual==='object'){
      add(payload.campanhaMensalAtual);
    }

    const current=compKey(payload.competenciaPrincipal||'');
    if(current && !managed.some(x=>compKey(x?.competencia||'')===current && (x?.fechada===true || x?.congelada===true))){
      active.add(current);
    }
    return active;
  }

  function sanitizeMonthlyHistory(result){
    if(!result || typeof result!=='object' || !Array.isArray(result.atualizacoes))return result;
    const active=activeMonthlyCompetences();
    if(!active.size)return result;
    return Object.assign({},result,{
      atualizacoes:result.atualizacoes.filter(x=>!active.has(compKey(x?.competencia||'')))
    });
  }

  function itemTime(item){
    if(!item || typeof item!=='object')return '';
    const keys=[
      'atualizadoEm','atualizado_em','horario','dataHoraFormatado',
      'dataHoraISO','dataHora','timestamp','updatedAt','updated_at'
    ];
    for(const key of keys){
      const value=item[key];
      if(value!==undefined && value!==null && String(value).trim()){
        return String(value).trim();
      }
    }
    if(item.historico && typeof item.historico==='object'){
      return itemTime(item.historico);
    }
    return '';
  }

  function moduleTime(result,moduleName){
    if(!result || typeof result!=='object')return '';
    const target=String(moduleName||'').toUpperCase();
    const top=target==='MENSAL'
      ?(result.horarioMensal||result.horarioMensalISO)
      :(result.horarioExtras||result.horarioExtrasISO);
    if(top)return String(top).trim();

    for(const key of ['resultados','modulos']){
      const rows=Array.isArray(result[key])?result[key]:[];
      for(const row of rows){
        if(!row || typeof row!=='object')continue;
        const name=String(row.modulo||row.nomeModulo||row.label||'').toUpperCase();
        if(name!==target && !name.includes(target))continue;
        const value=itemTime(row);
        if(value)return value;
      }
    }
    return '';
  }

  function persistTimes(result){
    if(!result || typeof result!=='object')return;
    const mensal=moduleTime(result,'MENSAL');
    const extras=moduleTime(result,'EXTRAS');
    if(!mensal && !extras)return;

    const current=(window.__v2BootstrapHorarios && typeof window.__v2BootstrapHorarios==='object')
      ?window.__v2BootstrapHorarios:{};

    window.__v2BootstrapHorarios={
      mensal:mensal || String(current.mensal||''),
      extras:extras || String(current.extras||'')
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

  async function syncBootstrapTimes(){
    try{
      const response=await originalFetch('/data/bootstrap?_prod43='+Date.now(),{
        method:'GET',
        credentials:'same-origin',
        cache:'no-store',
        headers:{'Accept':'application/json'}
      });
      if(!response.ok)return false;
      const payload=await response.json();
      persistTimes(payload);
      return true;
    }catch(e){
      return false;
    }
  }

  function scheduleTimeSync(){
    [900,2500,6000].forEach(ms=>{
      setTimeout(()=>{syncBootstrapTimes();},ms);
    });
  }

  async function updateCenterApi(body){
    const response=await originalFetch('/admin/update-center',{
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
      throw new Error('Resposta inválida do servidor da Central de Atualizações.');
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

  async function refreshMonthlyRules(comp, expectedLab){
    const competencia=compKey(comp);
    const token=tokenNow();
    if(!competencia || !token)return false;

    let last=null;
    const waits=[0,450,1200];

    for(const wait of waits){
      if(wait)await new Promise(resolve=>setTimeout(resolve,wait));
      try{
        const r=await originalPostApi({
          acao:'CM70_LISTARMODELOSREGRAS',
          token,
          competencia
        });
        if(!(r?.sucesso===true||r?.success===true||r?.ok===true))continue;
        const rules=Array.isArray(r.regrasExistentes)
          ?r.regrasExistentes
          :(Array.isArray(r.regrasPremiacao)?r.regrasPremiacao:[]);
        last={r,rules};

        if(!expectedLab)break;
        const expected=String(expectedLab||'').trim().toLocaleUpperCase('pt-BR');
        const found=rules.some(x=>
          String(x?.laboratorio||x?.lab||'').trim().toLocaleUpperCase('pt-BR')===expected
        );
        if(found)break;
      }catch(e){
        console.warn('[PROD4.3 regras live]',e);
      }
    }

    if(!last)return false;

    window.regrasPremiacaoPublicas=last.rules.slice();

    try{
      const cache=localMonthlyPayload();
      if(cache && typeof cache==='object'){
        cache.regrasPremiacao=last.rules.slice();
        if(typeof v102SaveDataCache==='function')v102SaveDataCache(cache);
      }
    }catch(e){}

    try{
      await window.cm18SelectCompetence?.(competencia);
    }catch(e){
      console.warn('[PROD4.3 refresh Gestão Mensal]',e);
    }
    return true;
  }

  async function refreshMonthlyBootstrap(){
    try{
      const response=await originalFetch('/data/bootstrap?_monthly_admin='+Date.now(),{
        method:'GET',
        credentials:'same-origin',
        cache:'no-store',
        headers:{'Accept':'application/json'}
      });
      if(!response.ok)return false;
      const payload=await response.json();
      if(!payload || typeof payload!=='object')return false;

      try{
        if(typeof v102SaveDataCache==='function')v102SaveDataCache(payload);
      }catch(e){}

      if(Array.isArray(payload.regrasPremiacao)){
        window.regrasPremiacaoPublicas=payload.regrasPremiacao.slice();
      }
      persistTimes(payload);

      const selected=
        compKey(document.getElementById('cm18Period')?.value||'') ||
        compKey(payload.competenciaPrincipal||'');

      if(selected && !document.getElementById('monthlyCampaignManagerModule')?.classList.contains('hidden')){
        await window.cm18SelectCompetence?.(selected);
      }
      return true;
    }catch(e){
      console.warn('[PROD4.3 bootstrap Gestão Mensal]',e);
      return false;
    }
  }

  window.postApi=async function(body){
    const action=String(body?.acao||body?.action||'').trim().toUpperCase();

    if(action==='OPCACHE_STATUS' || action==='OPCACHE_ATUALIZAR'){
      const result=await updateCenterApi(body);
      if(action==='OPCACHE_ATUALIZAR'){
        persistTimes(result);
        scheduleTimeSync();
      }
      return result;
    }

    const result=await originalPostApi.apply(this,arguments);
    if(action==='HIST39_LISTAR'){
      return sanitizeMonthlyHistory(result);
    }
    return result;
  };

  function installMonthlyManagerRefresh(){
    const fn=window.openMonthlyCampaignManager;
    if(typeof fn!=='function' || fn.__prod43Refresh)return;
    const wrapped=function(){
      const out=fn.apply(this,arguments);
      Promise.resolve(out).finally(()=>{
        refreshMonthlyBootstrap();
      });
      return out;
    };
    wrapped.__prod43Refresh=true;
    wrapped.__prod43Original=fn;
    window.openMonthlyCampaignManager=wrapped;
  }

  function installMetricRefresh(){
    const save=window.cm70SaveManualMetric;
    if(typeof save==='function' && !save.__prod43Refresh){
      const wrapped=async function(){
        const comp=compKey(document.getElementById('cm70Comp')?.value||'');
        const lab=String(document.getElementById('cm70Lab')?.value||'').trim();
        const out=await save.apply(this,arguments);
        await refreshMonthlyRules(comp,lab);
        return out;
      };
      wrapped.__prod43Refresh=true;
      wrapped.__prod43Original=save;
      window.cm70SaveManualMetric=wrapped;
    }

    const del=window.cm70DeleteMetric;
    if(typeof del==='function' && !del.__prod43Refresh){
      const wrappedDelete=async function(){
        const comp=compKey(
          document.getElementById('cm18Period')?.value ||
          document.getElementById('cm70Comp')?.value ||
          ''
        );
        const out=await del.apply(this,arguments);
        await refreshMonthlyRules(comp,'');
        return out;
      };
      wrappedDelete.__prod43Refresh=true;
      wrappedDelete.__prod43Original=del;
      window.cm70DeleteMetric=wrappedDelete;
    }
  }

  installMonthlyManagerRefresh();
  installMetricRefresh();

  window.addEventListener('load',()=>{
    [0,250,900].forEach(ms=>setTimeout(()=>{
      installMonthlyManagerRefresh();
      installMetricRefresh();
    },ms));
  });

  console.log('[PROD4.3] Central e consistência da Gestão Mensal ativas.');
})();
