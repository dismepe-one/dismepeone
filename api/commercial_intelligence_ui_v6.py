from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V6"


def install_commercial_intelligence_ui_v6() -> None:
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

    # Painel executivo entra entre KPIs e tabela principal.
    kpi_anchor = '<section class="kpis" id="kpis"></section>'
    dashboard = r'''
<section class="exec-grid" id="execDashboard">
  <article class="exec-card wide"><div class="exec-head"><div><b>Top 15 produtos em queda</b><span>Maior retração no último mês fechado</span></div></div><div id="chartDrop" class="bar-chart"></div></article>
  <article class="exec-card wide"><div class="exec-head"><div><b>Top 15 produtos em alta</b><span>Maior aceleração acima do padrão</span></div></div><div id="chartHigh" class="bar-chart"></div></article>
  <article class="exec-card"><div class="exec-head"><div><b>Estoque por fornecedor</b><span>Top 15 por valor de estoque</span></div></div><div id="chartSupplier" class="bar-chart compact"></div></article>
  <article class="exec-card"><div class="exec-head"><div><b>Distribuição dos alertas</b><span>Leitura do portfólio atual</span></div></div><div id="statusSummary" class="status-summary"></div></article>
  <article class="exec-card full"><div class="exec-head"><div><b>Oportunidades comerciais</b><span>Produtos agrupados por ação sugerida</span></div></div><div id="opportunityGrid" class="opp-grid"></div></article>
  <article class="exec-card full hidden" id="markupQuadrantCard"><div class="exec-head"><div><b>Giro × Markup</b><span>Quadrantes de giro e rentabilidade</span></div></div><div id="markupQuadrant" class="quadrant"></div></article>
  <article class="exec-card full"><div class="exec-head"><div><b>Evolução do produto selecionado</b><span>Clique em qualquer produto da tabela para detalhar</span></div></div><div id="productDetail" class="product-detail"><div class="empty-mini">Selecione um produto na tabela.</div></div></article>
</section>
'''
    if kpi_anchor in text and 'id="execDashboard"' not in text:
        text = text.replace(kpi_anchor, kpi_anchor + dashboard, 1)

    # Filtros adicionais, preparados para markup e vencimento.
    view_anchor = '<select id="viewSelect" title="Selecionar visão da análise">'
    advanced_filters = r'''<div class="adv-filters" id="advFilters">
<label><span>DDE mín.</span><input id="ddeMin" type="number" min="0" step="1" placeholder="0"></label>
<label><span>DDE máx.</span><input id="ddeMax" type="number" min="0" step="1" placeholder="—"></label>
<label><span>Estoque mín.</span><input id="stockMin" type="number" min="0" step="1" placeholder="0"></label>
<label class="hidden" id="markupMinWrap"><span>Markup mín.</span><input id="markupMin" type="number" min="0" step="0.1" placeholder="0"></label>
<label class="hidden" id="markupMaxWrap"><span>Markup máx.</span><input id="markupMax" type="number" min="0" step="0.1" placeholder="—"></label>
<label class="check-filter"><input id="onlyBlocked" type="checkbox"><span>Bloq. compra</span></label>
<label class="check-filter hidden" id="expiryFilterWrap"><input id="onlyExpiring" type="checkbox"><span>Venc. ≤ 90 dias</span></label>
</div>'''
    hero_end = '</section>\n<section class="kpis" id="kpis"></section>'
    if hero_end in text and 'id="advFilters"' not in text:
        text = text.replace('</section>\n<section class="kpis" id="kpis"></section>', advanced_filters + '\n</section>\n<section class="kpis" id="kpis"></section>', 1)

    css_anchor = '</style>'
    css_patch = r'''
.exec-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.exec-card{background:#fff;border:1px solid var(--bd);border-radius:14px;padding:13px;min-width:0}.exec-card.wide{min-height:330px}.exec-card.full{grid-column:1/-1}.exec-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.exec-head b{display:block;font-size:11px;color:#17332c}.exec-head span{display:block;font-size:8px;color:var(--mut);margin-top:2px}.bar-chart{display:grid;gap:5px;align-content:start}.bar-row{display:grid;grid-template-columns:minmax(150px,1.8fr) 3fr 58px;gap:7px;align-items:center;font-size:8px}.bar-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bar-track{height:10px;border-radius:999px;background:#edf3f1;overflow:hidden}.bar-fill{height:100%;min-width:2px;border-radius:999px;background:#0a7863}.bar-fill.drop{background:#c2415d}.bar-value{text-align:right;font-weight:900}.status-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.status-item{border:1px solid #e2ece9;border-radius:10px;padding:9px;background:#fafcfb}.status-item b{font-size:16px}.status-item span{display:block;font-size:8px;color:var(--mut);margin-top:2px}.opp-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.opp{border:1px solid #e1ebe8;border-radius:11px;padding:10px;background:#fbfdfc;cursor:pointer}.opp:hover{border-color:#8ec2b5}.opp b{font-size:16px}.opp span{display:block;font-size:8px;color:var(--mut);margin-top:3px}.quadrant{position:relative;min-height:310px;border:1px solid #e2ece9;border-radius:12px;background:linear-gradient(90deg,transparent 49.8%,#d9e7e3 50%,transparent 50.2%),linear-gradient(0deg,transparent 49.8%,#d9e7e3 50%,transparent 50.2%);overflow:hidden}.quad-label{position:absolute;font-size:8px;color:#6c7d78;font-weight:800}.quad-dot{position:absolute;width:8px;height:8px;border-radius:50%;background:#087864;transform:translate(-50%,-50%);opacity:.75}.product-detail{min-height:110px}.detail-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.detail-head h3{margin:0;font-size:14px}.detail-meta{font-size:9px;color:var(--mut);margin-top:3px}.detail-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px;margin-top:10px}.detail-cell{border:1px solid #e2ece9;border-radius:9px;padding:8px}.detail-cell span{display:block;font-size:7px;color:var(--mut);text-transform:uppercase}.detail-cell b{display:block;font-size:12px;margin-top:3px}.history-bars{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;align-items:end;height:100px;margin-top:12px}.history-bar{display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;height:100%}.history-bar i{width:70%;max-width:60px;background:#80b9aa;border-radius:6px 6px 0 0;min-height:2px}.history-bar b{font-size:9px}.history-bar span{font-size:7px;color:var(--mut)}.empty-mini{font-size:9px;color:var(--mut);padding:20px;text-align:center}.adv-filters{width:100%;display:flex;gap:7px;flex-wrap:wrap;margin-top:10px;padding-top:9px;border-top:1px solid rgba(0,85,72,.08)}.adv-filters label{display:grid;gap:3px}.adv-filters label span{font-size:7px;font-weight:900;color:#64748b;text-transform:uppercase}.adv-filters input[type=number]{width:90px;height:33px;border:1px solid var(--bd);border-radius:8px;padding:0 8px;font-size:9px}.check-filter{display:flex!important;align-items:center;grid-template-columns:auto auto!important;gap:6px!important;background:#fff;border:1px solid var(--bd);border-radius:8px;padding:0 9px;height:33px;margin-top:11px}.check-filter input{margin:0}.table tbody tr{cursor:pointer}.table tbody tr.selected td{background:#edf8f4!important}
@media(max-width:1000px){.opp-grid{grid-template-columns:repeat(2,1fr)}.detail-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:720px){.exec-grid{grid-template-columns:1fr}.exec-card.full{grid-column:auto}.opp-grid{grid-template-columns:1fr 1fr}.bar-row{grid-template-columns:minmax(110px,1.4fr) 2fr 48px}.detail-grid{grid-template-columns:repeat(2,1fr)}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    # Amplia referências.
    refs_old = "formula:document.getElementById('formula'),supplierBtn:document.getElementById('supplierBtn')"
    refs_new = "formula:document.getElementById('formula'),ddeMin:document.getElementById('ddeMin'),ddeMax:document.getElementById('ddeMax'),stockMin:document.getElementById('stockMin'),markupMin:document.getElementById('markupMin'),markupMax:document.getElementById('markupMax'),onlyBlocked:document.getElementById('onlyBlocked'),onlyExpiring:document.getElementById('onlyExpiring'),markupMinWrap:document.getElementById('markupMinWrap'),markupMaxWrap:document.getElementById('markupMaxWrap'),expiryFilterWrap:document.getElementById('expiryFilterWrap'),chartDrop:document.getElementById('chartDrop'),chartHigh:document.getElementById('chartHigh'),chartSupplier:document.getElementById('chartSupplier'),statusSummary:document.getElementById('statusSummary'),opportunityGrid:document.getElementById('opportunityGrid'),markupQuadrantCard:document.getElementById('markupQuadrantCard'),markupQuadrant:document.getElementById('markupQuadrant'),productDetail:document.getElementById('productDetail'),supplierBtn:document.getElementById('supplierBtn')"
    if refs_old in text:
        text = text.replace(refs_old, refs_new, 1)

    # Filtro avançado agregado ao filtro existente.
    apply_old = "function applyFilter(){const q=E.search.value.trim().toLowerCase(),su=new Set(selectedSuppliers()),cu=E.curve.value;S.filtered=S.all.filter(x=>(!q||[x.produto,x.codigo,x.ean,x.fornecedor].join(' ').toLowerCase().includes(q))&&(!su.size||su.has(x.fornecedor))&&(!cu||x.curva===cu));S.visible=PAGE;render()}"
    apply_new = r'''function applyFilter(){const q=E.search.value.trim().toLowerCase(),su=new Set(selectedSuppliers()),cu=E.curve.value;const dmin=Number(E.ddeMin?.value||0),dmax=E.ddeMax?.value===''?Infinity:Number(E.ddeMax?.value),smin=Number(E.stockMin?.value||0),mmin=Number(E.markupMin?.value||0),mmax=E.markupMax?.value===''?Infinity:Number(E.markupMax?.value),blocked=!!E.onlyBlocked?.checked,expiring=!!E.onlyExpiring?.checked;S.filtered=S.all.filter(x=>(!q||[x.produto,x.codigo,x.ean,x.fornecedor].join(' ').toLowerCase().includes(q))&&(!su.size||su.has(x.fornecedor))&&(!cu||x.curva===cu)&&Number(x.dde||0)>=dmin&&Number(x.dde||0)<=dmax&&Number(x.estoque||0)>=smin&&Number(x.markupMedio||0)>=mmin&&Number(x.markupMedio||0)<=mmax&&(!blocked||String(x.bloqCompra||'').trim())&&(!expiring||x.vencimentoProximo));S.visible=PAGE;render();renderExecutive()}'''
    if apply_old in text:
        text = text.replace(apply_old, apply_new, 1)

    # Adiciona gráficos e detalhe.
    script_anchor = "async function load(){try{"
    helpers = r'''
