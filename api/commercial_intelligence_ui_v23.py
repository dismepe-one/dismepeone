from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V23"


def install_commercial_intelligence_ui_v23() -> None:
    from . import commercial_intelligence as ci

    page = getattr(ci, "PAGE_FILE", None)
    if not isinstance(page, Path):
        return
    try:
        text = page.read_text(encoding="utf-8")
    except Exception:
        return
    if _MARKER in text:
        return

    # Guarda a validade junto do item da promoção para que os relatórios possam
    # sinalizar produtos próximos do vencimento sem depender do estado da tela.
    old_add = "if(!item){item={codigo:product.codigo,produto:product.produto||'',fornecedor:product.fornecedor||'',custo:Number(product.preco||0),precoPromocional:price};items.push(item)}else{item.precoPromocional=price;item.custo=Number(product.preco||item.custo||0)}"
    new_add = "if(!item){item={codigo:product.codigo,produto:product.produto||'',fornecedor:product.fornecedor||'',custo:Number(product.preco||0),precoPromocional:price,vencimento:String(product.vencimento||product.validade||''),vencimentoProximo:!!product.vencimentoProximo};items.push(item)}else{item.precoPromocional=price;item.custo=Number(product.preco||item.custo||0);item.vencimento=String(product.vencimento||product.validade||item.vencimento||'');item.vencimentoProximo=!!product.vencimentoProximo}"
    if old_add in text:
        text = text.replace(old_add, new_add, 1)

    # Depois de salvar com Enter, mantém o preço no campo em vez de limpá-lo.
    old_wire = "function wirePriceEntries(){E.content?.querySelectorAll('.price-entry').forEach(inp=>{inp.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();const price=parsePrice(inp.value);if(price<=0){inp.focus();return}const product=S.all.find(x=>String(x.codigo)===String(inp.dataset.code));if(!product)return;await addToPromo(product,price);inp.value='';inp.placeholder='Adicionado';setTimeout(()=>inp.placeholder='R$ 0,00',1200)})})}"
    new_wire = r'''function wirePriceEntries(){E.content?.querySelectorAll('.price-entry').forEach(inp=>{inp.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();const price=parsePrice(inp.value);if(price<=0){inp.focus();return}const product=S.all.find(x=>String(x.codigo)===String(inp.dataset.code));if(!product)return;await addToPromo(product,price);inp.value=Number(price).toFixed(2).replace('.',',');inp.dispatchEvent(new Event('input',{bubbles:true}));inp.placeholder='Salvo';setTimeout(()=>inp.placeholder='R$ 0,00',1200)})})}'''
    if old_wire in text:
        text = text.replace(old_wire, new_wire, 1)

    runtime = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_PROMO_PERSIST_V23
(function(){
  'use strict';
  const ACTIVE_KEY='dismepe_ci_active_promo';

  function promoList(){
    try{return (typeof P!=='undefined'&&Array.isArray(P.list))?P.list:[]}catch(_){return []}
  }
  function activeId(){
    try{if(typeof P!=='undefined'&&P.active)return String(P.active)}catch(_){}
    const select=document.getElementById('promoSelect');
    return String(select?.value||'');
  }
  function activePromo(){
    const id=activeId();
    return promoList().find(p=>String(p?.id||'')===id)||null;
  }
  function savedItem(code){
    const promo=activePromo();
    if(!promo)return null;
    const items=Array.isArray(promo.items)?promo.items:[];
    return items.find(item=>String(item?.codigo||'')===String(code))||null;
  }
  function formatPrice(value){return Number(value||0).toFixed(2).replace('.',',')}

  function restorePrices(force){
    const promo=activePromo();
    if(!promo)return;
    const promoId=String(promo.id||'');
    document.querySelectorAll('.price-entry').forEach(inp=>{
      if(!force&&document.activeElement===inp)return;
      const item=savedItem(inp.dataset.code||'');
      const saved=Number(item?.precoPromocional||0);
      const signature=promoId+'|'+(saved>0?String(saved):'0');
      if(!force&&inp.dataset.promoRestoreSignature===signature)return;
      inp.value=saved>0?formatPrice(saved):'';
      inp.dataset.promoRestoreSignature=signature;
      inp.dispatchEvent(new Event('input',{bubbles:true}));
    });
  }

  function restoreSelectedPromo(){
    const select=document.getElementById('promoSelect');
    const list=promoList();
    if(!select||!list.length)return false;
    let saved='';
    try{saved=localStorage.getItem(ACTIVE_KEY)||''}catch(_){}
    if(saved&&list.some(p=>String(p?.id||'')===saved)){
      try{if(typeof P!=='undefined')P.active=saved}catch(_){}
      if(select.value!==saved)select.value=saved;
      try{if(typeof renderPromoPanel==='function')renderPromoPanel()}catch(_){}
    }
    restorePrices(true);
    return true;
  }

  function start(){
    const select=document.getElementById('promoSelect');
    if(select){
      select.addEventListener('change',function(){
        try{localStorage.setItem(ACTIVE_KEY,String(select.value||''))}catch(_){}
        setTimeout(()=>restorePrices(true),0);
      });
    }

    const root=document.getElementById('ciProductsView')||document.getElementById('content')||document.body;
    if(root&&typeof MutationObserver!=='undefined'){
      new MutationObserver(function(){requestAnimationFrame(()=>restorePrices(false))}).observe(root,{childList:true,subtree:true});
    }

    [100,300,700,1200,2200].forEach(ms=>setTimeout(()=>{
      restoreSelectedPromo();
      restorePrices(false);
    },ms));
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
</script>
'''

    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + runtime + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v23.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
