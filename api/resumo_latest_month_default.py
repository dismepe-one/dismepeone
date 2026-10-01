from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_RESUMO_LATEST_MONTH_DEFAULT_V3"


def install_resumo_latest_month_default() -> None:
    """Faz o Resumo de Ganhos abrir na competência mais recente cadastrada.

    A alteração é feita diretamente na função cm32PopulateMonthSelect do portal,
    evitando wrappers em window (a função original vive no escopo do próprio
    script). A opção "Todos os meses" continua disponível para escolha manual.
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

    old = """    if(previous&&[...sel.options].some(o=>o.value===previous)){\n      sel.value=previous;\n    }else if(ordered.includes(current)){\n      sel.value=current;\n    }else if(ordered.length){\n      sel.value=ordered[0];\n    }else{"""

    new = """    const previousExists=previous&&[...sel.options].some(o=>o.value===previous);\n\n    // No Resumo de Ganhos, o primeiro carregamento não deve preservar ALL.\n    // Usa sempre a competência mais recente realmente cadastrada. Depois que\n    // o usuário escolher outro mês manualmente, a seleção passa a ser mantida.\n    if(id==='sumPremMes' && (!previous || previous==='ALL')){\n      if(ordered.includes(current)){\n        sel.value=current;\n      }else if(ordered.length){\n        sel.value=ordered[0];\n      }else{\n        sel.value='ALL';\n      }\n    }else if(previousExists){\n      sel.value=previous;\n    }else if(ordered.includes(current)){\n      sel.value=current;\n    }else if(ordered.length){\n      sel.value=ordered[0];\n    }else{"""

    if old not in text:
        return

    patched = text.replace(old, new, 1)
    marker = "\n<!-- " + _MARKER + " -->\n"
    body_pos = patched.lower().rfind("</body>")
    if body_pos >= 0:
        patched = patched[:body_pos] + marker + patched[body_pos:]

    try:
        temp = portal.with_name(portal.name + ".resumo-latest-month.tmp")
        temp.write_text(patched, encoding="utf-8")
        temp.replace(portal)
    except Exception:
        pass