function shortName(v,max=34){const s=String(v||'');return s.length>max?s.slice(0,max-1)+'…':s}
function renderBars(el,rows,valueKey,drop=false,moneyMode=false){if(!el)return;const data=(rows||[]).slice(0,15);if(!data.length){el.innerHTML='<div class="empty-mini">Sem dados para este recorte.</div>';return}const vals=data.map(x=>Math.abs(Number(x[valueKey]||0)));const max=Math.max(1,...vals);el.innerHTML=data.map((x,i)=>`<div class="bar-row" title="${esc(x.produto||x.fornecedor||'')}"><div class="bar-label">${i+1}. ${esc(shortName(x.produto||x.fornecedor||''))}</div><div class="bar-track"><div class="bar-fill ${drop?'drop':''}" style="width:${Math.max(2,Math.round(Math.abs(Number(x[valueKey]||0))/max*100))}%"></div></div><div class="bar-value">${moneyMode?money(x[valueKey]):((Number(x[valueKey]||0)>0?'+':'')+Math.round(Number(x[valueKey]||0))+'%')}</div></div>`).join('')}
function renderStatus(){const s=S.data?.insights?.status||{};const items=[['Risco ruptura',s.riscoRuptura||0],['Sem giro',s.semGiro||0],['Produtos novos',s.produtoNovo||0],['Em queda',s.emQueda||0],['Em alta',s.emAlta||0],['Venc. próximo',s.vencimentoProximo||0],['Normal',s.normal||0]];E.statusSummary.innerHTML=items.map(x=>`<div class="status-item"><b>${fmt(x[1])}</b><span>${x[0]}</span></div>`).join('')}
function renderOpportunities(){const o=S.data?.insights?.oportunidades||{};const defs=[['garantirEstoque','Garantir estoque','rupture'],['acelerarVenda','Acelerar venda','low'],['capitalParado','Capital parado','noTurn'],['produtoEstrela','Produto estrela','high'],['reverPreco','Rever preço/margem','high'],['margemAltaGiroBaixo','Margem alta / giro baixo','low'],['vencimento','Vencimento próximo','overview']];E.opportunityGrid.innerHTML=defs.map(([k,l,v])=>`<div class="opp" data-view="${v}"><b>${fmt(o[k]?.quantidade||0)}</b><span>${l}</span></div>`).join('');E.opportunityGrid.querySelectorAll('.opp').forEach(x=>x.addEventListener('click',()=>{S.tab=x.dataset.view;E.viewSelect.value=S.tab;S.visible=PAGE;render()}))}
function renderQuadrant(){const enabled=!!S.data?.insights?.markupDisponivel;E.markupQuadrantCard?.classList.toggle('hidden',!enabled);if(!enabled||!E.markupQuadrant)return;const rows=S.filtered.filter(x=>Number(x.markupMedio||0)>0);if(!rows.length){E.markupQuadrant.innerHTML='<div class="empty-mini">Sem markup no recorte.</div>';return}const maxG=Math.max(1,...rows.map(x=>Number(x.mediaUnidades||0))),maxM=Math.max(1,...rows.map(x=>Number(x.markupMedio||0)));const points=rows.slice().sort((a,b)=>Number(b.mediaUnidades||0)-Number(a.mediaUnidades||0)).slice(0,250);E.markupQuadrant.innerHTML='<span class="quad-label" style="left:8px;top:8px">Markup alto / giro baixo</span><span class="quad-label" style="right:8px;top:8px">Produto estrela</span><span class="quad-label" style="left:8px;bottom:8px">Baixo giro / baixo markup</span><span class="quad-label" style="right:8px;bottom:8px">Giro alto / markup baixo</span>'+points.map(x=>`<i class="quad-dot" title="${esc(x.produto)} · Giro ${fmt(x.mediaUnidades)} · Markup ${fmt(x.markupMedio)}%" style="left:${Math.min(98,Math.max(2,Number(x.mediaUnidades||0)/maxG*96+2))}%;bottom:${Math.min(96,Math.max(2,Number(x.markupMedio||0)/maxM*92+2))}%"></i>`).join('')}
function renderProductDetail(x){if(!x||!E.productDetail)return;const h=x.historico||[],labels=S.data?.meses||[],mx=Math.max(1,...h.map(Number));E.productDetail.innerHTML=`<div class="detail-head"><div><h3>${esc(x.codigo)} · ${esc(x.produto)}</h3><div class="detail-meta">${esc(x.fornecedor)} · ${esc(x.acao||'')}</div></div>${badge(x)}</div><div class="detail-grid"><div class="detail-cell"><span>Estoque</span><b>${fmt(x.estoque)}</b></div><div class="detail-cell"><span>Média</span><b>${fmt(x.mediaUnidades)}</b></div><div class="detail-cell"><span>DDE</span><b>${Math.round(Number(x.dde)||0)}</b></div><div class="detail-cell"><span>Markup médio</span><b>${x.temMarkup?fmt(x.markupMedio)+'%':'—'}</b></div><div class="detail-cell"><span>Última entrada</span><b>${esc(x.ultimaEntrada||'—')}</b></div><div class="detail-cell"><span>Lote / vencimento</span><b>${esc(x.lote||'—')} · ${esc(x.vencimento||'—')}</b></div></div><div class="history-bars">${h.map((v,i)=>`<div class="history-bar"><b>${fmt(v)}</b><i style="height:${Math.max(2,Math.round(Number(v||0)/mx*72))}px"></i><span>${esc(labels[i]||'')}</span></div>`).join('')}</div>`}
function renderExecutive(){if(!S.data?.insights)return;const ins=S.data.insights;renderBars(E.chartDrop,ins.topQueda,'variacaoPct',true,false);renderBars(E.chartHigh,ins.topAlta,'variacaoPct',false,false);renderBars(E.chartSupplier,ins.topEstoqueFornecedores,'valorEstoque',false,true);renderStatus();renderOpportunities();renderQuadrant()}
'''
    if script_anchor in text and 'function renderExecutive()' not in text:
        text = text.replace(script_anchor, helpers + '\n' + script_anchor, 1)

    # Depois do load, mostra disponibilidade de filtros e dashboard.
    load_marker = "renderKpis();buildFilters();render()"
    load_replace = "renderKpis();buildFilters();if(E.markupMinWrap)E.markupMinWrap.classList.toggle('hidden',!data.insights?.markupDisponivel);if(E.markupMaxWrap)E.markupMaxWrap.classList.toggle('hidden',!data.insights?.markupDisponivel);if(E.expiryFilterWrap)E.expiryFilterWrap.classList.toggle('hidden',!data.insights?.vencimentoDisponivel);renderExecutive();render()"
    if load_marker in text:
        text = text.replace(load_marker, load_replace, 1)

    # Clique em produto para detalhe.
    table_row_old = "const body=rows.map(x=>`<tr><td>${esc(x.codigo)}</td>"
    table_row_new = "const body=rows.map(x=>`<tr data-code=\"${esc(x.codigo)}\"><td>${esc(x.codigo)}</td>"
    if table_row_old in text:
        text = text.replace(table_row_old, table_row_new, 1)

    render_end_old = "document.getElementById('loadMore')?.addEventListener('click',()=>{S.visible+=PAGE;render()})}"
    render_end_new = "document.getElementById('loadMore')?.addEventListener('click',()=>{S.visible+=PAGE;render()});E.content.querySelectorAll('tbody tr[data-code]').forEach(tr=>tr.addEventListener('click',()=>{E.content.querySelectorAll('tbody tr.selected').forEach(x=>x.classList.remove('selected'));tr.classList.add('selected');const item=S.all.find(x=>String(x.codigo)===String(tr.dataset.code));renderProductDetail(item)}))}"
    if render_end_old in text:
        text = text.replace(render_end_old, render_end_new, 1)

    # Advanced inputs disparam filtro.
    init_old = "function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;render()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}"
    init_new = "function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);[E.ddeMin,E.ddeMax,E.stockMin,E.markupMin,E.markupMax].filter(Boolean).forEach(x=>x.addEventListener('input',applyFilter));[E.onlyBlocked,E.onlyExpiring].filter(Boolean).forEach(x=>x.addEventListener('change',applyFilter));E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;render()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}"
    if init_old in text:
        text = text.replace(init_old, init_new, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]
    try:
        temp = page.with_name(page.name + ".intelligence-ui-v6.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
