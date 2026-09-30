/* DISMEPE ONE — mantém o layout original e troca apenas Objetivo/Realizado para unidades. */
(function(){
  'use strict';
  const TARGET='CE-20260930-154538-472167';
  const METRIC='RANKING_POSITIVACAO_PRODUTOS';
  if(window.__dismepeExtrasPdfUnitsInstalledV2) return;
  window.__dismepeExtrasPdfUnitsInstalledV2=true;

  function selectedCampaign(){
    return String(document.getElementById('extraCampaignSelect')?.value||'').trim();
  }

  function metricOf(row){
    return String(row?.metrica||row?.metric||'').trim().toUpperCase();
  }

  function isTargetRow(row){
    return selectedCampaign()===TARGET && metricOf(row)===METRIC;
  }

  function numberValue(value){
    const n=Number(value);
    return Number.isFinite(n)?Math.max(0,Math.round(n)):0;
  }

  function units(value){
    return numberValue(value).toLocaleString('pt-BR')+' un.';
  }

  function installScreenFormatters(){
    const originalObjective=window.extraPartialObjectiveText;
    const originalRealized=window.extraPartialRealizedText;
    if(typeof originalObjective!=='function' || typeof originalRealized!=='function') return false;
    if(originalObjective.__dismepeNatulabUnitsV2 && originalRealized.__dismepeNatulabUnitsV2) return true;

    const objective=function(row){
      if(isTargetRow(row)){
        return units(row?.objetivo ?? row?.meta ?? row?.objetivoClientes ?? 0);
      }
      return originalObjective.apply(this,arguments);
    };
    objective.__dismepeNatulabUnitsV2=true;

    const realized=function(row){
      if(isTargetRow(row)){
        return units(
          row?.clientesPositivadosValidos ??
          row?.realizado ??
          row?.venda ??
          0
        );
      }
      return originalRealized.apply(this,arguments);
    };
    realized.__dismepeNatulabUnitsV2=true;

    window.extraPartialObjectiveText=objective;
    window.extraPartialRealizedText=realized;

    try{
      if(selectedCampaign()===TARGET && typeof window.renderExtraRows==='function'){
        window.renderExtraRows();
      }
    }catch(_e){}
    return true;
  }

  function normalize(value){
    return String(value||'')
      .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
      .replace(/\s+/g,' ').trim().toUpperCase();
  }

  function parseNumber(value){
    let text=String(value||'').trim();
    if(!text) return NaN;
    text=text.replace(/[^0-9,.-]/g,'');
    if(!text) return NaN;
    if(text.includes(',')) text=text.replace(/\./g,'').replace(',','.');
    const number=Number(text);
    return Number.isFinite(number)?Math.max(0,Math.round(number)):NaN;
  }

  function rewriteTable(table){
    const headers=[...table.querySelectorAll('thead th')].map(th=>normalize(th.textContent));
    if(!headers.length){
      const first=table.querySelector('tr');
      if(first) headers.push(...[...first.children].map(cell=>normalize(cell.textContent)));
    }
    const objectiveIndex=headers.findIndex(text=>text.includes('OBJETIVO'));
    const realizedIndex=headers.findIndex(text=>text.includes('REALIZADO'));
    if(objectiveIndex<0 && realizedIndex<0) return false;

    const rows=[...table.querySelectorAll('tbody tr')];
    const effectiveRows=rows.length?rows:[...table.querySelectorAll('tr')].slice(1);
    effectiveRows.forEach(row=>{
      const cells=[...row.children].filter(cell=>/^(TD|TH)$/.test(cell.tagName));
      [objectiveIndex,realizedIndex].forEach(index=>{
        if(index<0 || !cells[index]) return;
        const current=String(cells[index].textContent||'').trim();
        if(!current || /\bun\.?$/i.test(current)) return;
        const number=parseNumber(current);
        if(Number.isFinite(number)) cells[index].textContent=units(number);
      });
    });
    return true;
  }

  function rewritePdfDocument(doc){
    if(selectedCampaign()!==TARGET || !doc) return;
    [...doc.querySelectorAll('table')].forEach(rewriteTable);
  }

  function wrapChildPrint(child){
    if(!child || child.__dismepeExtrasPdfUnitsPrintV2) return;
    child.__dismepeExtrasPdfUnitsPrintV2=true;
    try{
      const previousPrint=child.print;
      if(typeof previousPrint==='function'){
        child.print=function(){
          try{rewritePdfDocument(child.document);}catch(_e){}
          return previousPrint.apply(child,arguments);
        };
      }
      child.addEventListener('beforeprint',function(){
        try{rewritePdfDocument(child.document);}catch(_e){}
      });
    }catch(_e){}
  }

  function installPdfGuard(){
    const original=window.exportExtraCampaignPdf;
    if(typeof original!=='function') return false;
    if(original.__dismepeExtrasPdfUnitsV2) return true;

    const wrapped=async function(){
      if(selectedCampaign()!==TARGET) return original.apply(this,arguments);

      const previousOpen=window.open;
      window.open=function(){
        const child=previousOpen.apply(window,arguments);
        wrapChildPrint(child);
        return child;
      };
      try{
        return await original.apply(this,arguments);
      }finally{
        window.open=previousOpen;
      }
    };
    wrapped.__dismepeExtrasPdfUnitsV2=true;
    window.exportExtraCampaignPdf=wrapped;
    return true;
  }

  function installChangeGuard(){
    const select=document.getElementById('extraCampaignSelect');
    if(!select || select.__dismepeNatulabUnitsChangeV2) return;
    select.__dismepeNatulabUnitsChangeV2=true;
    select.addEventListener('change',function(){
      setTimeout(function(){
        installScreenFormatters();
        try{
          if(selectedCampaign()===TARGET && typeof window.renderExtraRows==='function') window.renderExtraRows();
        }catch(_e){}
      },0);
    });
  }

  let attempts=0;
  (function retry(){
    const screenOk=installScreenFormatters();
    const pdfOk=installPdfGuard();
    installChangeGuard();
    if((screenOk&&pdfOk) || attempts++>120) return;
    setTimeout(retry,100);
  })();
})();
