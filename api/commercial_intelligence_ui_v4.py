from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V4"


def install_commercial_intelligence_ui_v4() -> None:
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

    # Cabeçalho padrão com logo DISMEPE ONE do portal de Indústrias.
    old_header = '<header><div class="top"><div class="brand">DISMEPE ONE<small>INTELIGÊNCIA COMERCIAL</small></div><button class="back" onclick="location.href=\'/\'"><i class="fa-solid fa-arrow-left"></i> Voltar</button></div></header>'
    new_header = '<header><div class="top"><div class="brand"><img id="dismepeOneLogo" alt="DISMEPE ONE"><div><strong>Inteligência Comercial</strong><small>MAPA DE ESTOQUE</small></div></div><button class="back" onclick="location.href=\'/\'"><i class="fa-solid fa-arrow-left"></i> Voltar</button></div></header>'
    if old_header in text:
        text = text.replace(old_header, new_header, 1)

    # Filtro fornecedor vira seletor múltiplo customizado.
    old_filter = '<div class="filters"><input id="search" placeholder="Buscar produto, código ou fornecedor"><select id="supplier"><option value="">Todos os fornecedores</option></select><select id="curve"><option value="">Todas as curvas</option></select></div>'
    new_filter = '''<div class="filters"><input id="search" placeholder="Buscar produto, código ou fornecedor"><div class="multi" id="supplierMulti"><button type="button" id="supplierBtn" class="multi-btn">Todos os fornecedores <i class="fa-solid fa-chevron-down"></i></button><div id="supplierMenu" class="multi-menu hidden"><div class="multi-actions"><button type="button" id="supplierAll">Todos</button><button type="button" id="supplierClear">Limpar</button></div><input id="supplierSearch" placeholder="Buscar fornecedor"><div id="supplierOptions" class="multi-options"></div></div></div><select id="supplier" multiple class="hidden" aria-hidden="true"></select><select id="curve"><option value="">Todas as curvas</option></select><button type="button" class="export-btn" id="exportXlsx"><i class="fa-solid fa-file-excel"></i> Excel</button><button type="button" class="export-btn" id="exportPdf"><i class="fa-solid fa-file-pdf"></i> PDF</button></div>'''
    if old_filter in text:
        text = text.replace(old_filter, new_filter, 1)

    # Remove o texto técnico solicitado, deixando somente um subtítulo curto.
    text = text.replace('<p id="subtitle">Carregando leitura completa do mapa...</p>', '<p id="subtitle">Análise comercial baseada no Mapa de Estoque.</p>', 1)
    text = text.replace("E.subtitle.textContent='Carregando leitura completa do mapa...';", "E.subtitle.textContent='Análise comercial baseada no Mapa de Estoque.';", 1)
    long_sub = "E.subtitle.textContent=`Leitura completa: ${S.all.length.toLocaleString('pt-BR')} produtos. ${data.criterioTendencia||''} Fonte atualizada em ${data.atualizadoEm||'—'}.`;"
    if long_sub in text:
        text = text.replace(long_sub, "E.subtitle.textContent='Análise comercial baseada no Mapa de Estoque.';", 1)

    # Estilos adicionais.
    css_anchor = '</style>'
    css_patch = r'''
.brand{display:flex;align-items:center;gap:12px}.brand img{width:184px;height:60px;object-fit:contain;object-position:left center}.brand strong{display:block;color:var(--g);font-size:14px}.brand small{display:block;font-size:8px;letter-spacing:.14em;color:#60746f;margin-top:2px}.multi{position:relative}.multi-btn,.export-btn{height:39px;border:1px solid var(--bd);border-radius:10px;padding:0 11px;background:#fff;color:var(--tx);font-weight:800;font-size:10px}.multi-btn{min-width:190px;display:flex;align-items:center;justify-content:space-between;gap:8px}.export-btn{color:var(--g)}.multi-menu{position:absolute;top:44px;left:0;z-index:60;width:min(340px,85vw);background:#fff;border:1px solid var(--bd);border-radius:12px;box-shadow:0 14px 34px rgba(0,63,54,.16);padding:9px}.multi-menu.hidden{display:none}.multi-actions{display:flex;gap:6px;margin-bottom:7px}.multi-actions button{border:1px solid var(--bd);background:#f8fbfa;border-radius:8px;padding:6px 9px;font-size:9px;font-weight:900;color:var(--g)}.multi-menu input{width:100%;min-width:0!important;margin-bottom:7px}.multi-options{max-height:260px;overflow:auto;display:grid;gap:2px}.multi-option{display:flex;align-items:center;gap:8px;padding:7px 6px;border-radius:7px;font-size:9px}.multi-option:hover{background:#f3f8f6}.multi-option input{width:auto;min-width:0;margin:0}.new-note{font-size:8px;font-weight:900;color:#0369a1;margin-top:3px}.dde-int{font-variant-numeric:tabular-nums}
@media(max-width:650px){.brand img{width:145px;height:48px}.multi,.multi-btn,.export-btn{width:100%}.multi-btn{min-width:0}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    # Acrescenta refs dos novos controles.
    old_refs = "function refs(){E={subtitle:document.getElementById('subtitle'),search:document.getElementById('search'),supplier:document.getElementById('supplier'),curve:document.getElementById('curve'),kpis:document.getElementById('kpis'),tabs:document.getElementById('tabs'),title:document.getElementById('title'),desc:document.getElementById('desc'),count:document.getElementById('count'),content:document.getElementById('content'),formula:document.getElementById('formula')}}"
    new_refs = "function refs(){E={subtitle:document.getElementById('subtitle'),search:document.getElementById('search'),supplier:document.getElementById('supplier'),curve:document.getElementById('curve'),kpis:document.getElementById('kpis'),tabs:document.getElementById('tabs'),title:document.getElementById('title'),desc:document.getElementById('desc'),count:document.getElementById('count'),content:document.getElementById('content'),formula:document.getElementById('formula'),supplierBtn:document.getElementById('supplierBtn'),supplierMenu:document.getElementById('supplierMenu'),supplierSearch:document.getElementById('supplierSearch'),supplierOptions:document.getElementById('supplierOptions'),exportXlsx:document.getElementById('exportXlsx'),exportPdf:document.getElementById('exportPdf')}}"
    if old_refs in text:
        text = text.replace(old_refs, new_refs, 1)

    # Substitui construção do fornecedor e aplicação do filtro.
    old_build = "function buildFilters(){const su=[...new Set(S.all.map(x=>x.fornecedor).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'));E.supplier.innerHTML='<option value=\"\">Todos os fornecedores</option>'+su.map(x=>`<option value=\"${esc(x)}\">${esc(x)}</option>`).join('');const cu=[...new Set(S.all.map(x=>x.curva).filter(Boolean))].sort();E.curve.innerHTML='<option value=\"\">Todas as curvas</option>'+cu.map(x=>`<option value=\"${esc(x)}\">${esc(x)}</option>`).join('')}"
    new_build = r'''function selectedSuppliers(){return Array.from(E.supplier.selectedOptions||[]).map(o=>o.value).filter(Boolean)}
