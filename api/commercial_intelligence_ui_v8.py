from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V8"


def install_commercial_intelligence_ui_v8() -> None:
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

    # Nova visão para montar promoções.
    option_anchor = '<option value="suppliers">Fornecedores</option>'
    if option_anchor in text and '<option value="promotion">Montar promoção</option>' not in text:
        text = text.replace(option_anchor, option_anchor + '\n<option value="promotion">Montar promoção</option>', 1)

    # Barra da promoção ativa.
    hero_anchor = '<section class="kpis" id="kpis"></section>'
    promo_bar = r'''
<section class="promo-toolbar" id="promoToolbar">
  <div class="promo-main">
    <div><span class="promo-label">Promoção ativa</span><select id="promoSelect"></select></div>
    <button type="button" id="promoNew" class="promo-btn"><i class="fa-solid fa-plus"></i> Nova promoção</button>
    <button type="button" id="promoOpen" class="promo-btn"><i class="fa-solid fa-tags"></i> Montar promoção</button>
  </div>
  <div class="promo-hint">Digite o preço promocional na linha e pressione <b>Enter</b>. O produto entra automaticamente na promoção ativa.</div>
</section>
'''
    if hero_anchor in text and 'id="promoToolbar"' not in text:
        text = text.replace(hero_anchor, promo_bar + hero_anchor, 1)

    # Painel da promoção.
    main_end = '</main>'
    promo_panel = r'''
<section class="promo-panel hidden" id="promoPanel">
  <div class="promo-panel-head">
    <div><span class="promo-label">RASCUNHO DE PROMOÇÃO</span><h2 id="promoTitle">Montar promoção</h2><p id="promoNotice">As promoções ficam disponíveis apenas para o usuário que as criou.</p></div>
    <div class="promo-actions"><button id="promoXlsx" class="promo-btn"><i class="fa-solid fa-file-excel"></i> Excel</button><button id="promoPdf" class="promo-btn"><i class="fa-solid fa-file-pdf"></i> PDF</button><button id="promoDelete" class="promo-btn danger-btn"><i class="fa-solid fa-trash"></i> Excluir</button></div>
  </div>
  <div class="promo-name-row"><label>Nome da promoção<input id="promoName" maxlength="120" placeholder="Ex.: Sextou no QG"></label><div class="promo-expiry" id="promoExpiry">Após exportar, esta promoção será excluída automaticamente em até 24 horas.</div></div>
  <div id="promoItems"></div>
</section>
'''
    if main_end in text and 'id="promoPanel"' not in text:
        text = text.replace(main_end, promo_panel + '\n' + main_end, 1)

    css_anchor = '</style>'
    css_patch = r'''
.promo-toolbar{background:#fff;border:1px solid var(--bd);border-radius:14px;padding:10px 12px;display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.promo-main{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.promo-main>div{display:grid;gap:3px}.promo-label{font-size:7px;font-weight:950;letter-spacing:.12em;color:#5e746e}.promo-main select,.promo-name-row input{height:36px;border:1px solid var(--bd);border-radius:9px;background:#fff;padding:0 9px;color:var(--tx);font-weight:800}.promo-main select{min-width:230px}.promo-btn{height:36px;border:1px solid #bfd4ce;background:#fff;color:var(--g);border-radius:9px;padding:0 11px;font-size:9px;font-weight:900;cursor:pointer}.promo-btn:hover{background:#f1f8f5}.danger-btn{color:#b4233d}.promo-hint{font-size:8px;color:var(--mut)}.promo-panel{max-width:1500px;margin:14px auto 0;padding:0 18px 30px}.promo-panel.hidden{display:none}.promo-panel-head,.promo-name-row{background:#fff;border:1px solid var(--bd);border-radius:14px;padding:13px;display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.promo-panel-head h2{margin:2px 0;font-size:17px}.promo-panel-head p{margin:2px 0 0;font-size:8px;color:var(--mut)}.promo-actions{display:flex;gap:6px;flex-wrap:wrap}.promo-name-row{margin-top:8px}.promo-name-row label{display:grid;gap:4px;font-size:8px;font-weight:900;color:#5e746e}.promo-name-row input{min-width:300px}.promo-expiry{font-size:8px;color:#8a5a12;background:#fff9e9;border:1px solid #f1dfaa;border-radius:9px;padding:8px 10px}.promo-items-table{width:100%;border-collapse:collapse;min-width:720px}.promo-items-wrap{margin-top:8px;background:#fff;border:1px solid var(--bd);border-radius:14px;overflow:auto}.promo-items-table th{background:#eef5f2;font-size:8px;text-transform:uppercase;padding:9px;text-align:left}.promo-items-table td{font-size:9px;padding:9px;border-top:1px solid #edf2f0}.promo-price-input{width:100px;height:32px;border:1px solid var(--bd);border-radius:8px;padding:0 8px;text-align:right;font-weight:900}.promo-row-remove{border:0;background:transparent;color:#b4233d;cursor:pointer}.promo-empty{padding:28px;text-align:center;color:var(--mut);font-size:9px}.price-entry{width:90px;height:31px;border:1px solid #a9cfc4;border-radius:8px;padding:0 8px;text-align:right;font-size:9px;font-weight:900;background:#f9fffd}.price-entry:focus{outline:none;border-color:#079b72;box-shadow:0 0 0 3px rgba(7,155,114,.10)}
@media(max-width:650px){.promo-main,.promo-main>*{width:100%}.promo-main select,.promo-btn,.promo-name-row input{width:100%;min-width:0}.promo-panel{padding:0 10px 22px}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    # Adiciona coluna Preço na tabela de produtos.
    cols_anchor = "['acao','Ação']"
    if cols_anchor in text and "['promoPrice','Preço promoção']" not in text:
        text = text.replace(cols_anchor, cols_anchor + ",['promoPrice','Preço promoção']", 1)

    # Injeta célula de preço antes do histórico mensal.
    action_cell = '<td class="action">${esc(x.acao)}</td>${x.historico.map(v=>`<td class="num">${fmt(v)}</td>`).join(\'\')}'
    price_cell = '<td class="action">${esc(x.acao)}</td><td><input class="price-entry" data-code="${esc(x.codigo)}" inputmode="decimal" placeholder="R$ 0,00"></td>${x.historico.map(v=>`<td class="num">${fmt(v)}</td>`).join(\'\')}'
    if action_cell in text:
        text = text.replace(action_cell, price_cell, 1)

    # Referências extras.
    refs_anchor = "productDetail:document.getElementById('productDetail')"
    refs_new = "productDetail:document.getElementById('productDetail'),promoToolbar:document.getElementById('promoToolbar'),promoSelect:document.getElementById('promoSelect'),promoNew:document.getElementById('promoNew'),promoOpen:document.getElementById('promoOpen'),promoPanel:document.getElementById('promoPanel'),promoTitle:document.getElementById('promoTitle'),promoNotice:document.getElementById('promoNotice'),promoName:document.getElementById('promoName'),promoExpiry:document.getElementById('promoExpiry'),promoItems:document.getElementById('promoItems'),promoXlsx:document.getElementById('promoXlsx'),promoPdf:document.getElementById('promoPdf'),promoDelete:document.getElementById('promoDelete')"
    if refs_anchor in text:
        text = text.replace(refs_anchor, refs_new, 1)

    # Visão promotion não solicita produtos da API.
    load_fetch = "fetch('/data/inteligencia-comercial?visao='+encodeURIComponent(S.tab)+'&ts='+Date.now(),{credentials:'same-origin',cache:'no-store'})"
    load_fetch_new = "fetch('/data/inteligencia-comercial?visao='+encodeURIComponent(S.tab==='promotion'?'overview':S.tab)+'&ts='+Date.now(),{credentials:'same-origin',cache:'no-store'})"
    if load_fetch in text:
        text = text.replace(load_fetch, load_fetch_new, 1)

    # Helpers de promoção antes do load.
    script_anchor = 'async function load(){try{'
    helpers = r'''
