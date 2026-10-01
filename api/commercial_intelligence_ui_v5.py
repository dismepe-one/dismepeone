from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V5"


def install_commercial_intelligence_ui_v5() -> None:
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

    # Mantém a navegação existente internamente, mas deixa as abas invisíveis.
    text = text.replace(
        '<nav class="tabs" id="tabs"></nav>',
        '<nav class="tabs ci-tabs-hidden" id="tabs" aria-hidden="true"></nav>',
        1,
    )

    # Adiciona a visão como um filtro compacto no mesmo bloco dos demais filtros.
    curve_anchor = '<select id="curve"><option value="">Todas as curvas</option></select>'
    view_select = '''<select id="viewSelect" title="Selecionar visão da análise">
<option value="overview">Visão geral</option>
<option value="critical">Críticos</option>
<option value="rupture">Risco de ruptura</option>
<option value="low">Venda abaixo da média</option>
<option value="high">Venda acima do normal</option>
<option value="dde">DDE</option>
<option value="noTurn">Sem giro</option>
<option value="suppliers">Fornecedores</option>
</select>'''
    if curve_anchor in text and 'id="viewSelect"' not in text:
        text = text.replace(curve_anchor, view_select + curve_anchor, 1)

    # Estilo mais discreto para o seletor de visão.
    css_anchor = '</style>'
    css_patch = r'''
.ci-tabs-hidden{display:none!important}
#viewSelect{height:39px;border:1px solid var(--bd);border-radius:10px;padding:0 30px 0 10px;background:#f8fbfa;color:#35554d;font-weight:800;font-size:10px;min-width:158px}
#viewSelect:focus{outline:none;border-color:#079b72;box-shadow:0 0 0 3px rgba(7,155,114,.10)}
@media(max-width:650px){#viewSelect{width:100%;min-width:0}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    # Inclui o seletor nas referências do script atual.
    refs_old = "curve:document.getElementById('curve'),kpis:document.getElementById('kpis')"
    refs_new = "curve:document.getElementById('curve'),viewSelect:document.getElementById('viewSelect'),kpis:document.getElementById('kpis')"
    if refs_old in text:
        text = text.replace(refs_old, refs_new, 1)

    # Mantém o filtro sincronizado com a visão atual, inclusive em renderizações subsequentes.
    render_old = "function render(){E.tabs.innerHTML=tabDefs.map"
    render_new = "function render(){if(E.viewSelect)E.viewSelect.value=S.tab;E.tabs.innerHTML=tabDefs.map"
    if render_old in text:
        text = text.replace(render_old, render_new, 1)

    # O init do V4 já contém filtros múltiplos e exportações; acrescenta apenas a troca de visão.
    init_old = "function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}"
    init_new = "function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;render()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}"
    if init_old in text:
        text = text.replace(init_old, init_new, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v5.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
