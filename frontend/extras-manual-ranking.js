/* DISMEPE ONE — Ranking Manual nas Campanhas Extras.
 * Gestão informa posição, colaborador e premiação. Usuário final recebe apenas
 * o ranking; valores financeiros permanecem administrativos/Resumo de Ganhos.
 */
(function(){
  'use strict';

  const METRIC='RANKING_MANUAL';
  const LABEL='Ranking manual — resultado lançado pela gestão';
  const DEFAULT_POSITIONS=5;
  let users=[];
  let campaignCache=new Map();
  let editingId='';
  let installing=false;

  const $=id=>document.getElementById(id);
  const metric=()=>String($('extraMetrica')?.value||'').trim().toUpperCase();
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function ensureOptions(){
    for(const id of ['extraMetrica','extraMetricaBase']){
      const select=$(id);
      if(select && ![...select.options].some(option=>option.value===METRIC)){
        const option=document.createElement('option');
        option.value=METRIC; option.textContent=LABEL; select.appendChild(option);
      }
    }
  }

  async function loadUsers(){
    if(users.length) return users;
    try{
      const response=await fetch('/data/extras-users',{credentials:'include',cache:'no-store'});
      if(!response.ok) return users;
      const data=await response.json();
      users=Array.isArray(data?.usuarios)?data.usuarios:[];
    }catch(_err){}
    return users;
  }

  function userLabel(row){
    const name=String(row?.vendedor||row?.nome||row?.usuario||'').trim();
    const type=String(row?.tipo||'').trim();
    return type?`${name} — ${type}`:name;
  }

  function selectOptions(selected=''){
    const selectedKey=String(selected||'').trim().toUpperCase();
    const rows=['<option value="">Selecione o colaborador</option>'];
    const sorted=[...users].sort((a,b)=>userLabel(a).localeCompare(userLabel(b),'pt-BR'));
    for(const row of sorted){
      const value=String(row?.vendedor||row?.nome||row?.usuario||'').trim();
      if(!value) continue;
      const sel=value.toUpperCase()===selectedKey?' selected':'';
      rows.push(`<option value="${esc(value)}"${sel}>${esc(userLabel(row))}</option>`);
    }
    if(selected && !sorted.some(row=>String(row?.vendedor||row?.nome||row?.usuario||'').trim().toUpperCase()===selectedKey)){
      rows.push(`<option value="${esc(selected)}" selected>${esc(selected)}</option>`);
    }
    return rows.join('');
  }

  function manualRows(){
    return [...document.querySelectorAll('#extraManualRankingList [data-manual-ranking-row]')]
      .map(row=>({
        posicao:Number(row.getAttribute('data-position')||0),
        colaborador:String(row.querySelector('[data-manual-collaborator]')?.value||'').trim(),
        premiacao:Number(row.querySelector('[data-manual-prize]')?.value||0),
      }))
      .filter(row=>row.posicao>0 && (row.colaborador || row.premiacao>0));
  }

  function addManualRow(position,data={}){
    const list=$('extraManualRankingList'); if(!list) return;
    const row=document.createElement('div');
    row.setAttribute('data-manual-ranking-row','1');
    row.setAttribute('data-position',String(position));
    row.className='grid grid-cols-1 gap-2 rounded-xl border border-slate-200 bg-white p-3 md:grid-cols-[90px_minmax(220px,1fr)_180px]';
    row.innerHTML=`
      <div><label class="text-[10px] font-black uppercase tracking-wide text-slate-500">Posição</label><div class="mt-1 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-black text-emerald-800">${position}º lugar</div></div>
      <div><label class="text-[10px] font-black uppercase tracking-wide text-slate-500">Colaborador</label><select data-manual-collaborator class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800">${selectOptions(data.colaborador||'')}</select></div>
      <div><label class="text-[10px] font-black uppercase tracking-wide text-slate-500">Premiação (somente gestão)</label><input data-manual-prize type="number" min="0" step="0.01" value="${Number(data.premiacao||0)||''}" placeholder="R$ 0,00" class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-bold text-slate-800"></div>`;
    list.appendChild(row);
  }

  async function renderManualRows(config=[]){
    await loadUsers();
    const list=$('extraManualRankingList'); if(!list) return;
    list.innerHTML='';
    const indexed=new Map((Array.isArray(config)?config:[]).map(row=>[Number(row?.posicao||0),row]));
    const max=Math.max(DEFAULT_POSITIONS,...indexed.keys());
    for(let position=1;position<=max;position++) addManualRow(position,indexed.get(position)||{});
  }

  function ensureManualSection(){
    if($('extraManualRankingSection')) return;
    const anchor=$('extraRankingSection') || $('extraProdutosSomadosSection') || $('extraBrindeSection');
    if(!anchor || !anchor.parentElement) return;
    const section=document.createElement('div');
    section.id='extraManualRankingSection';
    section.className='hidden mt-4 rounded-2xl border border-emerald-200 bg-emerald-50/50 p-4';
    section.innerHTML=`
      <div class="text-xs font-black uppercase tracking-wide text-emerald-900">Ranking manual</div>
      <div class="mt-1 text-[10px] leading-5 text-emerald-800">Informe manualmente os colocados e a premiação. <b>Os usuários verão somente posição e nome.</b> Os valores entram exclusivamente no Resumo de Ganhos e ficam visíveis à gestão.</div>
      <div id="extraManualRankingList" class="mt-3 space-y-2"></div>
      <button type="button" id="extraManualAddPosition" class="mt-3 rounded-xl border border-emerald-300 bg-white px-3 py-2 text-xs font-black text-emerald-800">+ Adicionar posição</button>`;
    anchor.parentElement.insertBefore(section,anchor.nextSibling);
    $('extraManualAddPosition')?.addEventListener('click',()=>{
      const count=document.querySelectorAll('#extraManualRankingList [data-manual-ranking-row]').length;
      addManualRow(count+1,{});
    });
  }

  async function applyUI(config=null){
    ensureOptions(); ensureManualSection();
    if(metric()!==METRIC){
      $('extraManualRankingSection')?.classList.add('hidden');
      return;
    }
    $('extraManualRankingSection')?.classList.remove('hidden');
    $('extraRankingSection')?.classList.add('hidden');
    $('extraProdutosSomadosSection')?.classList.add('hidden');
    $('extraFaixasSection')?.classList.add('hidden');
    $('extraBrindeSection')?.classList.add('hidden');
    const rows=config || campaignCache.get(editingId)?.regra?.rankingManual || [];
    if(!$('extraManualRankingList')?.children.length || config) await renderManualRows(rows);
  }

  function validateManualRows(){
    const rows=manualRows();
    if(!rows.length){alert('Informe pelo menos uma posição no Ranking Manual.');return false;}
    const positions=new Set(); const collaborators=new Set();
    for(const row of rows){
      if(!row.colaborador){alert(`Selecione o colaborador do ${row.posicao}º lugar.`);return false;}
      if(!Number.isFinite(row.premiacao)||row.premiacao<=0){alert(`Informe a premiação do ${row.posicao}º lugar.`);return false;}
      if(positions.has(row.posicao)){alert(`A posição ${row.posicao}º está repetida.`);return false;}
      const key=row.colaborador.toUpperCase();
      if(collaborators.has(key)){alert(`${row.colaborador} aparece mais de uma vez no ranking.`);return false;}
      positions.add(row.posicao); collaborators.add(key);
    }
    const max=Math.max(...positions);
    for(let position=1;position<=max;position++) if(!positions.has(position)){alert('As posições precisam ser sequenciais a partir do 1º lugar.');return false;}
    return true;
  }

  function installFetchPatch(){
    if(window.fetch.__manualRankingWrapped) return;
    const original=window.fetch.bind(window);
    const wrapped=async function(input,init){
      const url=typeof input==='string'?input:String(input?.url||'');
      const method=String(init?.method||input?.method||'GET').toUpperCase();
      let nextInit=init;
      if(method==='POST' && url.includes('/admin/campanhas-extras/save') && init?.body){
        try{
          const payload=JSON.parse(init.body);
          if(String(payload?.campanha?.metrica||'').toUpperCase()===METRIC){
            if(!validateManualRows()) throw new Error('__DISMEPE_MANUAL_RANKING_INVALID__');
            payload.campanha.regra=payload.campanha.regra&&typeof payload.campanha.regra==='object'?payload.campanha.regra:{};
            payload.campanha.regra.rankingManual=manualRows();
            payload.campanha.regra.fonteResultado='MANUAL';
            payload.campanha.regra.premiacaoVisivelUsuarios=false;
            payload.campanha.tipoPremiacao='RANKING_MANUAL_DINHEIRO';
            nextInit={...init,body:JSON.stringify(payload)};
          }
        }catch(err){
          if(err?.message==='__DISMEPE_MANUAL_RANKING_INVALID__') throw err;
        }
      }
      const response=await original(input,nextInit);
      if(method==='GET' && url.includes('/data/campanhas-extras')){
        try{
          const data=await response.clone().json();
          const rows=Array.isArray(data?.campanhas)?data.campanhas:(Array.isArray(data?.todas)?data.todas:[]);
          if(rows.length) campaignCache=new Map(rows.map(c=>[String(c?.id||''),c]));
        }catch(_err){}
      }
      return response;
    };
    wrapped.__manualRankingWrapped=true;
    window.fetch=wrapped;
  }

  function installFormatters(){
    const realized=window.extraPartialRealizedText;
    if(typeof realized==='function' && !realized.__manualRankingWrapped){
      const wrapped=function(row){
        if(String(row?.metrica||'').toUpperCase()===METRIC){
          const p=Number(row?.posicaoRanking||0); return p>0?`${p}º lugar`:'Ranking manual';
        }
        return realized.apply(this,arguments);
      };
      wrapped.__manualRankingWrapped=true; window.extraPartialRealizedText=wrapped;
    }
    const objective=window.extraPartialObjectiveText;
    if(typeof objective==='function' && !objective.__manualRankingWrapped){
      const wrapped=function(row){
        if(String(row?.metrica||'').toUpperCase()===METRIC) return '—';
        return objective.apply(this,arguments);
      };
      wrapped.__manualRankingWrapped=true; window.extraPartialObjectiveText=wrapped;
    }
  }

  function install(){
    if(installing) return; installing=true;
    ensureOptions(); ensureManualSection(); installFetchPatch(); installFormatters(); loadUsers();

    const sync=window.syncExtraMetricFromSimpleUI;
    if(typeof sync==='function' && !sync.__manualRankingWrapped){
      const wrapped=function(){
        if($('extraMetricaBase')?.value===METRIC){
          if($('extraMetrica')) $('extraMetrica').value=METRIC;
          window.updateExtraMetricUI?.(); setTimeout(()=>applyUI(),0); return;
        }
        return sync.apply(this,arguments);
      };
      wrapped.__manualRankingWrapped=true; window.syncExtraMetricFromSimpleUI=wrapped;
    }

    const update=window.updateExtraMetricUI;
    if(typeof update==='function' && !update.__manualRankingWrapped){
      const wrapped=function(){const result=update.apply(this,arguments);setTimeout(()=>applyUI(),0);return result;};
      wrapped.__manualRankingWrapped=true; window.updateExtraMetricUI=wrapped;
    }

    const edit=window.editExtraCampaign;
    if(typeof edit==='function' && !edit.__manualRankingWrapped){
      const wrapped=function(id){
        editingId=String(id||''); const result=edit.apply(this,arguments);
        setTimeout(async()=>{
          ensureOptions();
          const config=campaignCache.get(editingId);
          if(config && String(config?.metrica||'').toUpperCase()===METRIC){
            if($('extraMetrica')) $('extraMetrica').value=METRIC;
            if($('extraMetricaBase')) $('extraMetricaBase').value=METRIC;
            await applyUI(config?.regra?.rankingManual||[]);
          }
        },50);
        return result;
      };
      wrapped.__manualRankingWrapped=true; window.editExtraCampaign=wrapped;
    }

    const save=window.saveExtraCampaign;
    if(typeof save==='function' && !save.__manualRankingWrapped){
      const wrapped=async function(){
        if(metric()===METRIC && !validateManualRows()) return;
        try{return await save.apply(this,arguments);}catch(err){
          if(err?.message==='__DISMEPE_MANUAL_RANKING_INVALID__') return;
          throw err;
        }
      };
      wrapped.__manualRankingWrapped=true; window.saveExtraCampaign=wrapped;
    }

    $('extraMetricaBase')?.addEventListener('change',()=>setTimeout(()=>applyUI(),0));
    setTimeout(()=>applyUI(),0); installing=false;
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(install,0),{once:true});
  else setTimeout(install,0);
})();
