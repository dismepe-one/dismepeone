from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V13"


def install_commercial_intelligence_ui_v13() -> None:
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

    promo_anchor = '<section class="promo-toolbar" id="promoToolbar">'
    complement_bar = r'''
<section class="complement-toolbar" id="complementToolbar">
  <div class="complement-main">
    <div>
      <span class="promo-label">MAPA COMPLEMENTAR TEMPORÁRIO</span>
      <b id="complementStatus">Nenhum arquivo complementar carregado</b>
      <small id="complementMeta">Cruza pelo código do produto. Pc.Custo será usado como custo médio da promoção.</small>
    </div>
  </div>
  <div class="complement-actions">
    <input id="complementFile" type="file" accept=".pdf,.xlsx,.csv,application/pdf" hidden>
    <button type="button" id="complementUpload" class="promo-btn"><i class="fa-solid fa-file-arrow-up"></i> Importar mapa complementar</button>
    <button type="button" id="complementRemove" class="promo-btn danger-btn hidden"><i class="fa-solid fa-trash"></i> Remover complemento</button>
  </div>
</section>
'''
    if promo_anchor in text and 'id="complementToolbar"' not in text:
        text = text.replace(promo_anchor, complement_bar + promo_anchor, 1)

    old_cols = "['acao','Ação'],['preco','Custo'],['promoPrice','Preço promoção']"
    new_cols = "['acao','Ação'],['preco','Custo médio'],['lote','Lote'],['vencimento','Validade'],['quantidadeUltimaEntrada','Qtd. últ. entrada'],['promoPrice','Preço promoção']"
    if old_cols in text:
        text = text.replace(old_cols, new_cols, 1)

    cost_cell = '<td class="num"><b>${money(x.preco||0)}</b></td>'
    extra_cells = cost_cell + '<td>${esc(x.lote||\'—\')}</td><td>${esc(x.vencimento||\'—\')}</td><td class="num">${fmt(x.quantidadeUltimaEntrada||0)}</td>'
    if cost_cell in text and '<td>${esc(x.lote||\'—\')}</td>' not in text:
        text = text.replace(cost_cell, extra_cells, 1)

    detail_old = '<div class="detail-cell"><span>Lote / vencimento</span><b>${esc(x.lote||\'—\')} · ${esc(x.vencimento||\'—\')}</b></div>'
    detail_new = '<div class="detail-cell"><span>Lote</span><b>${esc(x.lote||\'—\')}</b></div><div class="detail-cell"><span>Validade</span><b>${esc(x.vencimento||\'—\')}</b></div><div class="detail-cell"><span>Qtd. última entrada</span><b>${fmt(x.quantidadeUltimaEntrada||0)}</b></div>'
    if detail_old in text:
        text = text.replace(detail_old, detail_new, 1)

    css_anchor = '</style>'
    css_patch = r'''
.complement-toolbar{background:#f8fbfa;border:1px dashed #b9d5cd;border-radius:14px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.complement-main>div{display:grid;gap:2px}.complement-main b{font-size:10px;color:#23473e}.complement-main small{font-size:8px;color:var(--mut)}.complement-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.complement-toolbar.loading{opacity:.65;pointer-events:none}
@media(max-width:650px){.complement-actions,.complement-actions .promo-btn{width:100%}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V13
(function(){
  const $=id=>document.getElementById(id);
  async function api(url,opts={}){
    const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...opts});
    let d={};
    try{d=await r.json()}catch(_){d={detail:`Falha HTTP ${r.status||0}`}}
    if(!r.ok)throw new Error(d.detail||`Falha HTTP ${r.status||0}`);
    return d;
  }
  function renderStatus(d){
    const status=$('complementStatus'),meta=$('complementMeta'),remove=$('complementRemove');
    if(!status||!meta)return;
    if(!d?.ativo){status.textContent='Nenhum arquivo complementar carregado';meta.textContent='Cruza pelo código. Aceita PDF, Excel e CSV. No PDF: Pc.Custo = custo médio, Qtd = última entrada e Venc. = validade.';remove?.classList.add('hidden');return;}
    status.textContent=d.arquivo||'Mapa complementar ativo';
    const when=d.enviadoEm?new Date(d.enviadoEm).toLocaleString('pt-BR'):'';
    meta.textContent=`${Number(d.codigos||0).toLocaleString('pt-BR')} códigos${when?' · enviado em '+when:''} · Pc.Custo usado no markup da promoção`;
    remove?.classList.remove('hidden');
  }
  async function loadStatus(){try{renderStatus(await api('/data/inteligencia-comercial/complemento'))}catch(e){console.error(e)}}
  function makeUploadId(){
    const a=new Uint32Array(4);crypto.getRandomValues(a);
    return `u${Date.now().toString(36)}_${Array.from(a).map(n=>n.toString(36)).join('')}`;
  }
  async function upload(file){
    if(!file)return;
    const bar=$('complementToolbar'),status=$('complementStatus'),meta=$('complementMeta');
    bar?.classList.add('loading');
    try{
      const max=12*1024*1024;if(file.size>max)throw new Error('O arquivo complementar deve ter no máximo 12 MB.');
      const chunkSize=512*1024,total=Math.ceil(file.size/chunkSize),uploadId=makeUploadId();
      for(let i=0;i<total;i++){
        status&&(status.textContent=`Enviando arquivo… ${i+1}/${total}`);
        meta&&(meta.textContent='O envio é feito em blocos para evitar falhas em redes móveis.');
        const chunk=file.slice(i*chunkSize,Math.min(file.size,(i+1)*chunkSize));
        await api('/data/inteligencia-comercial/complemento/upload-chunk',{
          method:'POST',
          headers:{'content-type':'application/octet-stream','x-upload-id':uploadId,'x-chunk-index':String(i),'x-chunk-total':String(total)},
          body:chunk
        });
      }
      status&&(status.textContent='Processando PDF…');
      meta&&(meta.textContent='Lendo Pc.Custo, Lote, Qtd e Venc. e cruzando pelo código do produto.');
      const d=await api('/data/inteligencia-comercial/complemento/upload-finalize',{
        method:'POST',
        headers:{'x-upload-id':uploadId,'x-file-name':encodeURIComponent(file.name)}
      });
      alert(`Mapa complementar importado com sucesso. ${Number(d.codigos||0).toLocaleString('pt-BR')} códigos reconhecidos.`);
      location.reload();
    }catch(e){
      alert(e?.message||'Falha ao importar o mapa complementar.');
      bar?.classList.remove('loading');loadStatus();
    }
  }
  function init(){
    $('complementUpload')?.addEventListener('click',()=>$('complementFile')?.click());
    $('complementFile')?.addEventListener('change',e=>{const f=e.target.files?.[0];e.target.value='';upload(f)});
    $('complementRemove')?.addEventListener('click',async()=>{
      if(!confirm('Deseja realmente remover o mapa complementar temporário? O Mapa principal não será alterado.'))return;
      try{await api('/data/inteligencia-comercial/complemento',{method:'DELETE'});location.reload()}catch(e){alert(e?.message||'Falha ao remover o complemento.')}
    });
    loadStatus();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v13.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
