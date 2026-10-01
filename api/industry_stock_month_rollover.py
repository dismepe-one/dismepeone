from __future__ import annotations

import copy
from typing import Any


_INSTALLED = False


def _remap_stock_months(payload: Any) -> Any:
    """Converte o layout legado de 4 colunas para JUL/AGO/SET/OUT.

    O PDF atual do Átrio já avançou a janela mensal, mas o parser ainda grava
    as quatro posições com os nomes antigos jun_26/jul_26/ago_26/set_26.
    A ordem física no PDF permanece correta; portanto a correção segura é
    somente renomear as posições na leitura, sem alterar nenhum valor.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("linhas"), list):
        return payload

    out = copy.deepcopy(payload)
    for row in out.get("linhas") or []:
        if not isinstance(row, dict):
            continue
        old_jun = row.get("jun_26")
        old_jul = row.get("jul_26")
        old_ago = row.get("ago_26")
        old_set = row.get("set_26")

        row["jul_26"] = old_jun
        row["ago_26"] = old_jul
        row["set_26"] = old_ago
        row["out_26"] = old_set
        row.pop("jun_26", None)

    out["mesesVendas"] = ["JUL/26", "AGO/26", "SET/26", "OUT/26"]
    out["mapaMesesCorrigidos"] = True
    out["layoutMeses"] = "JUL_AGO_SET_OUT_2026"
    return out


def install_industry_stock_month_rollover() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from . import industries as industries_module
    except Exception:
        return

    original = getattr(industries_module, "_load_stock", None)
    if not callable(original) or getattr(original, "__dismepe_month_rollover__", False):
        return

    async def wrapped_load_stock(*args, **kwargs):
        payload = await original(*args, **kwargs)
        return _remap_stock_months(payload)

    wrapped_load_stock.__dismepe_month_rollover__ = True
    wrapped_load_stock.__wrapped__ = original
    industries_module._load_stock = wrapped_load_stock

    # O cache interno pode conter a fotografia anterior já lida pelo processo.
    # Zerá-lo força a próxima consulta a passar pela camada corrigida.
    if hasattr(industries_module, "_STOCK_SNAPSHOT_CACHE"):
        industries_module._STOCK_SNAPSHOT_CACHE = None

    _INSTALLED = True
