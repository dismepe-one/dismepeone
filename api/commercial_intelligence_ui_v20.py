from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V20"


def install_commercial_intelligence_ui_v20() -> None:
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

    # Qtd. última entrada representa unidades inteiras. Não usa formatação
    # pt-BR para evitar ponto/vírgula como separadores visuais.
    text = text.replace(
        "${fmt(x.quantidadeUltimaEntrada||0)}",
        "${String(Math.max(0,Math.round(Number(x.quantidadeUltimaEntrada||0))))}",
    )

    # DDE é um indicador em dias e deve ser exibido sem casas decimais.
    # Mantém o valor numérico original para cálculos e ordenação; altera
    # somente a apresentação na tabela.
    text = text.replace(
        "<b>${fmt(x.dde)}</b>",
        "<b>${String(Math.round(Number(x.dde||0)))}</b>",
    )

    # Nos gráficos de Estatísticas, identifica produtos por código + nome.
    # Fornecedores continuam exibidos apenas pelo nome, sem mudar cálculos.
    text = text.replace(
        "title=\"${esc(x.produto||x.fornecedor||'')}\"",
        "title=\"${esc(x.produto?((x.codigo?x.codigo+' - ':'')+x.produto):(x.fornecedor||''))}\"",
    )
    text = text.replace(
        "shortName(x.produto||x.fornecedor||'')",
        "shortName(x.produto?((x.codigo?x.codigo+' - ':'')+x.produto):(x.fornecedor||''),42)",
    )
    text = text.replace(
        "title=\"${esc(x.produto)} · Giro",
        "title=\"${esc((x.codigo?x.codigo+' - ':'')+(x.produto||''))} · Giro",
    )

    # Regra visual e de filtro de vencimento: até 12 meses é considerado próximo.
    # Reconhece também MM/AAAA, formato utilizado no mapa complementar.
    text = text.replace("Venc. ≤ 90 dias", "Venc. ≤ 12 meses")
    helper = r'''function ciNearExpiry(x){
  const raw=String(x?.vencimento||x?.validade||'').trim();
  if(!raw)return false;
  let d=null;
  let m=raw.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{2,4})/);
  if(m){let y=Number(m[3]);if(y<100)y+=2000;d=new Date(y,Number(m[2])-1,Number(m[1]));}
  else{
    m=raw.match(/^(\d{1,2})[\/-](\d{4})$/);
    if(m){const month=Number(m[1]),year=Number(m[2]);d=new Date(year,month,0);}
    else{m=raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);if(m)d=new Date(Number(m[1]),Number(m[2])-1,Number(m[3]));}
  }
  if(!d||Number.isNaN(d.getTime()))return !!x?.vencimentoProximo;
  const now=new Date();const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const limit=new Date(today.getFullYear(),today.getMonth()+12,today.getDate());
  return d>=today&&d<=limit;
}
'''
    if "function ciNearExpiry(x)" not in text:
        text = text.replace("function applyFilter(){", helper + "function applyFilter(){", 1)
    text = text.replace("(!expiring||x.vencimentoProximo)", "(!expiring||ciNearExpiry(x))")
    text = text.replace("x.vencimentoProximo?'", "ciNearExpiry(x)?'")
    text = text.replace("${x.vencimentoProximo?'color:#be123c':''}", "${ciNearExpiry(x)?'color:#be123c':''}")
    text = text.replace(
        "<td>${esc(x.vencimento||'—')}</td>",
        "<td>${ciNearExpiry(x)?'<span style=\"color:#be123c;font-weight:900\">'+esc(x.vencimento||'—')+'</span>':esc(x.vencimento||'—')}</td>",
    )
    text = text.replace(
        "<div class=\"detail-cell\"><span>Validade</span><b>${esc(x.vencimento||'—')}</b></div>",
        "<div class=\"detail-cell\"><span>Validade</span><b style=\"${ciNearExpiry(x)?'color:#be123c':''}\">${esc(x.vencimento||'—')}</b></div>",
    )

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v20.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