function supplierLabel(){const v=selectedSuppliers();return !v.length?'Todos os fornecedores':(v.length===1?v[0]:`${v.length} fornecedores selecionados`)}
function syncSupplierLabel(){if(E.supplierBtn)E.supplierBtn.innerHTML=`${esc(supplierLabel())} <i class="fa-solid fa-chevron-down"></i>`}
function renderSupplierOptions(filter=''){const needle=filter.trim().toLowerCase();const selected=new Set(selectedSuppliers());const items=Array.from(E.supplier.options).map(o=>o.value).filter(Boolean).filter(v=>!needle||v.toLowerCase().includes(needle));E.supplierOptions.innerHTML=items.map(v=>`<label class="multi-option"><input type="checkbox" value="${esc(v)}" ${selected.has(v)?'checked':''}><span>${esc(v)}</span></label>`).join('');E.supplierOptions.querySelectorAll('input[type=checkbox]').forEach(cb=>cb.addEventListener('change',()=>{const option=Array.from(E.supplier.options).find(o=>o.value===cb.value);if(option)option.selected=cb.checked;syncSupplierLabel();applyFilter()}))}
function setupSupplierMulti(){if(!E.supplierBtn)return;E.supplierBtn.addEventListener('click',e=>{e.stopPropagation();E.supplierMenu.classList.toggle('hidden');if(!E.supplierMenu.classList.contains('hidden')){E.supplierSearch.value='';renderSupplierOptions();E.supplierSearch.focus()}});E.supplierSearch.addEventListener('input',()=>renderSupplierOptions(E.supplierSearch.value));document.getElementById('supplierAll')?.addEventListener('click',()=>{Array.from(E.supplier.options).forEach(o=>o.selected=true);renderSupplierOptions();syncSupplierLabel();applyFilter()});document.getElementById('supplierClear')?.addEventListener('click',()=>{Array.from(E.supplier.options).forEach(o=>o.selected=false);renderSupplierOptions();syncSupplierLabel();applyFilter()});document.addEventListener('click',e=>{if(!document.getElementById('supplierMulti')?.contains(e.target))E.supplierMenu.classList.add('hidden')})}
function buildFilters(){const su=[...new Set(S.all.map(x=>x.fornecedor).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'));E.supplier.innerHTML=su.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');renderSupplierOptions();syncSupplierLabel();const cu=[...new Set(S.all.map(x=>x.curva).filter(Boolean))].sort();E.curve.innerHTML='<option value="">Todas as curvas</option>'+cu.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')}'''
    if old_build in text:
        text = text.replace(old_build, new_build, 1)

    old_apply = "function applyFilter(){const q=E.search.value.trim().toLowerCase(),su=E.supplier.value,cu=E.curve.value;S.filtered=S.all.filter(x=>(!q||[x.produto,x.codigo,x.ean,x.fornecedor].join(' ').toLowerCase().includes(q))&&(!su||x.fornecedor===su)&&(!cu||x.curva===cu));S.visible=PAGE;render()}"
    new_apply = "function applyFilter(){const q=E.search.value.trim().toLowerCase(),su=new Set(selectedSuppliers()),cu=E.curve.value;S.filtered=S.all.filter(x=>(!q||[x.produto,x.codigo,x.ean,x.fornecedor].join(' ').toLowerCase().includes(q))&&(!su.size||su.has(x.fornecedor))&&(!cu||x.curva===cu));S.visible=PAGE;render()}"
    if old_apply in text:
        text = text.replace(old_apply, new_apply, 1)

    # DDE inteiro e sem selo duplicado sob data. Produto novo permanece apenas sob o nome.
    text = text.replace('<td class="num"><b>${fmt(x.dde)}</b></td><td>${esc(x.ultimaEntrada||\'—\')}${x.produtoNovo?\'<br><span class="pill info">PRODUTO NOVO</span>\':\'\'}</td>', '<td class="num dde-int"><b>${Math.round(Number(x.dde)||0)}</b></td><td>${esc(x.ultimaEntrada||\'—\')}</td>', 1)
    text = text.replace('<td class="num"><b>${fmt(x.dde)}</b></td>', '<td class="num dde-int"><b>${Math.round(Number(x.dde)||0)}</b></td>', 1)

    # Fornecedores na visão agregada respeitam seleção múltipla.
    old_suppliers_view = "if(S.tab==='suppliers'){const q=E.search.value.trim().toLowerCase(),su=E.supplier.value;let rows=S.data.fornecedores.filter(x=>(!q||x.fornecedor.toLowerCase().includes(q))&&(!su||x.fornecedor===su));"
    new_suppliers_view = "if(S.tab==='suppliers'){const q=E.search.value.trim().toLowerCase(),su=new Set(selectedSuppliers());let rows=S.data.fornecedores.filter(x=>(!q||x.fornecedor.toLowerCase().includes(q))&&(!su.size||su.has(x.fornecedor)));"
    if old_suppliers_view in text:
        text = text.replace(old_suppliers_view, new_suppliers_view, 1)

    # Exportação do recorte atual.
    init_anchor = "function init(){refs();E.search.addEventListener('input',applyFilter);E.supplier.addEventListener('change',applyFilter);E.curve.addEventListener('change',applyFilter);load()}"
    init_new = r'''function exportUrl(ext){const p=new URLSearchParams();if(E.search.value.trim())p.set('q',E.search.value.trim());selectedSuppliers().forEach(v=>p.append('fornecedor',v));if(E.curve.value)p.set('curva',E.curve.value);p.set('aba',S.tab);p.set('ordenar',S.sort);p.set('direcao',String(S.dir));return `/data/inteligencia-comercial/export.${ext}?${p.toString()}`}
function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}'''
    if init_anchor in text:
        text = text.replace(init_anchor, init_new, 1)

    # Injeta a logo padrão diretamente a partir do mesmo base64 da tela de Indústrias,
    # obtido no backend pelo patch de identidade visual abaixo.
    logo_placeholder = "<img id=\"dismepeOneLogo\" alt=\"DISMEPE ONE\">"
    try:
        industries = (Path(__file__).resolve().parents[1] / "frontend" / "industries.html").read_text(encoding="utf-8")
        import re
        match = re.search(r'<div class="brand"><img src="(data:image/png;base64,[^"]+)"', industries)
        if match and logo_placeholder in text:
            text = text.replace(logo_placeholder, f'<img id="dismepeOneLogo" src="{match.group(1)}" alt="DISMEPE ONE">', 1)
    except Exception:
        pass

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]
    try:
        temp = page.with_name(page.name + ".intelligence-ui-v4.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
