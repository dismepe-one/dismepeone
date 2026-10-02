from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V9"


def install_commercial_intelligence_ui_v9() -> None:
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

    # Compatibilidade com a função init já expandida pelos filtros avançados.
    init_old = "function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);[E.ddeMin,E.ddeMax,E.stockMin,E.markupMin,E.markupMax].filter(Boolean).forEach(x=>x.addEventListener('input',applyFilter));[E.onlyBlocked,E.onlyExpiring].filter(Boolean).forEach(x=>x.addEventListener('change',applyFilter));E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;load()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}"
    init_new = r'''function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);[E.ddeMin,E.ddeMax,E.stockMin,E.markupMin,E.markupMax].filter(Boolean).forEach(x=>x.addEventListener('input',applyFilter));[E.onlyBlocked,E.onlyExpiring].filter(Boolean).forEach(x=>x.addEventListener('change',applyFilter));E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;if(S.tab==='promotion'){render();return}load()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{if(S.tab!=='overview')location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{if(S.tab!=='overview')location.href=exportUrl('pdf')});E.promoSelect?.addEventListener('change',()=>{P.active=E.promoSelect.value||null;renderPromoPanel()});E.promoNew?.addEventListener('click',async()=>{try{await createPromo()}catch(e){alert(e?.message||'Falha ao criar promoção.')}});E.promoOpen?.addEventListener('click',()=>{S.tab='promotion';if(E.viewSelect)E.viewSelect.value='promotion';render()});E.promoName?.addEventListener('change',()=>{const p=currentPromo();if(p){p.name=E.promoName.value.trim()||p.name;savePromo(p)}});E.promoDelete?.addEventListener('click',async()=>{const p=currentPromo();if(!p||!confirm('Excluir esta promoção?'))return;try{await promoApi('/data/inteligencia-comercial/promocoes/'+encodeURIComponent(p.id),{method:'DELETE'});P.list=P.list.filter(x=>x.id!==p.id);P.active=P.list[0]?.id||null;renderPromoSelect();renderPromoPanel()}catch(e){alert(e?.message||'Falha ao excluir promoção.')}});E.promoXlsx?.addEventListener('click',()=>{const p=currentPromo();if(!p)return;location.href='/data/inteligencia-comercial/promocoes/'+encodeURIComponent(p.id)+'/export.xlsx';setTimeout(loadPromos,1200)});E.promoPdf?.addEventListener('click',()=>{const p=currentPromo();if(!p)return;location.href='/data/inteligencia-comercial/promocoes/'+encodeURIComponent(p.id)+'/export.pdf';setTimeout(loadPromos,1200)});loadPromos();load()}'''
    if init_old in text:
        text = text.replace(init_old, init_new, 1)

    # O render atual recebeu guardas de exportação no V7; acrescenta o painel de
    # promoção sem depender da assinatura antiga usada pelo V8.
    render_old = "function render(){if(E.viewSelect)E.viewSelect.value=S.tab;if(E.exportXlsx)E.exportXlsx.disabled=S.tab==='overview';if(E.exportPdf)E.exportPdf.disabled=S.tab==='overview';if(E.exportXlsx)E.exportXlsx.title=S.tab==='overview'?'A exportação da Visão geral é bloqueada para proteger o desempenho':'';if(E.exportPdf)E.exportPdf.title=S.tab==='overview'?'A exportação da Visão geral é bloqueada para proteger o desempenho':'';"
    render_new = render_old + "renderPromoPanel();if(S.tab==='promotion'){E.title.textContent='Montar promoção';E.desc.textContent='Monte e exporte promoções diretamente a partir da Inteligência Comercial.';E.count.textContent=((currentPromo()?.items||[]).length).toLocaleString('pt-BR')+' produtos';E.content.innerHTML='<div class=\"empty\">Use as demais visões para localizar produtos, informar o preço promocional e pressionar Enter. A promoção ativa permanece salva no servidor.</div>';return}"
    if render_old in text and "Monte e exporte promoções diretamente" not in text:
        text = text.replace(render_old, render_new, 1)

    # Garante ligação dos inputs de preço após cada renderização da tabela.
    table_line = "E.content.innerHTML=all.length?table(shown,all.length):'<div class=\"empty\">Nenhum produto neste recorte.</div>';"
    if table_line in text and table_line + "wirePriceEntries();" not in text:
        text = text.replace(table_line, table_line + "wirePriceEntries();", 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v9.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
