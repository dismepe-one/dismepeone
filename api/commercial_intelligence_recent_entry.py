from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


_TZ = ZoneInfo("America/Recife")
_INSTALLED = False


def _parse_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw[:10], fmt).replace(tzinfo=_TZ)
        except ValueError:
            continue
    return None


def _days_since(value: Any) -> int | None:
    date = _parse_date(value)
    if date is None:
        return None
    today = datetime.now(_TZ).date()
    days = (today - date.date()).days
    return days if days >= 0 else None


def install_commercial_intelligence_recent_entry() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence as ci

    original_product = ci._product
    original_summary = ci._summary

    def product_with_recent_entry(row: dict[str, Any], labels: list[str]) -> dict[str, Any]:
        item = original_product(row, labels)
        days = _days_since(item.get("ultimaEntrada"))
        no_sales = float(item.get("mediaUnidades") or 0) <= 0
        has_stock = float(item.get("estoque") or 0) > 0

        # Regra comercial: entre 1 e 30 dias da última entrada, se ainda não
        # houve giro, o item continua em "Sem giro", mas recebe a observação
        # "PRODUTO NOVO". Não existe aba separada para produtos novos.
        is_new = bool(
            has_stock
            and no_sales
            and days is not None
            and 1 <= days <= 30
        )

        item["diasUltimaEntrada"] = days
        item["produtoNovo"] = is_new

        if is_new:
            item["semGiro"] = True
            item["observacao"] = "PRODUTO NOVO"
            item["acao"] = "PRODUTO NOVO / AGUARDAR GIRO"

            # Mantém o item na aba Sem giro, mas ele não é tratado como crítico
            # apenas pelo fato de ainda não ter vendido dentro da janela inicial.
            reasons = [
                reason
                for reason in (item.get("motivosCriticos") or [])
                if reason != "Estoque sem giro"
            ]
            item["motivosCriticos"] = reasons
            item["critico"] = bool(
                item.get("ruptura")
                or float(item.get("dde") or 0) >= 60
                or any("Venda caiu" in str(reason) for reason in reasons)
            )
        else:
            item["observacao"] = str(item.get("observacao") or "")

        rupture = bool(item.get("ruptura"))
        dde = float(item.get("dde") or 0)
        risk = bool(
            rupture
            or (
                has_stock
                and float(item.get("mediaUnidades") or 0) > 0
                and dde >= 30
            )
        )
        item["riscoRuptura"] = risk
        item["riscoRupturaAlto"] = bool(rupture or dde >= 60)
        if rupture:
            item["nivelRuptura"] = "RUPTURA"
        elif dde >= 60:
            item["nivelRuptura"] = "RISCO ALTO"
        elif dde >= 30:
            item["nivelRuptura"] = "RISCO"
        else:
            item["nivelRuptura"] = "NORMAL"
        return item

    def summary_with_recent_entry(products: list[dict[str, Any]]) -> dict[str, Any]:
        result = original_summary(products)
        result["novos"] = sum(1 for item in products if item.get("produtoNovo"))
        result["riscoRuptura"] = sum(1 for item in products if item.get("riscoRuptura"))
        result["riscoRupturaAlto"] = sum(1 for item in products if item.get("riscoRupturaAlto"))
        return result

    ci._product = product_with_recent_entry
    ci._summary = summary_with_recent_entry

    from .commercial_intelligence_zero_sales_filter import (
        install_commercial_intelligence_zero_sales_filter,
    )
    install_commercial_intelligence_zero_sales_filter()

    _INSTALLED = True
