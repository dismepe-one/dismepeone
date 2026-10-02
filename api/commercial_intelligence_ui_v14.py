from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V14"


def install_commercial_intelligence_ui_v14() -> None:
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

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V14
(function(){
  function detailFrom(xhr){
    try{
      const data=JSON.parse(xhr.responseText||'{}');
      return data.detail||data.message||'';
    }catch(_){return ''}
  }
  function uploadXHR(file){
    const bar=document.getElementById('complementToolbar');
    const meta=document.getElementById('complementMeta');
    if(!file)return;
    if(file.size>12*1024*1024){alert('O arquivo complementar deve ter no máximo 12 MB.');return;}
    bar?.classList.add('loading');
    if(meta)meta.textContent='Enviando mapa complementar...';

    const xhr=new XMLHttpRequest();
    xhr.open('POST','/data/inteligencia-comercial/complemento/upload',true);
    xhr.withCredentials=true;
    xhr.timeout=120000;
    xhr.setRequestHeader('Content-Type','application/octet-stream');
    xhr.setRequestHeader('X-File-Name',encodeURIComponent(file.name));
    xhr.upload.onprogress=function(ev){
      if(!meta||!ev.lengthComputable)return;
      const p=Math.max(1,Math.min(99,Math.round((ev.loaded/ev.total)*100)));
      meta.textContent=`Enviando mapa complementar... ${p}%`;
    };
    xhr.onreadystatechange=function(){
      if(xhr.readyState!==4)return;
      bar?.classList.remove('loading');
      if(xhr.status>=200&&xhr.status<300){
        let data={};
        try{data=JSON.parse(xhr.responseText||'{}')}catch(_){}
        alert(`Mapa complementar importado com sucesso. ${Number(data.codigos||0).toLocaleString('pt-BR')} códigos reconhecidos.`);
        location.reload();
        return;
      }
      const detail=detailFrom(xhr);
      alert(detail||`Falha no mapa complementar (HTTP ${xhr.status||0}).`);
      if(meta)meta.textContent=detail||`Falha no envio (HTTP ${xhr.status||0}).`;
    };
    xhr.onerror=function(){
      bar?.classList.remove('loading');
      alert('Falha de comunicação ao enviar o mapa complementar.');
      if(meta)meta.textContent='Falha de comunicação no upload.';
    };
    xhr.ontimeout=function(){
      bar?.classList.remove('loading');
      alert('O processamento do mapa complementar excedeu 120 segundos.');
      if(meta)meta.textContent='Tempo excedido no processamento.';
    };
    xhr.send(file);
  }

  function bind(){
    const input=document.getElementById('complementFile');
    if(!input||input.dataset.xhrUploadBound==='1')return;
    input.dataset.xhrUploadBound='1';
    input.addEventListener('change',function(ev){
      ev.preventDefault();
      ev.stopImmediatePropagation();
      const file=ev.target.files&&ev.target.files[0];
      uploadXHR(file);
    },true);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
</script>
'''

    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n<!-- " + _MARKER + " -->\n" + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v14.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
