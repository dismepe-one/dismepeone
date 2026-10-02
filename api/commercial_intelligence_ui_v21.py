from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V21"


def _install_next_layer() -> None:
    from .commercial_intelligence_ui_v22 import install_commercial_intelligence_ui_v22
    install_commercial_intelligence_ui_v22()


def install_commercial_intelligence_ui_v21() -> None:
    from . import commercial_intelligence as ci

    page = getattr(ci, "PAGE_FILE", None)
    if not isinstance(page, Path):
        return
    try:
        text = page.read_text(encoding="utf-8")
    except Exception:
        return
    if _MARKER in text:
        _install_next_layer()
        return

    # A base completa já está carregada em S.all/S.filtered. Trocar entre as
    # visões operacionais não precisa chamar load() e refazer requisição/análise.
    slow_change = "E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;if(S.tab==='promotion'){render();return}load()});"
    fast_change = "E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;render();if(typeof renderExecutive==='function'&&document.body.classList.contains('ci-main-stats'))renderExecutive()});"
    if slow_change in text:
        text = text.replace(slow_change, fast_change, 1)

    # Compatibilidade caso alguma camada anterior deixe a assinatura antiga.
    slow_change_legacy = "E.viewSelect?.addEventListener('change',()=>{S.tab=E.viewSelect.value;S.visible=PAGE;load()});"
    if slow_change_legacy in text:
        text = text.replace(slow_change_legacy, fast_change, 1)

    css_anchor = "</style>"
    css_patch = r'''
/* Desktop alinhado ao padrão visual do DISMEPE ONE. Mobile permanece intacto. */
@media(min-width:761px){
  body{background:#f3f7f5}
  header{background:linear-gradient(135deg,#e1f1eb 0%,#eef7f3 100%);border-bottom:1px solid #cddfd9;box-shadow:0 3px 12px rgba(0,63,54,.055)}
  .top{max-width:1440px;padding:12px 22px}
  .brand{gap:14px}.brand img{width:172px;height:56px}.brand strong{font-size:15px}.brand small{font-size:8px}
  .back{height:40px;padding:0 14px;border-radius:10px;border-color:#c7d8d3;background:#fff;box-shadow:0 1px 2px rgba(0,63,54,.04)}
  main{max-width:1440px;padding:18px 22px 28px;gap:12px}

  .ci-main-tabs{position:static;top:auto;z-index:auto;gap:4px;padding:5px;border-radius:12px;border:1px solid #d7e5e0;box-shadow:0 2px 8px rgba(0,63,54,.035)}
  .ci-main-tab{height:39px;border-radius:8px;padding:0 16px;font-size:9px;letter-spacing:.01em}
  .ci-main-tab.active{background:#075b49;box-shadow:0 2px 5px rgba(7,91,73,.18)}

  #complementToolbar,.ci-list-tools,.panel,.exec-card,.kpi{border-color:#d8e5e1;box-shadow:0 2px 8px rgba(0,63,54,.035)}
  #complementToolbar{border-radius:12px;padding:10px 13px;background:#fff}
  .ci-list-tools{border-radius:12px;padding:13px 14px;gap:10px}
  .ci-list-tools-head{padding:0 1px}
  .ci-list-tools-head b{font-size:12px;color:#17332c}
  .ci-list-tools-head span{font-size:8px;color:#6b7f79}

  .ci-list-tools .filters{display:grid;grid-template-columns:minmax(270px,1.5fr) minmax(170px,.85fr) minmax(210px,1fr) minmax(125px,.65fr) auto auto;gap:8px;align-items:center}
  .ci-list-tools .filters>input,
  .ci-list-tools .filters>select,
  .ci-list-tools .filters>.multi,
  .ci-list-tools .filters>.export-btn{height:40px;min-width:0;width:100%}
  .ci-list-tools .filters input,
  .ci-list-tools .filters select,
  #viewSelect,.multi-btn,.export-btn{border-color:#cfddd8;background:#fbfdfc;border-radius:9px}
  .ci-list-tools .filters input:focus,
  .ci-list-tools .filters select:focus,
  #viewSelect:focus{outline:none;border-color:#0a8069;box-shadow:0 0 0 3px rgba(10,128,105,.09)}
  .multi-btn{height:40px}
  .export-btn{height:40px;padding:0 12px;background:#fff;color:#075b49}
  .export-btn:hover:not(:disabled){background:#edf7f3;border-color:#9fc5ba}
  .export-btn:disabled{opacity:.48;cursor:not-allowed}

  .ci-list-tools .adv-filters{display:flex;align-items:flex-end;gap:8px;flex-wrap:wrap;padding-top:10px;margin-top:0;border-top:1px solid #edf2f0}
  .ci-list-tools .adv-filters label:not(.check-filter){min-width:104px}
  .ci-list-tools .adv-filters input[type=number]{height:36px;width:104px;background:#fbfdfc;border-color:#d5e2de}
  .check-filter{height:36px;margin-top:0;border-radius:9px;background:#fbfdfc;border-color:#d5e2de}

  #ciProductsView>*+*{margin-top:10px}
  #ciProductsView .panel{border-radius:12px}
  #ciProductsView .panel-head{padding:14px 16px;background:#fff}
  #ciProductsView .panel-head h2{font-size:15px;color:#17332c}
  #ciProductsView .panel-head p{font-size:9px;color:#667b75}
  #ciProductsView .badge{padding:5px 9px;background:#eaf4f0;color:#075b49}
  #ciProductsView .table th{background:#edf5f2;color:#4f6962;padding:10px 9px;border-bottom-color:#d6e4df}
  #ciProductsView .table td{padding:9px;color:#213d36}
  #ciProductsView .table tbody tr:hover td{background:#f7fbf9}
  #ciProductsView .table-wrap{scrollbar-width:thin;scrollbar-color:#b8cbc5 transparent}
  #ciProductsView .pager{background:#f9fbfa;border-top-color:#e4ece9}

  #ciStatsView .kpis{gap:10px}
  #ciStatsView .kpi,#ciStatsView .exec-card{border-radius:12px}
  #ciStatsView .exec-grid{gap:10px}
}

@media(min-width:761px) and (max-width:1120px){
  .ci-list-tools .filters{grid-template-columns:2fr 1fr 1fr 1fr;}
  .ci-list-tools .filters>.export-btn{width:auto;min-width:96px}
}
'''
    if css_anchor in text:
        text = text.replace(css_anchor, css_patch + "\n" + css_anchor, 1)

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v21.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass

    _install_next_layer()
