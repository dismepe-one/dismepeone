/* DISMEPE ONE Indústrias: quadro POSITIVACAO_CLIENTES da própria base mensal.
   Exibição exclusiva do Globo; sem nova coluna, API paralela ou novo cálculo. */
(()=>{
  'use strict';
  if(window.__DISMEPE_INDUSTRIES_GLOBO_POS__)return;
  window.__DISMEPE_INDUSTRIES_GLOBO_POS__=true;
  const normalize=value=>String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();
  const number=value=>Number(value).toLocaleString('pt-BR',{maximumFractionDigits:2});
  const money=value=>Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const lab=()=>document.getElementById('labSelect');
  const comp=()=>document.getElementById('compSelect');
  const gateOpen=()=>{const gate=document.getElementById('passwordGate');return gate&&!gate.classList.contains('hidden');};
  const data=()=>typeof salesData==='undefined'?null:salesData;
  const allowed=()=>!gateOpen()&&normalize(lab()?.value)==='GLOBO'&&normalize(data()?.laboratorio)==='GLOBO'&&data()?.competencia===comp()?.value;

  function displayMetric(metric){
    if(!metric||typeof metric!=='object')return 'Aguardando a parcial de positivação Globo.';
    const realized=metric.realizado==null?'—':number(metric.realizado);
    const goal=metric.meta==null?'—':number(metric.meta);
    if(metric.pendente){
      const reason=String(metric.motivo||'').trim();
      return reason.toLowerCase().includes('base vazia')
        ?realized+' clientes positivados registrados'
        :'Aguardando atualização'+(reason?': '+reason:'.');
    }
    return realized+' / '+goal+' · Prêmio '+(metric.premio==null?'—':money(metric.premio));
  }

  function decorate(kind,bodyId){
    const body=document.getElementById(bodyId);
    if(!body)return;
    // Remova somente os elementos inseridos por esta funcionalidade.
    for(const box of body.querySelectorAll('[data-globo-pos-quadro]'))box.remove();
    if(!allowed())return;
    const rows=Array.isArray(data()?.[kind])?data()[kind]:[];
    const index=new Map(rows.filter(row=>row&&row.colaborador)
      .map(row=>[normalize(row.colaborador),row.positivacaoIndividualGlobo]));
    for(const tr of body.querySelectorAll('tr')){
      const cell=tr.querySelector('td:first-child');
      if(!cell||tr.querySelector('td[colspan]'))continue;
      const name=normalize(cell.querySelector('b')?.textContent||cell.textContent);
      const metric=index.get(name);
      const box=document.createElement('div');
      box.dataset.globoPosQuadro='1';
      box.style.cssText='box-sizing:border-box;margin-top:8px;padding:10px 12px;min-width:190px;max-width:360px;border:1px solid #77e7d2;border-radius:12px;background:#f0fffc;color:#334155;font-size:12px;line-height:1.45;text-align:left;white-space:normal';
      const title=document.createElement('strong');
      title.textContent='Clientes positivados (individual)';
      title.style.cssText='display:block;font-size:12px;font-weight:800';
      const value=document.createElement('span');
      value.textContent=displayMetric(metric);
      box.append(title,value);
      cell.appendChild(box);
    }
  }
  function decorateBoth(){decorate('vendedores','vendBody');decorate('televendas','tlvBody');}
  function init(){
    const original=window.renderSales;
    if(typeof original!=='function'||!lab()||!comp())return;
    window.renderSales=function(){
      const result=original.apply(this,arguments);
      decorateBoth();
      return result;
    };
    lab().addEventListener('change',decorateBoth);
    comp().addEventListener('change',decorateBoth);
    decorateBoth();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();
