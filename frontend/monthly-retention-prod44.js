/* DISMEPE ONE 2.0 — PROD4.4
   Retenção mensal operacional: mês atual + mês anterior.
   O mês fechado anterior continua disponível para consulta. */
(function(){
  if(window.__dismepeMonthlyRetentionProd44Installed)return;
  window.__dismepeMonthlyRetentionProd44Installed=true;

  const originalPostApi=window.postApi;
  if(typeof originalPostApi!=='function'){
    console.warn('[PROD4.4 RETENÇÃO MENSAL] postApi não disponível.');
    return;
  }

  function competenceWindow(){
    const parts=new Intl.DateTimeFormat('en-US',{
      timeZone:'America/Recife',
      year:'numeric',
      month:'2-digit'
    }).formatToParts(new Date());

    const map={};
    parts.forEach(p=>{ if(p.type!=='literal')map[p.type]=p.value; });

    let year=Number(map.year);
    let month=Number(map.month);
    const current=String(month).padStart(2,'0')+'/'+year;

    month-=1;
    if(month===0){month=12;year-=1;}
    const previous=String(month).padStart(2,'0')+'/'+year;

    return [current,previous];
  }

  function normalizeComp(value){
    const s=String(value||'').trim();
    let m=s.match(/^(0?[1-9]|1[0-2])[\/-](20\d{2})$/);
    if(m)return String(Number(m[1])).padStart(2,'0')+'/'+m[2];
    m=s.match(/^(20\d{2})[\/-](0?[1-9]|1[0-2])$/);
    if(m)return String(Number(m[2])).padStart(2,'0')+'/'+m[1];
    return s;
  }

  function dateValue(item){
    const raw=String(item?.dataHoraISO||item?.dataHoraFormatado||'').trim();
    if(!raw)return 0;
    const iso=Date.parse(raw);
    if(Number.isFinite(iso))return iso;
    const m=raw.match(/^(\d{2})\/(\d{2})\/(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
    if(!m)return 0;
    return Date.UTC(Number(m[3]),Number(m[2])-1,Number(m[1]),Number(m[4]),Number(m[5]),Number(m[6]||0));
  }

  function filterMonthlyHistory(result){
    if(!result || !Array.isArray(result.atualizacoes))return result;

    const retained=competenceWindow();
    const allowed=new Set(retained);
    const rows=result.atualizacoes
      .filter(x=>allowed.has(normalizeComp(x?.competencia)))
      .slice()
      .sort((a,b)=>dateValue(b)-dateValue(a));

    const latest=new Map();
    rows.forEach(item=>{
      const comp=normalizeComp(item?.competencia);
      if(comp && !latest.has(comp))latest.set(comp,item);
    });

    result.atualizacoes=retained.map(c=>latest.get(c)).filter(Boolean);
    result.limiteHistorico=2;
    result.limiteHistoricoCompetencias=2;
    result.competenciasRetidas=retained;
    result.retencaoAutomatica=true;
    return result;
  }

  window.postApi=async function(body){
    const result=await originalPostApi.apply(this,arguments);
    const action=String(body?.acao||body?.action||'').trim().toUpperCase();
    if(action==='HIST39_LISTAR')return filterMonthlyHistory(result);
    return result;
  };

  window.__DISMEPE_MONTHLY_RETENTION={
    competencias:competenceWindow(),
    limite:2,
    automatica:true
  };

  console.log(
    '[PROD4.4 RETENÇÃO MENSAL] Ativa:',
    window.__DISMEPE_MONTHLY_RETENTION.competencias.join(' + ')
  );
})();

/* Limpeza física: executada em segundo plano por usuário autorizado.
   Só marca o mês como concluído quando o servidor confirma todas as exclusões. */
(function(){
  const state=window.__DISMEPE_MONTHLY_RETENTION;
  if(!state || !Array.isArray(state.competencias) || !state.competencias.length)return;

  const monthKey='DISMEPE_MONTHLY_RETENTION_PURGED_'+state.competencias[0];
  let running=null;

  async function maybePurge(){
    try{
      if(localStorage.getItem(monthKey)==='OK')return true;
    }catch(e){}

    if(running)return running;

    running=(async()=>{
      try{
        const response=await fetch('/admin/monthly-retention',{
          method:'POST',
          credentials:'same-origin',
          cache:'no-store',
          headers:{'Accept':'application/json'}
        });

        if(response.status===401 || response.status===403 || response.status===409){
          return false;
        }

        let body={};
        try{body=await response.json();}catch(e){}

        if(!response.ok || body?.sucesso!==true){
          console.warn('[PROD4.4 RETENÇÃO MENSAL] Limpeza pendente.',body);
          return false;
        }

        try{localStorage.setItem(monthKey,'OK');}catch(e){}
        console.log(
          '[PROD4.4 RETENÇÃO MENSAL] Limpeza concluída.',
          body?.excluidos?.length||0,
          'registro(s) antigo(s) removido(s).'
        );
        return true;
      }catch(e){
        console.warn('[PROD4.4 RETENÇÃO MENSAL] Limpeza automática indisponível.',e);
        return false;
      }finally{
        running=null;
      }
    })();

    return running;
  }

  const originalOpen=window.openMonthlyCampaignManager;
  if(typeof originalOpen==='function' && !originalOpen.__prod44RetentionWrapped){
    const wrapped=function(){
      void maybePurge();
      return originalOpen.apply(this,arguments);
    };
    wrapped.__prod44RetentionWrapped=true;
    wrapped.__prod44Original=originalOpen;
    window.openMonthlyCampaignManager=wrapped;
  }

  window.addEventListener('load',()=>{
    setTimeout(()=>{void maybePurge();},8000);
  });

  window.__dismepeRunMonthlyRetention=maybePurge;
})();
