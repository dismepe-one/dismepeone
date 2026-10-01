from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V7"


def install_commercial_intelligence_ui_v7() -> None:
    from . import commercial_intelligence as ci

    page = getattr(ci, "PAGE_FILE", None)
    if not isinstance(page, Path):
        return
    try:
        text = page.read_text(encoding="utf-8")
    except Exception:
        return
    if _MARKER in text:
        # Mesmo quando o V7 já estiver aplicado ao arquivo temporário, garante
        # que o patch seguinte de promoção seja executado nesta instância.
        from .commercial_intelligence_ui_v8 import install_commercial_intelligence_ui_v8
        install_commercial_intelligence_ui_v8()
        return

    # A API passa a receber explicitamente a visão solicitada.
    text = text.replace(
        "fetch('/data/inteligencia-comercial?ts='+Date.now(),{credentials:'same-origin',cache:'no-store'})",
        "fetch('/data/inteligencia-comercial?visao='+encodeURIComponent(S.tab)+'&ts='+Date.now(),{credentials:'same-origin',cache:'no-store'})",
        1,
    )

    # Segurança para respostas sem listagem (Visão geral / Fornecedores).
    text = text.replace(
        "S.data=data;S.all=data.produtos;S.filtered=S.all.slice();",
        "S.data=data;S.all=Array.isArray(data.produtos)?data.produtos:[];S.filtered=S.all.slice();",
        1,
    )

    # Os filtros estruturais continuam disponíveis na Visão geral usando
    # agregados, sem depender da lista completa de produtos.
    old_build = "function buildFilters(){const su=[...new Set(S.all.map(x=>x.fornecedor).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'));E.supplier.innerHTML=su.map(x=>`<option value=\"${esc(x)}\">${esc(x)}</option>`).join('');renderSupplierOptions();syncSupplierLabel();const cu=[...new Set(S.all.map(x=>x.curva).filter(Boolean))].sort();E.curve.innerHTML='<option value=\"\">Todas as curvas</option>'+cu.map(x=>`<option value=\"${esc(x)}\">${esc(x)}</option>`).join('')}"
    new_build = "function buildFilters(){const supplierSource=S.all.length?S.all.map(x=>x.fornecedor):((S.data?.fornecedores||[]).map(x=>x.fornecedor));const su=[...new Set(supplierSource.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'));const selected=new Set(selectedSuppliers());E.supplier.innerHTML=su.map(x=>`<option value=\"${esc(x)}\" ${selected.has(x)?'selected':''}>${esc(x)}</option>`).join('');renderSupplierOptions();syncSupplierLabel();const cu=S.all.length?[...new Set(S.all.map(x=>x.curva).filter(Boolean))]:Array.from(S.data?.curvasDisponiveis||[]);const curveValue=E.curve.value;E.curve.innerHTML='<option value=\"\">Todas as curvas</option>'+cu.map(x=>`<option value=\"${esc(x)}\">${esc(x)}</option>`).join('');if(cu.includes(curveValue))E.curve.value=curveValue}"
    if old_build in text:
        text = text.replace(old_build, new_build, 1)

    # Trocar a visão faz uma nova requisição, em vez de filtrar a lista completa
    # já carregada no navegador.
    text = text.replace(
        "E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;render()});",
        "E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;load()});",
        1,
    )

    # A Visão geral não renderiza tabela nem botão de 'Mostrar mais'.
    supplier_branch = "if(S.tab==='suppliers'){"
    overview_branch = "if(S.tab==='overview'){E.count.textContent=(S.data?.totalProdutosBase||S.data?.resumo?.produtos||0).toLocaleString('pt-BR')+' produtos na base';E.content.innerHTML='<div class=\"empty\"><b>Visão geral protegida.</b><br>Os produtos não são carregados nesta visão. Selecione uma visão específica para consultar a listagem detalhada.</div>';return}if(S.tab==='suppliers'){"
    if supplier_branch in text:
        text = text.replace(supplier_branch, overview_branch, 1)

    # Desabilita exportações na Visão geral; o backend também bloqueia.
    render_start = "function render(){if(E.viewSelect)E.viewSelect.value=S.tab;"
    render_guard = "function render(){if(E.viewSelect)E.viewSelect.value=S.tab;if(E.exportXlsx)E.exportXlsx.disabled=S.tab==='overview';if(E.exportPdf)E.exportPdf.disabled=S.tab==='overview';if(E.exportXlsx)E.exportXlsx.title=S.tab==='overview'?'Selecione uma visão específica para exportar':'';if(E.exportPdf)E.exportPdf.title=S.tab==='overview'?'Selecione uma visão específica para exportar':'';"
    if render_start in text:
        text = text.replace(render_start, render_guard, 1)

    # Estilo visual de controles desabilitados.
    css_anchor = '</style>'
    css_patch = r'''
.export-btn:disabled{opacity:.4;cursor:not-allowed;background:#f2f5f4;color:#879691}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v7.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        return

    from .commercial_intelligence_ui_v8 import install_commercial_intelligence_ui_v8
    install_commercial_intelligence_ui_v8()
