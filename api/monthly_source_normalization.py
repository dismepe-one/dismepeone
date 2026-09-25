"""Normalizador independente das duas abas mensais do Google Sheets.

Nunca publica. Preserva as vendas atuais, inclusive mudanças legítimas na fonte.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any


class MonthlySourceInvalid(ValueError):
    pass


FOCUS_RE = re.compile(r"^(.*?)\s*[-–]?\s*Prod\.?\s*Foco\s*\(([^)]+)\)\s*$", re.I)


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).upper().strip()


def _numeric(value: Any, tab: str, line: int) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    if isinstance(value, bool):
        raise MonthlySourceInvalid(f"{tab}: número inválido na linha {line}.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MonthlySourceInvalid(f"{tab}: número inválido na linha {line}.") from exc
    if not result.is_finite():
        raise MonthlySourceInvalid(f"{tab}: número inválido na linha {line}.")
    return result


def sheet_to_monthly_rows(matrix: list[list[Any]], tab: str, comp: str) -> list[dict[str, Any]]:
    if tab not in ("CAMPANHA VEND", "CAMPANHAS TLVS"):
        raise MonthlySourceInvalid("Aba mensal desconhecida.")
    if not re.fullmatch(r"(0[1-9]|1[0-2])/20\d{2}", comp):
        raise MonthlySourceInvalid("Competência mensal inválida.")
    channel = "VENDEDOR" if tab == "CAMPANHA VEND" else "TELEVENDAS"
    if not matrix:
        raise MonthlySourceInvalid(f"Aba {tab} vazia.")
    header_at = -1
    columns = {}
    for i, row in enumerate(matrix[:100]):
        names = [normalized(v) for v in row]
        aliases = {
            "pessoa": ("VENDEDOR", "VENDEDORES", "TELEVENDAS", "TELEVENDA", "COLABORADOR"),
            "lab": ("LABORATORIO", "FORNECEDOR"),
            "objetivo": ("OBJETIVO", "META"),
            "venda": ("VENDA", "VENDAS", "REALIZADO", "FATURAMENTO"),
        }
        found = {
            field: [idx for idx, col in enumerate(names) if col in options]
            for field, options in aliases.items()
        }
        if all(len(hits) == 1 for hits in found.values()):
            header_at = i
            columns = {field: hits[0] for field, hits in found.items()}
            columns["premio"] = next(
                (idx for idx, col in enumerate(names) if col in ("PREMIACAO", "PREMIO")),
                None,
            )
            break
    if header_at < 0:
        raise MonthlySourceInvalid(f"Aba {tab} sem cabeçalho comercial válido.")
    entries = []
    for i, row in enumerate(matrix[header_at + 1:], start=header_at + 2):
        if not any(str(value or "").strip() for value in row):
            continue
        def cell(field: str) -> Any:
            pos = columns[field]
            return row[pos] if pos is not None and pos < len(row) else None
        name = str(cell("pessoa") or "").strip()
        supplier = str(cell("lab") or "").strip()
        if not name or not supplier:
            raise MonthlySourceInvalid(f"{tab}: colaborador ou laboratório ausente na linha {i}.")
        objective = _numeric(cell("objetivo"), tab, i)
        sale = _numeric(cell("venda"), tab, i)
        focus = FOCUS_RE.match(supplier)
        focus_code = focus.group(2).strip() if focus else ""
        if focus and not focus.group(1).strip():
            raise MonthlySourceInvalid(f"{tab}: linha de foco sem laboratório.")
        entries.append({
            "__COMPETENCIA": comp, "__CANAL": channel, "__COLABORADOR": name,
            "__LAB": supplier, "__linha": i, "__aba": tab,
            "__OBJETIVO": objective, "__VENDA": sale,
            "__TEM_FOCO": bool(focus), "__CODIGO_FOCO": focus_code,
            "__OBJETIVO_FOCO": objective if focus else Decimal(0),
            "__VENDA_FOCO": sale if focus else Decimal(0),
            "Premiação": cell("premio"),
        })
    if not entries:
        raise MonthlySourceInvalid(f"Aba {tab} sem registros comerciais.")
    return entries


def candidate_from_sheets(vendors: list[list[Any]], televendas: list[list[Any]],
                          comp: str) -> dict[str, Any]:
    return {
        "dadosVendedores": sheet_to_monthly_rows(vendors, "CAMPANHA VEND", comp),
        "dadosTelevendas": sheet_to_monthly_rows(televendas, "CAMPANHAS TLVS", comp),
    }
