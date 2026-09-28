(function(){
  'use strict';
  if(window.__dismepeProdutoFocoLabelsV2)return;
  window.__dismepeProdutoFocoLabelsV2=true;

  const sortState={key:'lab',dir:'asc'};
  const SORTS=[
    ['colab','Colaborador','text'],
    ['lab','Laboratório','text'],
    ['objetivo','Objetivo','number'],
    ['venda','Venda','number'],
    ['dia','Vender por dia','number'],
    ['atingimento','Atingimento','number'],
    ['status','Status','text']
  ];

  function upperLab(value){
    return String(value||'').trim().replace(/\s+/g,' ').toLocaleUpperCase('pt-BR');
  }

  function baseLab(item){
    const source=String(item?.lab||item?.__LAB||'').trim();
    try{
      if(typeof window.getBaseLab==='function'){
        const normalized=window.getBaseLab(source);
        if(normalized)return upperLab(normalized);
      }
    }catch(_){}
    return upperLab(
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

  function isFocus(item){
    try{
      if(typeof window.isFoco==='function')return !!window.isFoco(item);
    }catch(_){}
    return /PROD(?:UTO)?\.?\s*FOCO/i.test(String(item?.lab||item?.__LAB||''));
  }

  function standardized(item,isItemFocus){
    const lab=baseLab(item);
    if(!isItemFocus)return lab;
    const code=codeOf(item);
    return lab+' - Prod Foco'+(code?' (Cod '+code+')':'');
  }

  // Somente apresentação: não altera meta, venda, produto foco ou cálculo.
  window.formatLabFocusLabel=standardized;

  function normalizeText(value){
    return String(value||'').trim().replace(/\s+/g,' ').toLocaleUpperCase('pt-BR');
  }

  function numericText(value){
    let raw=String(value??'').trim();
    if(!raw||raw==='—')return 0;
    raw=raw.replace(/R\$|%|un\.?/gi,'').replace(/\s/g,'');
    if(raw.includes('.')&&raw.includes(','))raw=raw.replace(/\./g,'').replace(',','.');
    else if(raw.includes(','))raw=raw.replace(',','.');
    raw=raw.replace(/[^0-9.+-]/g,'');
    const number=Number(raw);
    return Number.isFinite(number)?number:0;
  }

  function datasetSortValue(item,key){
    if(key==='colab')return normalizeText(item?.colab);
    if(key==='lab')return baseLab(item);
    if(key==='objetivo')return Number(item?.objetivo||0);
    if(key==='venda')return Number(item?.venda||0);
    if(key==='atingimento')return Number(item?.percentual||0)*100;
    if(key==='status'){
      const p=Number(item?.percentual||0)*100;
      return p>=100?'META ATINGIDA':p>=50?'EM PROGRESSO':'ABAIXO DA META';
    }
    if(key==='dia'){
      try{
        if(typeof window.venderPorDia==='function'){
          return numericText(window.venderPorDia(item?.objetivo,item?.venda,false));
        }
      }catch(_){}
      return Math.max(0,Number(item?.objetivo||0)-Number(item?.venda||0));
    }
    return '';
  }

  function compareValues(a,b,type){
    if(type==='number')return Number(a||0)-Number(b||0);
    return String(a||'').localeCompare(String(b||''),'pt-BR',{sensitivity:'base',numeric:true});
  }

  function sortType(key){
    return SORTS.find(x=>x[0]===key)?.[2]||'text';
  }

  function sortDataset(data){
    if(!Array.isArray(data)||data.length<2)return Array.isArray(data)?[...data]:[];
    const groups=new Map();
    data.forEach((item,index)=>{
      const lab=baseLab(item);
      const colab=normalizeText(item?.colab);
      const groupKey=colab+'||'+lab;
      if(!groups.has(groupKey))groups.set(groupKey,{lab,colab,main:[],focus:[],index});
      const group=groups.get(groupKey);
      (isFocus(item)?group.focus:group.main).push(item);
    });

    const list=[...groups.values()];
    const type=sortType(sortState.key);
    list.sort((a,b)=>{
      const itemA=a.main[0]||a.focus[0]||{};
      const itemB=b.main[0]||b.focus[0]||{};
      let result=compareValues(
        datasetSortValue(itemA,sortState.key),
        datasetSortValue(itemB,sortState.key),
        type
      );
      if(result===0)result=a.lab.localeCompare(b.lab,'pt-BR',{sensitivity:'base',numeric:true});
      if(result===0)result=a.colab.localeCompare(b.colab,'pt-BR',{sensitivity:'base',numeric:true});
      if(result===0)result=a.index-b.index;
      return sortState.dir==='desc'?-result:result;
    });

    return list.flatMap(group=>{
      const focus=[...group.focus].sort((a,b)=>
        String(codeOf(a)).localeCompare(String(codeOf(b)),'pt-BR',{numeric:true,sensitivity:'base'})
      );
      return [...group.main,...focus];
    });
  }

  function baseLabFromRenderedLabel(text){
    return normalizeText(
      String(text||'').replace(/\s*-\s*PROD\s*FOCO(?:\s*\(\s*COD\s*[^)]*\))?.*$/i,'')
    );
  }

  function renderedRowValue(row,key){
    const cells=row.cells||[];
    if(key==='colab')return normalizeText(row.querySelector('.detail-colaborador-name')?.textContent||cells[0]?.textContent);
    if(key==='lab')return baseLabFromRenderedLabel(row.querySelector('.lab-focus-label')?.textContent||cells[1]?.textContent);
    if(key==='objetivo')return numericText(cells[2]?.textContent);
    if(key==='venda')return numericText(cells[3]?.textContent);
    if(key==='dia')return numericText(cells[4]?.textContent);
    if(key==='atingimento')return numericText(cells[5]?.textContent);
    if(key==='status')return normalizeText(cells[6]?.textContent);
    return '';
  }

  function reorderTableRows(){
    const body=document.getElementById('tableBody');
    if(!body)return;
    const rows=[...body.querySelectorAll('tr')].filter(row=>row.querySelector('.detail-colaborador-name'));
    if(rows.length<2)return;

    const groups=new Map();
    rows.forEach((row,index)=>{
      const colab=normalizeText(row.querySelector('.detail-colaborador-name')?.textContent);
      const label=row.querySelector('.lab-focus-label');
      const lab=baseLabFromRenderedLabel(label?.textContent);
      const key=colab+'||'+lab;
      if(!groups.has(key))groups.set(key,{colab,lab,main:[],focus:[],index});
      const group=groups.get(key);
      const focus=!!label?.classList.contains('lab-focus-highlight');
      row.classList.toggle('produto-foco-subrow',focus);
      (focus?group.focus:group.main).push(row);
    });

    const type=sortType(sortState.key);
    const list=[...groups.values()].sort((a,b)=>{
      const rowA=a.main[0]||a.focus[0];
      const rowB=b.main[0]||b.focus[0];
      let result=compareValues(
        renderedRowValue(rowA,sortState.key),
        renderedRowValue(rowB,sortState.key),
        type
      );
      if(result===0)result=a.lab.localeCompare(b.lab,'pt-BR',{sensitivity:'base',numeric:true});
      if(result===0)result=a.colab.localeCompare(b.colab,'pt-BR',{sensitivity:'base',numeric:true});
      if(result===0)result=a.index-b.index;
      return sortState.dir==='desc'?-result:result;
    });

    const fragment=document.createDocumentFragment();
    list.forEach(group=>{
      group.main.forEach(row=>fragment.appendChild(row));
      group.focus.sort((a,b)=>{
        const aa=a.querySelector('.lab-focus-label')?.textContent||'';
        const bb=b.querySelector('.lab-focus-label')?.textContent||'';
        return aa.localeCompare(bb,'pt-BR',{numeric:true,sensitivity:'base'});
      }).forEach(row=>fragment.appendChild(row));
    });
    body.appendChild(fragment);
  }

  function iconFor(key){
    if(sortState.key!==key)return '↕';
    return sortState.dir==='asc'?'↑':'↓';
  }

  function updateSortIndicators(){
    const headers=document.querySelectorAll('#detailTableScroll thead th[data-partial-sort]');
    headers.forEach(th=>{
      const key=th.dataset.partialSort;
      const icon=th.querySelector('.partial-sort-icon');
      if(icon)icon.textContent=iconFor(key);
      th.setAttribute('aria-sort',sortState.key===key?(sortState.dir==='asc'?'ascending':'descending'):'none');
    });
    const mobile=document.getElementById('partialSortDirection');
    if(mobile)mobile.textContent=sortState.dir==='asc'?'↑':'↓';
    const select=document.getElementById('partialSortField');
    if(select)select.value=sortState.key;
  }

  function applySort(key,forceDirection){
    if(!SORTS.some(x=>x[0]===key))return;
    if(forceDirection){
      sortState.key=key;
      sortState.dir=forceDirection;
    }else if(sortState.key===key){
      sortState.dir=sortState.dir==='asc'?'desc':'asc';
    }else{
      sortState.key=key;
      sortState.dir='asc';
    }
    updateSortIndicators();
    if(typeof window.updateDashboard==='function')window.updateDashboard();
  }

  function installHeaders(){
    const headers=[...document.querySelectorAll('#detailTableScroll thead th')];
    if(headers.length!==SORTS.length)return;
    headers.forEach((th,index)=>{
      const [key,label,type]=SORTS[index];
      if(th.dataset.partialSort)return;
      th.dataset.partialSort=key;
      th.setAttribute('role','columnheader');
      th.setAttribute('aria-sort','none');
      th.innerHTML=
        '<button type="button" class="partial-sort-button '+(type==='number'?'partial-sort-number':'')+'" '+
        'title="Clique para alternar a ordenação">'+
        '<span>'+label+'</span><span class="partial-sort-icon" aria-hidden="true">'+iconFor(key)+'</span>'+
        '</button>';
      th.querySelector('button')?.addEventListener('click',()=>applySort(key));
    });
    updateSortIndicators();
  }

  function installMobileSort(){
    if(document.getElementById('partialSortMobile'))return;
    const table=document.getElementById('detailTableScroll');
    if(!table)return;
    const bar=document.createElement('div');
    bar.id='partialSortMobile';
    bar.innerHTML=
      '<label for="partialSortField">Ordenar parcial</label>'+
      '<select id="partialSortField" aria-label="Campo para ordenar a parcial">'+
      SORTS.map(([key,label])=>'<option value="'+key+'">'+label+'</option>').join('')+
      '</select>'+
      '<button id="partialSortDirection" type="button" aria-label="Alternar ordem">↑</button>';
    table.parentNode.insertBefore(bar,table);
    const select=bar.querySelector('#partialSortField');
    const direction=bar.querySelector('#partialSortDirection');
    select.value=sortState.key;
    select.addEventListener('change',()=>applySort(select.value,'asc'));
    direction.addEventListener('click',()=>applySort(sortState.key));
  }

  function uppercaseLabOptions(){
    ['filterLab','overviewFilterLab'].forEach(id=>{
      const select=document.getElementById(id);
      if(!select)return;
      [...select.options].forEach(option=>{
        if(String(option.value||'').toUpperCase()==='ALL')return;
        option.textContent=upperLab(option.textContent);
      });
    });
  }

  function afterRender(){
    installHeaders();
    installMobileSort();
    uppercaseLabOptions();
    reorderTableRows();
    updateSortIndicators();
  }

  function wrapRenderers(){
    if(typeof window.prod598234RenderMobileCards==='function'&&!window.prod598234RenderMobileCards.__focusSortV2){
      const originalMobile=window.prod598234RenderMobileCards;
      const wrappedMobile=function(data){
        return originalMobile.call(this,sortDataset(data));
      };
      wrappedMobile.__focusSortV2=true;
      window.prod598234RenderMobileCards=wrappedMobile;
    }

    if(typeof window.updateDashboard==='function'&&!window.updateDashboard.__focusSortV2){
      const originalDashboard=window.updateDashboard;
      const wrappedDashboard=function(){
        const result=originalDashboard.apply(this,arguments);
        afterRender();
        return result;
      };
      wrappedDashboard.__focusSortV2=true;
      window.updateDashboard=wrappedDashboard;
    }
  }

  const css=document.createElement('style');
  css.id='produto-foco-compacto-v2';
  css.textContent=[
    '.lab-focus-label.lab-focus-highlight{display:inline-block!important;width:auto!important;max-width:100%!important;padding:3px 7px!important;border:1px solid #fed7aa!important;border-left:3px solid #f97316!important;border-radius:6px!important;background:#fff7ed!important;color:#c2410c!important;font-size:11px!important;font-weight:850!important;line-height:1.2!important;white-space:normal!important;overflow-wrap:anywhere!important;}',
    '#detailMobileCards .p598234-lab-value{ text-transform:uppercase!important;}',
    '#detailMobileCards .p598234-lab-value.p598234-focus{display:inline-block!important;width:auto!important;max-width:100%!important;padding:4px 7px!important;border-left:3px solid #f97316!important;border-radius:6px!important;font-size:10px!important;line-height:1.2!important;text-transform:none!important;}',
    '#detailTableScroll tr.produto-foco-subrow td:nth-child(2){padding-left:22px!important;}',
    '#detailTableScroll tr.produto-foco-subrow td:nth-child(2)::after{content:"";}',
    '.partial-sort-button{display:inline-flex;width:100%;align-items:center;gap:5px;border:0;background:transparent;color:inherit;font:inherit;font-weight:inherit;text-transform:inherit;letter-spacing:inherit;padding:0;cursor:pointer;}',
    '.partial-sort-number{justify-content:flex-end;}',
    '.partial-sort-icon{display:inline-flex;align-items:center;justify-content:center;min-width:14px;color:#005548;font-size:12px;font-weight:950;line-height:1;}',
    '#partialSortMobile{display:none;}',
    '@media(max-width:768px){',
    '.lab-focus-label.lab-focus-highlight{font-size:10px!important;padding:3px 6px!important;}',
    '#detailMobileCards .p598234-lab-value.p598234-focus{font-size:9.5px!important;padding:3px 6px!important;}',
    '#partialSortMobile{display:flex!important;align-items:center;gap:7px;margin:0 0 10px;padding:8px 9px;border:1px solid #dce9e5;border-radius:10px;background:#fff;}',
    '#partialSortMobile label{font-size:9px;font-weight:900;text-transform:uppercase;color:#60746f;white-space:nowrap;}',
    '#partialSortMobile select{min-width:0;flex:1;border:1px solid #cfded8;border-radius:8px;background:#fff;color:#17332c;padding:7px 8px;font-size:11px;font-weight:700;}',
    '#partialSortDirection{width:34px;height:34px;border:1px solid #bfd6ce;border-radius:8px;background:#e9f4ef;color:#005548;font-size:17px;font-weight:950;}',
    '}',
    '@media print{.lab-focus-label.lab-focus-highlight{font-size:9px!important;padding:2px 5px!important;}.partial-sort-icon,#partialSortMobile{display:none!important;}}'
  ].join('');
  document.head.appendChild(css);

  wrapRenderers();
  afterRender();
  window.addEventListener('load',()=>{
    wrapRenderers();
    afterRender();
  });
  [250,1000,2500].forEach(ms=>setTimeout(()=>{wrapRenderers();afterRender();},ms));
})();