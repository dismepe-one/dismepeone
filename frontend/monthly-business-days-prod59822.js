/* DISMEPE ONE — PROD5.9.8.22
   Dias úteis automáticos da Campanha Mensal.
   Regra: segunda a sexta, menos dias inativos cadastrados por competência.
   O número restante é calculado no servidor com fuso America/Recife. */
(function(){
  if(window.__dismepeMonthlyBusinessDays59822Installed)return;
  window.__dismepeMonthlyBusinessDays59822Installed=true;

  const state={
    installed:false,
    competencia:'',
    diasInativos:[],
    podeEditar:false,
    bloqueado:false,
    requestGeneration:0
  };

  const $=id=>document.getElementById(id);

  function esc(value){
    return String(value??'').replace(/[&<>"']/g,ch=>({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[ch]));
  }

  function comp(value){
    const s=String(value||'').trim();
    let m=s.match(/^(\d{1,2})\/(20\d{2})$/);
    if(m)return String(Number(m[1])).padStart(2,'0')+'/'+m[2];
    m=s.match(/^(20\d{2})-(\d{1,2})$/);
    if(m)return String(Number(m[2])).padStart(2,'0')+'/'+m[1];
    return '';
  }

  function currentComp(){
    const now=new Date();
    return String(now.getMonth()+1).padStart(2,'0')+'/'+now.getFullYear();
  }

  function selectedComp(fallback){
    return comp(fallback)||comp($('cm18Period')?.value)||state.competencia||currentComp();
  }

  function compRange(c){
    const normalized=comp(c);
    const m=normalized.match(/^(\d{2})\/(20\d{2})$/);
    if(!m)return {min:'',max:''};
    const month=Number(m[1]);
    const year=Number(m[2]);
    const last=new Date(year,month,0).getDate();
    return {
      min:`${year}-${String(month).padStart(2,'0')}-01`,
      max:`${year}-${String(month).padStart(2,'0')}-${String(last).padStart(2,'0')}`
    };
  }

  function ptDate(iso){
    const m=String(iso||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return m?`${m[3]}/${m[2]}/${m[1]}`:String(iso||'');
  }

  function isWeekend(iso){
    const d=new Date(String(iso||'')+'T12:00:00');
    if(Number.isNaN(d.getTime()))return false;
    return d.getDay()===0||d.getDay()===6;
  }

  function errorText(data,status){
    const detail=data?.detail;
    if(typeof detail==='string'&&detail.trim())return detail;
    if(detail&&typeof detail==='object'){
      const nested=detail.mensagem||detail.message||detail.erro||detail.error;
      if(nested)return String(nested);
    }
    return String(data?.mensagem||data?.erro||data?.error||`HTTP ${status}`);
  }

  async function api(method,c,payload){
    const normalized=comp(c);
    const url='/admin/monthly/business-days'+(
      method==='GET'?`?competencia=${encodeURIComponent(normalized)}`:''
    );
    const response=await fetch(url,{
      method,
      credentials:'same-origin',
      cache:'no-store',
      headers:{'Accept':'application/json','Content-Type':'application/json'},
      ...(payload?{body:JSON.stringify(payload)}:{})
    });
    let data={};
    try{data=await response.json();}catch(e){}
    if(!response.ok)throw new Error(errorText(data,response.status));
    return data;
  }

  function status(message,type){
    const el=$('cm59822Status');
    if(!el)return;
    el.textContent=message||'';
    el.className='mt-2 text-[10px] font-semibold '+(
      type==='error'?'text-rose-600':type==='ok'?'text-emerald-700':'text-slate-500'
    );
  }

  function setLoading(loading){
    const root=$('cm59822BusinessDays');
    if(root)root.classList.toggle('opacity-60',!!loading);
    const add=$('cm59822AddInactive');
    if(add)add.disabled=!!loading||!state.podeEditar||state.bloqueado;
  }

  function renderList(){
    const list=$('cm59822InactiveList');
    if(!list)return;

    const rows=[...state.diasInativos].sort((a,b)=>String(a.data).localeCompare(String(b.data)));
    if(!rows.length){
      list.innerHTML='<div class="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-[10px] text-slate-500">Nenhum dia inativo cadastrado nesta competência.</div>';
      return;
    }

    list.innerHTML=rows.map(item=>`
      <div class="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
        <div class="min-w-0">
          <div class="text-xs font-black text-slate-800">${esc(ptDate(item.data))}</div>
          <div class="truncate text-[9px] text-slate-500">${esc(item.motivo||'Dia inativo')}</div>
        </div>
        <button type="button" data-cm59822-remove="${esc(item.data)}" class="shrink-0 rounded-lg border border-rose-200 px-2.5 py-1.5 text-[9px] font-black text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40" ${(!state.podeEditar||state.bloqueado)?'disabled':''}>
          REMOVER
        </button>
      </div>
    `).join('');

    list.querySelectorAll('[data-cm59822-remove]').forEach(btn=>{
      btn.addEventListener('click',()=>removeInactive(btn.getAttribute('data-cm59822-remove')||''));
    });
  }

  function render(data){
    state.competencia=comp(data?.competencia)||state.competencia;
    state.diasInativos=Array.isArray(data?.diasInativos)?data.diasInativos.map(x=>({
      data:String(x?.data||''),
      motivo:String(x?.motivo||'')
    })).filter(x=>x.data):[];
    state.podeEditar=data?.podeEditar===true;
    state.bloqueado=data?.bloqueado===true;

    const remaining=$('cm59822Remaining');
    if(remaining)remaining.textContent=String(Number(data?.diasUteisRestantes??0));
    const total=$('cm59822Total');
    if(total)total.textContent=String(Number(data?.diasUteisTotais??0));
    const ref=$('cm59822Reference');
    if(ref)ref.textContent=data?.dataReferencia?ptDate(data.dataReferencia):'—';
    const label=$('cm59822Competence');
    if(label)label.textContent=state.competencia||'—';

    const range=compRange(state.competencia);
    const dateInput=$('cm59822InactiveDate');
    if(dateInput){
      dateInput.min=range.min;
      dateInput.max=range.max;
      dateInput.disabled=!state.podeEditar||state.bloqueado;
    }
    const reason=$('cm59822InactiveReason');
    if(reason)reason.disabled=!state.podeEditar||state.bloqueado;
    const add=$('cm59822AddInactive');
    if(add)add.disabled=!state.podeEditar||state.bloqueado;

    renderList();

    if(state.bloqueado){
      status('Competência congelada/fechada: os dias inativos estão em modo somente leitura.','info');
    }else if(!state.podeEditar){
      status('Você pode consultar o cálculo, mas não possui permissão para alterar os dias inativos.','info');
    }else{
      status('Cálculo automático ativo. Sábados e domingos já são ignorados pelo sistema.','ok');
    }
  }

  function applyLiveDays(data){
    const c=comp(data?.competencia);
    const selected=selectedComp();
    if(c&&c===selected){
      window.diasUteisRestantesMensal=Number(data?.diasUteisRestantes||0);
      try{window.updateDashboard?.();}catch(e){}
      try{window.renderOverview?.();}catch(e){}
      try{
        window.dispatchEvent(new CustomEvent('dismepe:business-days-updated',{detail:data}));
      }catch(e){}
    }
  }

  async function load(c){
    const normalized=selectedComp(c);
    if(!normalized)return;
    const generation=++state.requestGeneration;
    state.competencia=normalized;
    setLoading(true);
    status('Carregando dias úteis automáticos...','info');
    try{
      const data=await api('GET',normalized);
      if(generation!==state.requestGeneration)return;
      render(data);
      applyLiveDays(data);
    }catch(e){
      if(generation!==state.requestGeneration)return;
      status(e?.message||'Não foi possível carregar os dias úteis automáticos.','error');
    }finally{
      if(generation===state.requestGeneration)setLoading(false);
    }
  }

  async function persist(nextRows){
    if(!state.competencia||!state.podeEditar||state.bloqueado)return false;
    const previous=state.diasInativos.map(x=>({...x}));
    state.diasInativos=nextRows.map(x=>({...x}));
    renderList();
    setLoading(true);
    status('Salvando dias inativos...','info');
    try{
      const data=await api('POST',state.competencia,{
        competencia:state.competencia,
        diasInativos:state.diasInativos
      });
      render(data);
      applyLiveDays(data);
      status(data?.mensagem||'Dias inativos salvos.','ok');
      return true;
    }catch(e){
      state.diasInativos=previous;
      renderList();
      status(e?.message||'Não foi possível salvar os dias inativos.','error');
      return false;
    }finally{
      setLoading(false);
    }
  }

  async function addInactive(){
    const input=$('cm59822InactiveDate');
    const reason=$('cm59822InactiveReason');
    const iso=String(input?.value||'').trim();
    if(!iso){
      status('Escolha a data que não deverá contar como dia útil.','error');
      input?.focus();
      return;
    }
    const range=compRange(state.competencia);
    if((range.min&&iso<range.min)||(range.max&&iso>range.max)){
      status(`A data precisa pertencer à competência ${state.competencia}.`,'error');
      input?.focus();
      return;
    }
    if(isWeekend(iso)){
      status('Esse dia já é sábado/domingo e já é excluído automaticamente. Não precisa cadastrá-lo.','info');
      return;
    }

    const motivo=String(reason?.value||'').trim();
    const next=state.diasInativos.filter(x=>x.data!==iso);
    next.push({data:iso,motivo});
    next.sort((a,b)=>a.data.localeCompare(b.data));
    const ok=await persist(next);
    if(ok){
      if(input)input.value='';
      if(reason)reason.value='';
    }
  }

  async function removeInactive(iso){
    const next=state.diasInativos.filter(x=>x.data!==iso);
    await persist(next);
  }

  function buildUi(){
    const oldInput=$('cm97DiasUteis');
    if(!oldInput)return false;
    const block=oldInput.parentElement?.parentElement;
    if(!block)return false;

    block.id='cm59822BusinessDays';
    block.innerHTML=`
      <div class="flex flex-wrap items-center justify-between gap-2">
        <label class="block text-[10px] uppercase font-black text-slate-500">Dias úteis restantes</label>
        <span class="rounded-full bg-emerald-100 px-2.5 py-1 text-[9px] font-black text-emerald-700">AUTOMÁTICO</span>
      </div>

      <div class="mt-2 grid grid-cols-3 gap-2">
        <div class="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5">
          <div class="text-[8px] uppercase font-black text-emerald-700">Restantes</div>
          <div id="cm59822Remaining" class="mt-0.5 text-2xl font-black text-emerald-800">—</div>
        </div>
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
          <div class="text-[8px] uppercase font-black text-slate-500">Total no mês</div>
          <div id="cm59822Total" class="mt-0.5 text-lg font-black text-slate-800">—</div>
        </div>
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
          <div class="text-[8px] uppercase font-black text-slate-500">Competência</div>
          <div id="cm59822Competence" class="mt-1 text-xs font-black text-slate-800">—</div>
          <div class="mt-0.5 text-[8px] text-slate-400">Ref. <span id="cm59822Reference">—</span></div>
        </div>
      </div>

      <div class="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div class="mb-2 text-[9px] font-black uppercase tracking-wide text-slate-600">Cadastrar dia inativo</div>
        <div class="grid gap-2 md:grid-cols-[150px_minmax(0,1fr)_auto]">
          <input id="cm59822InactiveDate" type="date" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-800">
          <input id="cm59822InactiveReason" type="text" maxlength="160" placeholder="Motivo opcional: feriado, recesso, inventário..." class="min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800">
          <button id="cm59822AddInactive" type="button" class="rounded-lg bg-slate-800 px-3 py-2 text-[10px] font-black text-white hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-40">ADICIONAR</button>
        </div>
        <div class="mt-2 text-[9px] leading-4 text-slate-500">Segunda a sexta contam automaticamente. Sábados e domingos nunca entram no cálculo; cadastre apenas feriados, recessos ou outros dias sem operação.</div>
      </div>

      <div id="cm59822InactiveList" class="mt-2 space-y-1.5"></div>
      <div id="cm59822Status" class="mt-2 text-[10px] font-semibold text-slate-500"></div>
    `;

    $('cm59822AddInactive')?.addEventListener('click',addInactive);
    $('cm59822InactiveReason')?.addEventListener('keydown',event=>{
      if(event.key==='Enter'){
        event.preventDefault();
        addInactive();
      }
    });
    return true;
  }

  function wrapCompetenceSelector(){
    const old=window.cm18SelectCompetence;
    if(typeof old!=='function'||old.__prod59822BusinessDaysWrapped)return;
    const wrapped=async function(c){
      const result=await old.apply(this,arguments);
      setTimeout(()=>load(c),0);
      return result;
    };
    wrapped.__prod59822BusinessDaysWrapped=true;
    wrapped.__prod59822BusinessDaysOriginal=old;
    window.cm18SelectCompetence=wrapped;
  }

  function install(){
    if(state.installed)return true;
    if(!buildUi())return false;
    state.installed=true;
    wrapCompetenceSelector();
    $('cm18Period')?.addEventListener('change',event=>load(event.target?.value));
    load(selectedComp());
    return true;
  }

  function start(){
    if(install())return;
    let tries=0;
    const timer=setInterval(()=>{
      tries+=1;
      if(install()||tries>=40)clearInterval(timer);
    },250);
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',start,{once:true});
  }else{
    start();
  }
})();
