/* DISMEPE ONE Indústrias: positivação Globo ao lado da parcial existente de cada canal. */
(()=>{
  'use strict';
  if(window.__DISMEPE_INDUSTRIES_GLOBO_POS__)return;
  window.__DISMEPE_INDUSTRIES_GLOBO_POS__=true;

  const COLUMNS=[['positivados','Positivados Globo'],['meta','Meta Globo'],['atingimento','% Positivação Globo']];
  const CHANNELS=[['VENDEDORES','vendedores','vendBody'],['TELEVENDAS','televendas','tlvBody']];
  const norm=value=>String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().replace(/\s+/g,' ').toUpperCase();
  const qty=value=>Number(value).toLocaleString('pt-BR',{maximumFractionDigits:0});
  const percent=value=>Number(value).toLocaleString('pt-BR',{maximumFractionDigits:2})+'%';
  const lab=()=>document.getElementById('labSelect');
  const comp=()=>document.getElementById('compSelect');
  const selectedGlobo=()=>norm(lab()?.value)==='GLOBO';
  const gateOpen=()=>{const g=document.getElementById('passwordGate');return g&&!g.classList.contains('hidden');};
  const currentData=()=>typeof salesData==='undefined'?null:salesData;
  let cache=null,pendingKey='',generation=0,lastGlobo=false;

  function scopeKey(){
    const data=currentData(), month=String(comp()?.value||'').trim();
    return selectedGlobo()&&!gateOpen()&&norm(data?.laboratorio)==='GLOBO'&&
      data?.competencia===month&&/^\d{2}\/\d{4}$/.test(month)?month:'';
  }
  function statusNode(view){
    const section=document.getElementById('view-'+view);
    const top=section?.querySelector('.table-top');
    if(!top)return null;
    let node=section.querySelector('[data-globo-pos-status]');
    if(!node){
      node=document.createElement('p');node.dataset.globoPosStatus='1';
      node.setAttribute('role','status');
      node.style.cssText='margin:0;padding:9px 16px;font-size:12px;color:#50635d;background:#f6faf8;border-bottom:1px solid #e3ede8';
      top.insertAdjacentElement('afterend',node);
    }
    return node;
  }
  function statusText(){
    const month=scopeKey();
    if(!month)return 'Aguardando a parcial do Globo e a competência selecionada.';
    if(pendingKey===month)return 'Carregando positivação Globo de '+month+'...';
    if(cache?.key!==month)return 'Aguardando positivação Globo de '+month+'...';
    if(cache.state==='error')return 'Positivação Globo indisponível: '+cache.error;
    if(cache.state==='empty')return 'Sem registros de positivação Globo para '+month+'.';
    return 'Positivação Globo • '+month+' • última venda: '+(cache.latest||'—')+'. Clientes únicos por profissional e canal.';
  }
  function cellValue(row,key){
    if(!row)return '—';
    if(key==='positivados')return Number.isFinite(Number(row.positivados))?qty(row.positivados):'—';
    if(key==='meta')return row.meta==null||!Number.isFinite(Number(row.meta))?'—':qty(row.meta);
    return row.atingimento==null||!Number.isFinite(Number(row.atingimento))?'—':percent(row.atingimento);
  }
  function decorate(channel,kind,bodyId){
    const section=document.getElementById('view-'+kind);
    const body=document.getElementById(bodyId);
    const header=body?.closest('table')?.querySelector('thead tr');
    if(!section||!body||!header)return;
    const enabled=selectedGlobo()&&!gateOpen();
    const info=statusNode(kind);
    if(info){info.hidden=!enabled;if(enabled)info.textContent=statusText();}
    header.querySelectorAll('[data-globo-pos-column]').forEach(el=>el.remove());
    body.querySelectorAll('[data-globo-pos-column]').forEach(el=>el.remove());
    if(!enabled){
      for(const tr of body.querySelectorAll('tr')){
        const blank=tr.querySelector('td[colspan]');
        if(blank)blank.colSpan=7;
      }
      return;
    }
    for(const [key,label] of COLUMNS){
      const th=document.createElement('th');th.className='rightnum';
      th.dataset.globoPosColumn=key;th.textContent=label;
      th.title='Somente clientes que compraram produtos do laboratório Globo';
      header.appendChild(th);
    }
    const rows=cache?.state==='ok'&&cache.key===scopeKey()?cache[kind]:null;
    for(const tr of body.querySelectorAll('tr')){
      const blank=tr.querySelector('td[colspan]');
      if(blank){blank.colSpan=10;continue;}
      const professional=norm(tr.querySelector('td:first-child b')?.textContent||tr.querySelector('td:first-child')?.textContent);
      const record=rows?.get(professional);
      for(const [key] of COLUMNS){
        const td=document.createElement('td');td.className='rightnum';td.dataset.globoPosColumn=key;
        td.textContent=cellValue(record,key);
        tr.appendChild(td);
      }
    }
  }
  function decorateBoth(){for(const args of CHANNELS)decorate(...args);}
  function invalidate(){generation++;pendingKey='';cache=null;}
  function handleLabChange(){
    const now=selectedGlobo();
    if(now!==lastGlobo){invalidate();lastGlobo=now;}
    decorateBoth();
    requestIfNeeded();
  }
  async function requestIfNeeded(){
    const key=scopeKey();
    if(!key)return;
    if(pendingKey===key)return;
    if(cache?.key===key&&Date.now()-cache.at<(cache.state==='error'?30000:170000))return;
    const token=++generation;
    pendingKey=key;
    decorateBoth();
    try{
      const response=await fetch('/industrias/globo-positivacoes?competencia='+encodeURIComponent(key),
        {credentials:'include',cache:'no-store'});
      let data={};try{data=await response.json();}catch(_){/* erro sem dados sensíveis */}
      if(token!==generation||scopeKey()!==key)return;
      if(!response.ok||data.sucesso!==true){
        throw new Error(typeof data.detail==='string'?data.detail:'Não foi possível consultar os dados do Globo.');
      }
      if(data.laboratorio!=='GLOBO'||data.competencia!==key)
        throw new Error('A resposta não corresponde ao laboratório e à competência selecionados.');
      const index=items=>new Map((Array.isArray(items)?items:[]).filter(x=>x&&x.profissional)
        .map(x=>[norm(x.profissional),x]));
      cache={key,at:Date.now(),state:data.disponivel?'ok':'empty',latest:data.ultimaVenda,
        vendedores:index(data.vendedores),televendas:index(data.televendas)};
    }catch(error){
      if(token===generation&&scopeKey()===key)
        cache={key,at:Date.now(),state:'error',error:String(error?.message||'Falha temporária.').slice(0,170)};
    }finally{
      if(token===generation){pendingKey='';decorateBoth();}
    }
  }
  function initialize(){
    const original=window.renderSales;
    if(typeof original!=='function'||!lab()||!comp()||!document.getElementById('vendBody')||!document.getElementById('tlvBody'))return;
    window.renderSales=function(channel){
      const result=original.apply(this,arguments);
      decorateBoth();
      requestIfNeeded();
      return result;
    };
    lab().addEventListener('change',handleLabChange);
    comp().addEventListener('change',()=>{invalidate();decorateBoth();});
    document.getElementById('tabs')?.addEventListener('click',()=>{decorateBoth();requestIfNeeded();});
    lastGlobo=selectedGlobo();
    decorateBoth();
    requestIfNeeded();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});
  else initialize();
})();
