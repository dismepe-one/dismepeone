from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V2"


def install_commercial_intelligence_ui_patch() -> None:
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

    replacements = [
        (
            "const tabDefs=[['overview','Visão geral'],['critical','Críticos'],['low','Venda abaixo da média'],['high','Venda acima do normal'],['dde','DDE'],['noTurn','Sem giro'],['suppliers','Fornecedores']];",
            "const tabDefs=[['overview','Visão geral'],['critical','Críticos'],['rupture','Risco de ruptura'],['low','Venda abaixo da média'],['high','Venda acima do normal'],['dde','DDE'],['new','Produtos novos'],['noTurn','Sem giro'],['suppliers','Fornecedores']];",
        ),
        (
            "if(S.tab==='critical')r=r.filter(x=>x.critico);if(S.tab==='low')r=r.filter(x=>x.baixo);if(S.tab==='high')r=r.filter(x=>x.alta);if(S.tab==='dde')r=r.filter(x=>x.estoque>0);if(S.tab==='noTurn')r=r.filter(x=>x.semGiro);",
            "if(S.tab==='critical')r=r.filter(x=>x.critico);if(S.tab==='rupture')r=r.filter(x=>x.riscoRuptura);if(S.tab==='low')r=r.filter(x=>x.baixo);if(S.tab==='high')r=r.filter(x=>x.alta);if(S.tab==='dde')r=r.filter(x=>x.estoque>0);if(S.tab==='new')r=r.filter(x=>x.produtoNovo);if(S.tab==='noTurn')r=r.filter(x=>x.semGiro);",
        ),
        (
            "function badge(x){if(x.critico)return '<span class=\"pill danger\">CRÍTICO</span>';if(x.alta)return '<span class=\"pill info\">EM ALTA</span>';if(x.baixo)return '<span class=\"pill warn\">EM QUEDA</span>';return '<span class=\"pill ok\">NORMAL</span>'}",
            "function badge(x){if(x.produtoNovo)return '<span class=\"pill info\">PRODUTO NOVO</span>';if(x.ruptura)return '<span class=\"pill danger\">RUPTURA</span>';if(x.riscoRupturaAlto)return '<span class=\"pill danger\">RISCO ALTO</span>';if(x.riscoRuptura)return '<span class=\"pill warn\">RISCO RUPTURA</span>';if(x.critico)return '<span class=\"pill danger\">CRÍTICO</span>';if(x.alta)return '<span class=\"pill info\">EM ALTA</span>';if(x.baixo)return '<span class=\"pill warn\">EM QUEDA</span>';return '<span class=\"pill ok\">NORMAL</span>'}",
        ),
        (
            "const cols=[['produto','Produto'],['fornecedor','Fornecedor'],['estoque','Estoque'],['mediaUnidades','Média'],['dde','DDE'],['variacaoPct','Variação'],['acao','Ação']];",
            "const cols=[['produto','Produto'],['fornecedor','Fornecedor'],['estoque','Estoque'],['mediaUnidades','Média'],['dde','DDE'],['ultimaEntrada','Última entrada'],['variacaoPct','Variação'],['acao','Ação']];",
        ),
        (
            "<td class=\"num\"><b>${fmt(x.dde)}</b></td><td class=\"num\">${x.variacaoPct>0?'+':''}${fmt(x.variacaoPct)}%</td>",
            "<td class=\"num\"><b>${fmt(x.dde)}</b></td><td>${esc(x.ultimaEntrada||'—')}</td><td class=\"num\">${x.variacaoPct>0?'+':''}${fmt(x.variacaoPct)}%</td>",
        ),
        (
            "critical:['Críticos','Ruptura, pressão elevada, queda forte ou estoque sem giro.'],low:['Venda abaixo da média','Último mês fechado abaixo de 70% da média dos dois anteriores.'],high:['Venda acima do normal','Último mês fechado acima de 130% da média anterior.'],dde:['DDE','Ordenado pelo indicador solicitado. Quanto maior, maior a pressão da média sobre o estoque.'],noTurn:['Sem giro','Produtos com estoque e média de venda zerada.']",
            "critical:['Críticos','Ruptura, pressão elevada, queda forte ou estoque sem giro.'],rupture:['Risco de ruptura','Produtos sem estoque ou com DDE elevado em relação ao estoque disponível.'],low:['Venda abaixo da média','Último mês fechado abaixo de 70% da média dos dois anteriores.'],high:['Venda acima do normal','Último mês fechado acima de 130% da média anterior.'],dde:['DDE','Ordenado pelo indicador solicitado. Quanto maior, maior a pressão da média sobre o estoque.'],new:['Produtos novos','Sem giro, mas com última entrada realizada há até 15 dias.'],noTurn:['Sem giro','Produtos com estoque e média de venda zerada, excluindo entradas dos últimos 15 dias.']",
        ),
        (
            "['Sem giro',r.semGiro||0,'Estoque sem média']",
            "['Risco ruptura',r.riscoRuptura||0,'Estoque sob pressão']",
        ),
    ]

    patched = text
    for old, new in replacements:
        if old in patched:
            patched = patched.replace(old, new, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = patched.lower().rfind("</body>")
    if pos >= 0:
        patched = patched[:pos] + marker + patched[pos:]
    try:
        temp = page.with_name(page.name + ".intelligence-ui-v2.tmp")
        temp.write_text(patched, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
