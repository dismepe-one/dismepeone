from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_RESUMO_LATEST_MONTH_DEFAULT_V2"


def install_resumo_latest_month_default() -> None:
    """Pré-seleciona a competência mais recente disponível no Resumo de Ganhos.

    Mantém a opção "Todos os meses" disponível para escolha manual, mas na
    abertura/primeiro carregamento usa o último mês realmente cadastrado no
    snapshot do resumo. O patch é inserido antes do ÚLTIMO </body> do portal,
    evitando atingir templates HTML embutidos em strings JavaScript.
    """
    from . import main as main_module

    portal = getattr(main_module, "PORTAL_FILE", None)
    if not isinstance(portal, Path):
        return

    try:
        text = portal.read_text(encoding="utf-8")
    except Exception:
        return

    if _MARKER in text:
        return

    anchor = "</body>"
    position = text.lower().rfind(anchor)
    if position < 0:
        return

    patch = r'''
<script>
// DISMEPE_RESUMO_LATEST_MONTH_DEFAULT_V2
(function(){
  function install(){
    const original = window.cm32PopulateMonthSelect;
    if(typeof original !== 'function' || original.__dismepeLatestMonthDefault) return;

    function wrapped(id, rows){
      const sel = document.getElementById(id);
      const previous = sel ? String(sel.value || '') : '';

      original(id, rows);

      if(id !== 'sumPremMes' || !sel) return;

      // Só aplica o padrão quando o seletor ainda está no estado inicial.
      // Depois que o usuário escolhe outro mês, a escolha é preservada.
      if(previous && previous !== 'ALL') return;

      const months = Array.from(sel.options || [])
        .map(option => String(option.value || '').trim())
        .filter(value => value && value !== 'ALL')
        .sort((a,b) => b.localeCompare(a));

      if(months.length){
        sel.value = months[0];
      }
    }

    wrapped.__dismepeLatestMonthDefault = true;
    wrapped.__wrapped = original;
    window.cm32PopulateMonthSelect = wrapped;
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', install, {once:true});
  }else{
    install();
  }
})();
</script>
'''

    patched = text[:position] + patch + "\n" + text[position:]
    try:
        temp = portal.with_name(portal.name + ".resumo-latest-month.tmp")
        temp.write_text(patched, encoding="utf-8")
        temp.replace(portal)
    except Exception:
        pass
