(function(){
  'use strict';
  if(window.__dismepeProdutoFocoLabelsV1)return;
  window.__dismepeProdutoFocoLabelsV1=true;

  function titleLab(value){
    const raw=String(value||'').trim().replace(/\s+/g,' ');
    if(!raw)return '';
    return raw.toLocaleLowerCase('pt-BR').replace(/(^|[\s\-/])([a-zà-ÿ])/g,function(_,sep,ch){
      return sep+ch.toLocaleUpperCase('pt-BR');
    });
  }

  function baseLab(item){
    const source=String(item?.lab||item?.__LAB||'').trim();
    try{
      if(typeof window.getBaseLab==='function'){
        const normalized=window.getBaseLab(source);
        if(normalized)return titleLab(normalized);
      }
    }catch(_){}
    return titleLab(
      source
        .replace(/\s*[-–—]?\s*(?:PROD(?:UTO)?\.?\s*FOCO)(?:\s*\(\s*[^)]*\s*\))?.*$/i,'')
        .trim()
    );
  }

  function codeOf(item){
    const source=String(item?.lab||item?.__LAB||'');
    const match=source.match(/PROD(?:UTO)?\.?\s*FOCO\s*\(\s*(?:COD\.?\s*)?([^)]+?)\s*\)/i);
    if(match&&match[1])return String(match[1]).trim().replace(/^COD\.?\s*/i,'');
    const fallback=String(item?.__CODIGO_FOCO||item?.codigoFoco||item?.codigoProdutoFoco||'').trim();
    return fallback.replace(/^COD\.?\s*/i,'');
  }

  function standardized(item,isFocus){
    const lab=baseLab(item);
    if(!isFocus)return lab;
    const code=codeOf(item);
    return lab+' - Prod Foco'+(code?' (Cod '+code+')':'');
  }

  // Substitui somente a apresentação; não altera dados, metas, venda ou cálculo.
  window.formatLabFocusLabel=standardized;

  const css=document.createElement('style');
  css.id='produto-foco-compacto-v1';
  css.textContent=[
    '.lab-focus-label.lab-focus-highlight{',
    'display:inline-block!important;',
    'width:auto!important;',
    'max-width:100%!important;',
    'padding:3px 7px!important;',
    'border:1px solid #fed7aa!important;',
    'border-left:3px solid #f97316!important;',
    'border-radius:6px!important;',
    'background:#fff7ed!important;',
    'color:#c2410c!important;',
    'font-size:11px!important;',
    'font-weight:850!important;',
    'line-height:1.2!important;',
    'white-space:normal!important;',
    'overflow-wrap:anywhere!important;',
    '}',
    '#detailMobileCards .p598234-lab-value.p598234-focus{',
    'display:inline-block!important;',
    'width:auto!important;',
    'max-width:100%!important;',
    'padding:4px 7px!important;',
    'border-left:3px solid #f97316!important;',
    'border-radius:6px!important;',
    'font-size:10px!important;',
    'line-height:1.2!important;',
    '}',
    '@media(max-width:640px){',
    '.lab-focus-label.lab-focus-highlight{font-size:10px!important;padding:3px 6px!important;}',
    '#detailMobileCards .p598234-lab-value.p598234-focus{font-size:9.5px!important;padding:3px 6px!important;}',
    '}',
    '@media print{',
    '.lab-focus-label.lab-focus-highlight{font-size:9px!important;padding:2px 5px!important;}',
    '}'
  ].join('');
  document.head.appendChild(css);
})();