/* DISMEPE ONE — identidade visual nos relatórios impressos/PDF. */
(function(){
  'use strict';
  if(window.__dismepePdfBrandingInstalled) return;
  window.__dismepePdfBrandingInstalled=true;

  const BRAND_ID='dismepe-one-pdf-brand';
  const STYLE_ID='dismepe-one-pdf-brand-style';

  function ensureStyle(doc){
    if(!doc || doc.getElementById(STYLE_ID)) return;
    const style=doc.createElement('style');
    style.id=STYLE_ID;
    style.textContent=`
      #${BRAND_ID}{display:none;align-items:center;gap:9px;padding:0 0 10px;margin:0 0 12px;border-bottom:1px solid #dbe7e2;color:#145c49;font-family:Arial,Helvetica,sans-serif}
      #${BRAND_ID} img{width:34px;height:34px;object-fit:contain;display:block}
      #${BRAND_ID} .dismepe-pdf-wordmark{font-weight:800;font-size:17px;letter-spacing:.45px;line-height:1}
      #${BRAND_ID} .dismepe-pdf-sub{font-weight:600;font-size:8px;letter-spacing:1.1px;color:#60756e;margin-top:4px}
      @media print{#${BRAND_ID}{display:flex !important;break-inside:avoid;page-break-inside:avoid}}
    `;
    (doc.head||doc.documentElement).appendChild(style);
  }

  function ensureBrand(doc){
    try{
      if(!doc || !doc.body) return;
      ensureStyle(doc);
      if(doc.getElementById(BRAND_ID)) return;
      const brand=doc.createElement('div');
      brand.id=BRAND_ID;
      brand.innerHTML='<img src="/dismepe-one-logo.png" alt="DISMEPE ONE"><div><div class="dismepe-pdf-wordmark">DISMEPE ONE</div><div class="dismepe-pdf-sub">RELATÓRIO OFICIAL</div></div>';
      doc.body.insertBefore(brand,doc.body.firstChild);
    }catch(_e){}
  }

  const nativePrint=window.print;
  if(typeof nativePrint==='function'){
    window.print=function(){ensureBrand(document);return nativePrint.apply(window,arguments);};
  }
  window.addEventListener('beforeprint',function(){ensureBrand(document);});

  const nativeOpen=window.open;
  if(typeof nativeOpen==='function'){
    window.open=function(){
      const child=nativeOpen.apply(window,arguments);
      if(!child) return child;
      try{
        const childPrint=child.print;
        if(typeof childPrint==='function'){
          child.print=function(){ensureBrand(child.document);return childPrint.apply(child,arguments);};
        }
        child.addEventListener('beforeprint',function(){ensureBrand(child.document);});
      }catch(_e){}
      return child;
    };
  }
})();
