/* DISMEPE ONE Industrias: tela isolada para positivacoes do laboratorio Globo. */
(()=>{
  'use strict';
  if(window.__DISMEPE_INDUSTRIES_GLOBO_POS__)return;
  window.__DISMEPE_INDUSTRIES_GLOBO_POS__=true;
  const normalize=value=>String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();
  const escape=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const number=value=>Number(value||0).toLocaleString('pt-BR');
  let requestNumber=0;
  let tab,view,labSelect,competenceSelect,status,bodyV,bodyT,metrics;

  function selectedGlobo(){return normalize(labSelect?.value)==='GLOBO';}
  function selectedView(){return tab?.classList.contains('active')===true;}
  function restoreMetrics(show){if(metrics)metrics.classList.toggle('hidden',!show);}

  function refreshVisibility(){
    const authorizedSelection=selectedGlobo();
    if(!tab)return;
    tab.hidden=!authorizedSelection;
    tab.classList.toggle('hidden',!authorizedSelection);
    if(!authorizedSelection){
      requestNumber++;
      if(selectedView()&&typeof window.switchView==='function')window.switchView('inicio');
      restoreMetrics(true);
      if(status)status.textContent='Selecione o laboratório Globo para consultar suas positivações.';
      if(bodyV)bodyV.replaceChildren();
      if(bodyT)bodyT.replaceChildren();
    }
  }

  function fillTable(body,rows){
    body.innerHTML=rows.length?rows.map(row=>`<tr><td><b>${escape(row.profissional)}</b></td>`+
      `<td class="rightnum"><b>${number(row.positivados)}</b></td>`+
      `<td class="rightnum">${row.meta==null?'—':number(row.meta)}</td>`+
      `<td class="rightnum">${row.atingimento==null?'—':escape(Number(row.atingimento).toLocaleString('pt-BR',{maximumFractionDigits:2}))+'%'}</td></tr>`
    ).join(''):'<tr><td colspan="4" style="text-align:center;padding:18px;color:#71807b">Nenhum profissional cadastrado nesta base.</td></tr>';
  }

  async function load(){
    const id=++requestNumber;
    if(!selectedGlobo()||!selectedView())return;
    const competence=String(competenceSelect?.value||'').trim();
    if(!/^\d{2}\/\d{4}$/.test(competence)){
      status.textContent='Selecione uma competência para consultar as positivações Globo.';
      return;
    }
    status.textContent='Carregando positivações Globo de '+competence+'...';
    bodyV.replaceChildren();bodyT.replaceChildren();
    try{
      const response=await fetch('/industrias/globo-positivacoes?competencia='+encodeURIComponent(competence),
        {credentials:'include',cache:'no-store'});
      let data={};try{data=await response.json();}catch(_){/* retorno invalido */}
      if(id!==requestNumber||!selectedGlobo()||!selectedView()||competence!==competenceSelect.value)return;
      if(!response.ok||data.sucesso!==true){
        const detail=typeof data.detail==='string'?data.detail:'Não foi possível consultar a base Globo.';
        throw new Error(detail);
      }
      if(data.laboratorio!=='GLOBO'||data.competencia!==competence)throw new Error('A base retornou uma competência ou laboratório diferente.');
      if(!data.disponivel){
        status.textContent='Não há registros de positivação Globo disponíveis para '+competence+'. Nenhuma contagem foi estimada.';
        return;
      }
      fillTable(bodyV,Array.isArray(data.vendedores)?data.vendedores:[]);
      fillTable(bodyT,Array.isArray(data.televendas)?data.televendas:[]);
      status.textContent='Competência '+competence+' • última venda registrada: '+(data.ultimaVenda||'—')+'. Cada cliente é contado uma vez por profissional e canal; pode aparecer em ambos os canais.';
    }catch(error){
      if(id===requestNumber)status.textContent=error.message||'A base Globo está temporariamente indisponível.';
    }
  }

  function initialize(){
    const nav=document.getElementById('tabs');
    const main=document.querySelector('main');
    labSelect=document.getElementById('labSelect');
    competenceSelect=document.getElementById('compSelect');
    if(!nav||!main||!labSelect||!competenceSelect||document.getElementById('view-globo-positivacoes'))return;
    metrics=main.querySelector('.kpis');
    tab=document.createElement('button');
    tab.className='tab hidden';tab.type='button';tab.hidden=true;tab.dataset.view='globo-positivacoes';
    tab.innerHTML='<i class="fa-solid fa-users-viewfinder"></i>&nbsp; Positivações Globo';
    nav.appendChild(tab);
    view=document.createElement('section');
    view.id='view-globo-positivacoes';view.className='panel view hidden';
    view.innerHTML='<div class="card table-card"><div class="table-top"><div class="panel-title">'+
      '<h2>Positivações Globo</h2><p>Clientes únicos que compraram Globo, por vendedor e televendas na competência selecionada.</p></div></div>'+
      '<p id="globoPosStatus" role="status" style="margin:14px 16px;font-size:12px;color:#50635d"></p></div>'+
      '<div class="card table-card" style="margin-top:14px"><div class="table-top"><div class="panel-title"><h2>Vendedores</h2><p>Positivação Globo por vendedor.</p></div></div>'+
      '<div class="table-wrap"><table><thead><tr><th>Vendedor</th><th class="rightnum">Clientes positivados</th><th class="rightnum">Meta de clientes</th><th class="rightnum">Atingimento</th></tr></thead><tbody id="globoPosVendedores"></tbody></table></div></div>'+
      '<div class="card table-card" style="margin-top:14px"><div class="table-top"><div class="panel-title"><h2>Televendas</h2><p>Positivação Globo por televendas.</p></div></div>'+
      '<div class="table-wrap"><table><thead><tr><th>Televendas</th><th class="rightnum">Clientes positivados</th><th class="rightnum">Meta de clientes</th><th class="rightnum">Atingimento</th></tr></thead><tbody id="globoPosTelevendas"></tbody></table></div></div>';
    main.appendChild(view);
    status=document.getElementById('globoPosStatus');
    bodyV=document.getElementById('globoPosVendedores');
    bodyT=document.getElementById('globoPosTelevendas');
    tab.addEventListener('click',()=>{
      if(!selectedGlobo()||typeof window.switchView!=='function')return;
      window.switchView('globo-positivacoes');
      restoreMetrics(false);
      load();
    });
    nav.addEventListener('click',event=>{
      if(event.target.closest('.tab')!==tab){requestNumber++;restoreMetrics(true);}
    });
    labSelect.addEventListener('change',()=>{refreshVisibility();if(selectedView())load();});
    competenceSelect.addEventListener('change',()=>{if(selectedView())load();});
    new MutationObserver(()=>{
      refreshVisibility();
    }).observe(labSelect,{childList:true,subtree:true});
    refreshVisibility();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});
  else initialize();
})();
