from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V15"


def install_commercial_intelligence_ui_v15() -> None:
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

    # Pc.Custo do mapa complementar passa a ser exibido como Custo Médio.
    text = text.replace("['preco','Custo médio']", "['preco','Custo Médio']", 1)
    text = text.replace('<th>Código</th><th>Produto</th><th>Custo</th><th>Preço promoção</th><th>Markup promoção</th><th></th>', '<th>Código</th><th>Produto</th><th>Custo Médio</th><th>Preço promoção</th><th>Markup promoção</th><th></th>', 1)

    # Exibe os dados complementares logo abaixo do produto, principalmente útil no celular.
    # Não depende apenas da flag complementoTemporario: alguns fluxos podem manter os
    # campos complementares disponíveis mesmo quando a flag não vier marcada.
    old_product = '<td><b>${esc(x.produto)}</b><br>${badge(x)}</td>'
    new_product = '''<td><b>${esc(x.produto)}</b><br>${badge(x)}${(x.complementoTemporario||Number(x.precoMedioComplemento||0)>0||x.lote||x.vencimento||Number(x.quantidadeUltimaEntrada||0)>0)?`<div class="ci-complement-inline"><span><b>Custo Médio:</b> ${money(Number(x.precoMedioComplemento||0)>0?x.precoMedioComplemento:(x.preco||0))}</span><span><b>Lote:</b> ${esc(x.lote||'—')}</span><span><b>Validade:</b> <strong style="${x.vencimentoProximo?'color:#be123c':''}">${esc(x.vencimento||'—')}</strong></span><span><b>Qtd. últ. entrada:</b> ${fmt(x.quantidadeUltimaEntrada||0)}</span></div>`:''}</td>'''
    if old_product in text:
        text = text.replace(old_product, new_product, 1)

    css_anchor = '</style>'
    css_patch = r'''
.ci-complement-inline{display:none;margin-top:6px;padding-top:6px;border-top:1px dashed #d9e7e3;gap:4px}.ci-complement-inline span{font-size:8px;color:#5f746e}.ci-complement-inline b{font-size:8px;color:#244b41}@media(max-width:760px){.ci-complement-inline{display:grid;grid-template-columns:1fr 1fr}.ci-complement-inline span{white-space:nowrap}}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + '\n' + css_anchor, 1)

    # Detalhe do produto: identifica claramente o Pc.Custo como Custo Médio.
    detail_anchor = '<div class="detail-cell"><span>Estoque</span><b>${fmt(x.estoque)}</b></div>'
    if detail_anchor in text and '<span>Custo Médio</span>' not in text:
        detail_price = '<div class="detail-cell"><span>Custo Médio</span><b>${money(Number(x.precoMedioComplemento||0)>0?x.precoMedioComplemento:(x.preco||0))}</b></div>'
        text = text.replace(detail_anchor, detail_anchor + detail_price, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v15.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
