from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_PULSY_PRODUCT_NAMES_V1"


def install_pulsy_product_names_display() -> None:
    """Mostra o nome individual de cada produto na métrica PULSY.

    O overlay PULSY já entrega `criterio` com o nome do produto em cada
    componente. Esta camada altera somente o rótulo visual do detalhe,
    preservando cálculo, gatilhos, quantidades e premiações.
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

    old = "<b>${v171Escape(labels[c.metrica]||c.metrica)}</b>"
    new = "<b>${v171Escape(unitPrize?(c.criterio||'Produto PULSY'):(labels[c.metrica]||c.metrica))}</b>"

    if old not in text:
        return

    text = text.replace(old, new, 1)
    marker_anchor = "// DISMEPE_PULSY_UNITS_V1"
    if marker_anchor in text:
        text = text.replace(marker_anchor, marker_anchor + "\n// " + _MARKER, 1)
    else:
        text = "<!-- " + _MARKER + " -->\n" + text

    try:
        temp = portal.with_name(portal.name + ".pulsy-names.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(portal)
    except Exception:
        pass