const P={list:[],active:null,saving:false};
function promoCurrency(v){return Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function promoMarkup(price,cost){price=Number(price||0);cost=Number(cost||0);return cost>0?((price/cost)-1)*100:0}
function currentPromo(){return P.list.find(x=>x.id===P.active)||null}
function parsePrice(v){const s=String(v||'').trim().replace(/R\$\s?/g,'').replace(/\./g,'').replace(',','.');const n=Number(s);return Number.isFinite(n)&&n>0?n:0}
async function promoApi(url,opts={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...opts});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Falha na promoção.');return d}
function renderPromoSelect(){if(!E.promoSelect)return;E.promoSelect.innerHTML=P.list.length?P.list.map(x=>`<option value="${esc(x.id)}" ${x.id===P.active?'selected':''}>${esc(x.name||'Nova promoção')} (${(x.items||[]).length})</option>`).join(''):'<option value="">Nenhuma promoção</option>'}
function expiryText(p){if(!p?.expires_at)return 'Após exportar, esta promoção será excluída automaticamente em até 24 horas.';const ms=new Date(p.expires_at).getTime()-Date.now();if(ms<=0)return 'Promoção expirada e aguardando limpeza automática.';const h=Math.max(0,Math.ceil(ms/3600000));return `Promoção exportada. Será excluída automaticamente em aproximadamente ${h} hora${h===1?'':'s'}.`}
function renderPromoPanel(){const p=currentPromo();if(!E.promoPanel)return;const open=S.tab==='promotion';E.promoPanel.classList.toggle('hidden',!open);if(!open)return;if(!p){E.promoTitle.textContent='Montar promoção';E.promoName.value='';E.promoExpiry.textContent='Crie uma promoção para começar.';E.promoItems.innerHTML='<div class="promo-empty">Nenhuma promoção criada.</div>';return}E.promoTitle.textContent=p.name||'Promoção';E.promoName.value=p.name||'';E.promoExpiry.textContent=expiryText(p);const items=Array.isArray(p.items)?p.items:[];E.promoItems.innerHTML=items.length?`<div class="promo-items-wrap"><table class="promo-items-table"><thead><tr><th>Código</th><th>Produto</th><th>Preço promoção</th><th>Markup promoção</th><th></th></tr></thead><tbody>${items.map(i=>`<tr><td>${esc(i.codigo)}</td><td>${esc(i.produto||'')}</td><td><input class="promo-price-input" data-code="${esc(i.codigo)}" value="${Number(i.precoPromocional||0).toFixed(2).replace('.',',')}"></td><td><b>${promoMarkup(i.precoPromocional,i.custo).toFixed(2).replace('.',',')}%</b></td><td><button class="promo-row-remove" data-code="${esc(i.codigo)}"><i class="fa-solid fa-trash"></i></button></td></tr>`).join('')}</tbody></table></div>`:'<div class="promo-empty">Digite um preço promocional em qualquer produto e pressione Enter.</div>';E.promoItems.querySelectorAll('.promo-price-input').forEach(inp=>{inp.addEventListener('change',()=>{const item=items.find(i=>i.codigo===inp.dataset.code);if(item){const price=parsePrice(inp.value);if(price>0){item.precoPromocional=price;savePromo(p)}}})});E.promoItems.querySelectorAll('.promo-row-remove').forEach(btn=>btn.addEventListener('click',()=>{p.items=items.filter(i=>i.codigo!==btn.dataset.code);savePromo(p)}))}
async function loadPromos(){try{const d=await promoApi('/data/inteligencia-comercial/promocoes');P.list=Array.isArray(d.promocoes)?d.promocoes:[];if(!P.active||!P.list.some(x=>x.id===P.active))P.active=P.list[0]?.id||null;renderPromoSelect();renderPromoPanel()}catch(e){console.error(e)}}
async function createPromo(){const name=(prompt('Nome da promoção:','Nova promoção')||'').trim();if(!name)return;const d=await promoApi('/data/inteligencia-comercial/promocoes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name,items:[]})});const p=d.promocao;if(p){P.list.unshift(p);P.active=p.id;renderPromoSelect();S.tab='promotion';if(E.viewSelect)E.viewSelect.value='promotion';renderPromoPanel()}}
async function savePromo(p){if(!p||P.saving)return;P.saving=true;try{const d=await promoApi('/data/inteligencia-comercial/promocoes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:p.id,name:p.name,items:p.items||[]})});if(d.promocao){const idx=P.list.findIndex(x=>x.id===p.id);if(idx>=0)P.list[idx]=d.promocao;renderPromoSelect();renderPromoPanel()}}finally{P.saving=false}}
async function addToPromo(product,price){let p=currentPromo();if(!p){await createPromo();p=currentPromo();if(!p)return}const items=Array.isArray(p.items)?p.items:[];let item=items.find(i=>i.codigo===product.codigo);if(!item){item={codigo:product.codigo,produto:product.produto||'',fornecedor:product.fornecedor||'',custo:Number(product.preco||0),precoPromocional:price};items.push(item)}else{item.precoPromocional=price;item.custo=Number(product.preco||item.custo||0)}p.items=items;await savePromo(p)}
function wirePriceEntries(){E.content?.querySelectorAll('.price-entry').forEach(inp=>{inp.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();const price=parsePrice(inp.value);if(price<=0){inp.focus();return}const product=S.all.find(x=>String(x.codigo)===String(inp.dataset.code));if(!product)return;await addToPromo(product,price);inp.value='';inp.placeholder='Adicionado';setTimeout(()=>inp.placeholder='R$ 0,00',1200)})})}
'''
    if script_anchor in text and 'function loadPromos()' not in text:
        text = text.replace(script_anchor, helpers + '\n' + script_anchor, 1)

    # Depois de renderizar tabela, liga inputs de preço; promotion só abre painel.
    render_start = "function render(){if(E.viewSelect)E.viewSelect.value=S.tab;"
    render_new = "function render(){if(E.viewSelect)E.viewSelect.value=S.tab;renderPromoPanel();if(S.tab==='promotion'){E.title.textContent='Montar promoção';E.desc.textContent='Monte e exporte promoções diretamente a partir da Inteligência Comercial.';E.count.textContent=((currentPromo()?.items||[]).length).toLocaleString('pt-BR')+' produtos';E.content.innerHTML='<div class=\"empty\">Use as demais visões para localizar produtos e digitar o preço promocional. A promoção ativa permanece salva no servidor.</div>';return}"
    if render_start in text:
        text = text.replace(render_start, render_new, 1)

    # Conecta o wirePriceEntries após tabela.
    table_render = "E.content.innerHTML=all.length?table(shown,all.length):'<div class=\"empty\">Nenhum produto neste recorte.</div>';"
    table_render_new = table_render + "wirePriceEntries();"
    if table_render in text:
        text = text.replace(table_render, table_render_new, 1)

    # Init com promoções e eventos.
    init_anchor = "function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;load()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});load()}"
    init_new = r'''function init(){refs();E.search.addEventListener('input',applyFilter);E.curve.addEventListener('change',applyFilter);E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;if(S.tab==='promotion'){render();return}load()});setupSupplierMulti();E.exportXlsx?.addEventListener('click',()=>{location.href=exportUrl('xlsx')});E.exportPdf?.addEventListener('click',()=>{location.href=exportUrl('pdf')});E.promoSelect?.addEventListener('change',()=>{P.active=E.promoSelect.value||null;renderPromoPanel()});E.promoNew?.addEventListener('click',createPromo);E.promoOpen?.addEventListener('click',()=>{S.tab='promotion';if(E.viewSelect)E.viewSelect.value='promotion';render()});E.promoName?.addEventListener('change',()=>{const p=currentPromo();if(p){p.name=E.promoName.value.trim()||p.name;savePromo(p)}});E.promoDelete?.addEventListener('click',async()=>{const p=currentPromo();if(!p||!confirm('Excluir esta promoção?'))return;await promoApi('/data/inteligencia-comercial/promocoes/'+encodeURIComponent(p.id),{method:'DELETE'});P.list=P.list.filter(x=>x.id!==p.id);P.active=P.list[0]?.id||null;renderPromoSelect();renderPromoPanel()});E.promoXlsx?.addEventListener('click',()=>{const p=currentPromo();if(!p)return;location.href='/data/inteligencia-comercial/promocoes/'+encodeURIComponent(p.id)+'/export.xlsx';setTimeout(loadPromos,1200)});E.promoPdf?.addEventListener('click',()=>{const p=currentPromo();if(!p)return;location.href='/data/inteligencia-comercial/promocoes/'+encodeURIComponent(p.id)+'/export.pdf';setTimeout(loadPromos,1200)});loadPromos();load()}'''
    if init_anchor in text:
        text = text.replace(init_anchor, init_new, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v8.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
