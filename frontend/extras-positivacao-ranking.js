/* DISMEPE ONE — Ranking por positivação em 16 produtos.
 * Regra fixa: só entra no ranking quem atingir 10 clientes válidos;
 * cada cliente válido precisa comprar pelo menos 2 produtos diferentes da lista.
 */
(function(){
  'use strict';

  const METRIC='RANKING_POSITIVACAO_PRODUTOS';
  const LABEL='Ranking por positivação — 16 produtos';
  const MIN_PRODUCTS=16;
  const MIN_CUSTOMERS=10;
  const MIN_MIX=2;
  const MAX_PRIZES=5;

  function byId(id){return document.getElementById(id);}
  function metric(){return String(byId('extraMetrica')?.value||'').toUpperCase();}
  function productCodes(){
    const raw=String(byId('extraProdutosSomados')?.value||'');
    const out=[]; const seen=new Set();
    raw.split(/[,;\n\r\t ]+/).forEach(value=>{
      let code=String(value||'').trim().toUpperCase().replace(/\.0+$/,'').replace(/[^A-Z0-9]/g,'');
      if(code&&!seen.has(code)){seen.add(code);out.push(code);}
    });
    return out;
  }
  function rankingRows(){
    return [...document.querySelectorAll('#extraRankingList .extra-ranking-row')].map(row=>{
      const inicio=Math.max(1,Math.floor(Number(row.querySelector('[data-rank-inicio]')?.value||0)));
      const fim=Math.max(inicio,Math.floor(Number(row.querySelector('[data-rank-fim]')?.value||inicio)));
      const brinde=String(row.querySelector('[data-rank-brinde]')?.value||'').trim();
      return {inicio,fim,brinde};
    }).filter(row=>row.brinde);
  }
  function prizeCoverage(){
    const covered=new Set();
    rankingRows().forEach(row=>{
      for(let p=row.inicio;p<=Math.min(row.fim,MAX_PRIZES);p++) covered.add(p);
    });
    return covered;
  }
  function ensureOptions(){
    const hidden=byId('extraMetrica');
    if(hidden && ![...hidden.options].some(o=>o.value===METRIC)){
      const option=document.createElement('option'); option.value=METRIC; option.textContent=LABEL; hidden.appendChild(option);
    }
    const base=byId('extraMetricaBase');
    if(base && ![...base.options].some(o=>o.value===METRIC)){
      const option=document.createElement('option'); option.value=METRIC; option.textContent=LABEL; base.appendChild(option);
    }
  }
  function ensureInfo(){
    const section=byId('extraProdutosSomadosSection');
    if(!section || byId('extraPosRankingRuleInfo')) return;
    const info=document.createElement('div');
    info.id='extraPosRankingRuleInfo';
    info.className='mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-[10px] leading-5 text-emerald-900';
    info.innerHTML='<b>Regra de entrada no ranking:</b> cadastre exatamente 16 produtos. O colaborador só aparece no ranking depois de atingir <b>10 clientes válidos</b>. Cada cliente só é válido quando tiver saldo positivo em <b>2 ou mais produtos diferentes</b> da lista. As posições 1º a 5º recebem os brindes cadastrados.';
    section.appendChild(info);
  }
  function ensureFivePrizeRows(){
    const list=byId('extraRankingList');
    if(!list || typeof window.addExtraRankingRow!=='function') return;
    if(list.querySelectorAll('.extra-ranking-row').length) return;
    for(let p=1;p<=MAX_PRIZES;p++) window.addExtraRankingRow(p,p,'');
  }
  function applyMetricUI(){
    ensureOptions();
    if(metric()!==METRIC) return;

    byId('extraProdutosSomadosSection')?.classList.remove('hidden');
    byId('extraRankingSection')?.classList.remove('hidden');
    byId('extraFaixasSection')?.classList.add('hidden');
    byId('extraBrindeSection')?.classList.add('hidden');

    const rank=byId('extraRankingSection');
    if(rank){
      const title=rank.querySelector('.text-xs.font-black');
      const desc=rank.querySelector('.text-\\[10px\\]');
      if(title) title.textContent='Ranking por positivação';
      if(desc) desc.textContent='Somente elegíveis entram no ranking. Cadastre os brindes do 1º ao 5º lugar.';
    }
    const label=byId('extraProdutosSomadosSection')?.querySelector('label');
    if(label) label.textContent='16 produtos participantes *';

    ensureFivePrizeRows();
    ensureInfo();
  }

  function install(){
    ensureOptions();

    const originalSync=window.syncExtraMetricFromSimpleUI;
    if(typeof originalSync==='function' && !originalSync.__posRankingWrapped){
      const wrapped=function(){
        if(byId('extraMetricaBase')?.value===METRIC){
          const hidden=byId('extraMetrica');
          if(hidden) hidden.value=METRIC;
          const prize=byId('extraTipoPremiacao');
          if(prize && [...prize.options].some(o=>o.value==='RANKING_BRINDE')) prize.value='RANKING_BRINDE';
          window.updateExtraMetricUI?.();
          applyMetricUI();
          return;
        }
        return originalSync.apply(this,arguments);
      };
      wrapped.__posRankingWrapped=true;
      window.syncExtraMetricFromSimpleUI=wrapped;
    }

    const originalUpdate=window.updateExtraMetricUI;
    if(typeof originalUpdate==='function' && !originalUpdate.__posRankingWrapped){
      const wrapped=function(){
        const result=originalUpdate.apply(this,arguments);
        applyMetricUI();
        return result;
      };
      wrapped.__posRankingWrapped=true;
      window.updateExtraMetricUI=wrapped;
    }

    const originalEdit=window.editExtraCampaign;
    if(typeof originalEdit==='function' && !originalEdit.__posRankingWrapped){
      const wrapped=function(id){
        const result=originalEdit.apply(this,arguments);
        if(metric()===METRIC){
          const base=byId('extraMetricaBase'); if(base) base.value=METRIC;
          const prize=byId('extraTipoPremiacao');
          if(prize && [...prize.options].some(o=>o.value==='RANKING_BRINDE')) prize.value='RANKING_BRINDE';
          applyMetricUI();
        }
        return result;
      };
      wrapped.__posRankingWrapped=true;
      window.editExtraCampaign=wrapped;
    }

    const originalSave=window.saveExtraCampaign;
    if(typeof originalSave==='function' && !originalSave.__posRankingWrapped){
      const wrapped=async function(){
        if(metric()===METRIC){
          const codes=productCodes();
          if(codes.length!==MIN_PRODUCTS){
            alert('Informe exatamente '+MIN_PRODUCTS+' códigos de produtos diferentes. Atualmente há '+codes.length+'.');
            byId('extraProdutosSomados')?.focus();
            return;
          }
          const coverage=prizeCoverage();
          const missing=[]; for(let p=1;p<=MAX_PRIZES;p++) if(!coverage.has(p)) missing.push(p+'º');
          if(missing.length){
            alert('Informe os brindes das cinco posições do ranking. Faltando: '+missing.join(', ')+'.');
            return;
          }
        }
        return await originalSave.apply(this,arguments);
      };
      wrapped.__posRankingWrapped=true;
      window.saveExtraCampaign=wrapped;
    }

    byId('extraMetricaBase')?.addEventListener('change',()=>setTimeout(applyMetricUI,0));
    applyMetricUI();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(install,0),{once:true});
  else setTimeout(install,0);
})();
