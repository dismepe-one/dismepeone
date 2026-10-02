from __future__ import annotations

import re
from typing import Any


_INSTALLED = False


def _qty_integer(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        # Valores novos do parser já chegam inteiros. Para compatibilidade,
        # preserva números sem fração e arredonda apenas valores numéricos reais.
        return max(0, int(round(value)))
    raw = str(value).strip()
    # No relatório Qtd é unidade inteira e ponto/vírgula são separadores de milhar.
    digits = re.sub(r"[^0-9-]", "", raw)
    if not digits or digits == "-":
        return 0
    try:
        return max(0, int(digits))
    except ValueError:
        return 0


def install_commercial_intelligence_quantity_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence_complement_pdf as pdfmod
    from . import commercial_intelligence_complement as cc

    original_parse = pdfmod._parse_product_line
    original_product = cc.install_commercial_intelligence_complement

    def parse_product_line_integer_qty(line: str):
        parsed = original_parse(line)
        if not isinstance(parsed, dict):
            return parsed

        # Reextrai Qtd diretamente do trecho anterior a Venc. para não passar
        # pela conversão decimal genérica usada em preços.
        match = re.match(
            r"\s*(\d{1,3}(?:\.\d{3})*|\d+)(.*?)([A-Z]/[A-Z])\s*(.*)$",
            str(line or ""),
        )
        if not match:
            return parsed
        rest = match.group(4)
        entry = re.search(r"(\d{2}/\d{2}/\d{2})", rest)
        if not entry:
            return parsed
        after_entry = rest[entry.end():].strip()
        expiry_match = re.search(r"(\d{2}/\d{4})", after_entry)
        if not expiry_match:
            parsed["quantidadeUltimaEntrada"] = 0
            return parsed
        prefix = after_entry[:expiry_match.start()]
        qty_match = re.search(r"(-?\d[\d.,]*)\s*$", prefix)
        parsed["quantidadeUltimaEntrada"] = _qty_integer(qty_match.group(1) if qty_match else 0)
        return parsed

    pdfmod._parse_product_line = parse_product_line_integer_qty

    # O parser resiliente importa _parse_product_line em tempo de execução;
    # portanto passa a usar automaticamente esta versão corrigida.
    _INSTALLED = True
