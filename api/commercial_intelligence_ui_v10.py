from __future__ import annotations

from pathlib import Path


_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_UI_V10"


def install_commercial_intelligence_ui_v10() -> None:
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

    # Deixa explícito que a promoção pode ser apagada manualmente a qualquer
    # momento, independentemente de ter sido exportada ou não.
    text = text.replace(
        '<button id="promoDelete" class="promo-btn danger-btn"><i class="fa-solid fa-trash"></i> Excluir</button>',
        '<button id="promoDelete" class="promo-btn danger-btn" title="Excluir esta promoção imediatamente"><i class="fa-solid fa-trash"></i> Excluir agora</button>',
        1,
    )

    # Confirmação reforçada antes da exclusão definitiva.
    text = text.replace(
        "if(!p||!confirm('Excluir esta promoção?'))return;",
        "if(!p||!confirm(`Deseja realmente excluir a promoção \\\"${p.name||'Promoção'}\\\"? A exclusão será imediata e não poderá ser desfeita.`))return;",
        1,
    )

    # Observação na área de expiração: a limpeza automática não impede a
    # exclusão manual antes ou depois da exportação.
    text = text.replace(
        'Após exportar, esta promoção será excluída automaticamente em até 24 horas.',
        'Após exportar, esta promoção será excluída automaticamente em até 24 horas. Você também pode usar “Excluir agora” a qualquer momento.',
        1,
    )

    marker = "\n<!-- " + _MARKER + " -->\n"
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + marker + text[pos:]

    try:
        temp = page.with_name(page.name + ".intelligence-ui-v10.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(page)
    except Exception:
        pass
