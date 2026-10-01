from __future__ import annotations

import copy
from typing import Any


_INSTALLED = False
_KEEP_EXACT = {"FARMAX", "RS MED", "MEDEVICE", "FARMACE", "NEVE"}


def _supplier(row: dict[str, Any]) -> str:
    return str(row.get("fornecedor") or row.get("laboratorio") or "SEM FORNECEDOR").strip()


def _keep_zero_sales_supplier(name: str) -> bool:
    normalized = " ".join(str(name or "").upper().split())
    if normalized in _KEEP_EXACT:
        return True
    # No Mapa, KESTAL aparece com a razão social completa.
    return normalized.startswith("KESTAL")


def install_commercial_intelligence_zero_sales_filter() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence as ci

    original_analyze = ci._analyze

    def analyze_without_inactive_labs(payload: dict[str, Any], row_meta: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("linhas") if isinstance(payload.get("linhas"), list) else []
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}

        # Os três primeiros slots físicos correspondem, pela janela móvel do Mapa,
        # aos três últimos meses fechados. O quarto slot é o mês corrente.
        closed_slots = ci._SLOT_KEYS[:3]
        for row in rows:
            if not isinstance(row, dict):
                continue
            supplier = _supplier(row)
            counts[supplier] = counts.get(supplier, 0) + 1
            totals[supplier] = totals.get(supplier, 0.0) + sum(
                ci._num(row.get(slot)) for slot in closed_slots
            )

        hidden = {
            supplier
            for supplier, total in totals.items()
            if total == 0 and not _keep_zero_sales_supplier(supplier)
        }

        filtered_rows = [
            row
            for row in rows
            if isinstance(row, dict) and _supplier(row) not in hidden
        ]

        filtered_payload = copy.copy(payload)
        filtered_payload["linhas"] = filtered_rows
        result = original_analyze(filtered_payload, row_meta)
        if isinstance(result, dict):
            result["filtroLaboratoriosSemVenda"] = {
                "ativo": True,
                "mesesConsiderados": result.get("meses", [])[:3],
                "laboratoriosOcultos": len(hidden),
                "produtosOcultos": sum(counts.get(name, 0) for name in hidden),
                "excecoesMantidas": [
                    "FARMAX",
                    "KESTAL",
                    "RS MED",
                    "MEDEVICE",
                    "FARMACE",
                    "NEVE",
                ],
            }
        return result

    ci._analyze = analyze_without_inactive_labs
    _INSTALLED = True
