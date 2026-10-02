from __future__ import annotations

from typing import Any


_INSTALLED = False


def install_commercial_intelligence_dde_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence as ci

    original_product = ci._product
    original_analyze = ci._analyze

    def product_with_correct_dde(row: dict[str, Any], labels: list[str]) -> dict[str, Any]:
        item = original_product(row, labels)

        stock = max(0.0, float(item.get("estoque") or 0))
        avg = max(0.0, float(item.get("mediaUnidades") or 0))
        dde = (stock / avg) * 30.0 if avg > 0 else 0.0
        dde = ci._round(dde, 1)
        item["dde"] = dde

        rupture = bool(stock <= 0 and avg > 0)
        risk_high = bool(stock > 0 and avg > 0 and dde <= 15)
        risk = bool(rupture or (stock > 0 and avg > 0 and dde <= 30))
        high_stock = bool(avg > 0 and stock >= avg * 4)

        item["ruptura"] = rupture
        item["riscoRuptura"] = risk
        item["riscoRupturaAlto"] = bool(rupture or risk_high)
        item["pressaoEstoque"] = risk
        item["estoqueAlto"] = high_stock

        if rupture:
            item["nivelRuptura"] = "RUPTURA"
        elif risk_high:
            item["nivelRuptura"] = "RISCO ALTO"
        elif risk:
            item["nivelRuptura"] = "RISCO"
        else:
            item["nivelRuptura"] = "NORMAL"

        low_sales = bool(item.get("baixo"))
        high_sales = bool(item.get("alta"))
        no_turnover = bool(item.get("semGiro"))
        is_new = bool(item.get("produtoNovo"))

        old_reasons = [
            str(reason)
            for reason in (item.get("motivosCriticos") or [])
            if str(reason) not in {
                "Pressão alta de venda sobre o estoque",
                "Sem estoque com histórico de venda",
            }
        ]
        if is_new:
            old_reasons = [reason for reason in old_reasons if reason != "Estoque sem giro"]

        reasons: list[str] = []
        if rupture:
            reasons.append("Sem estoque com histórico de venda")
        if risk_high:
            reasons.append("Cobertura de estoque igual ou inferior a 15 dias")
        reasons.extend(reason for reason in old_reasons if reason not in reasons)
        item["motivosCriticos"] = reasons
        item["critico"] = bool(reasons)

        if rupture:
            item["acao"] = "REPOR / VERIFICAR RUPTURA"
        elif risk_high or (high_sales and stock < max(1.0, avg)):
            item["acao"] = "GARANTIR ESTOQUE"
        elif is_new:
            item["acao"] = "PRODUTO NOVO / AGUARDAR GIRO"
        elif no_turnover:
            item["acao"] = "AÇÃO DE GIRO"
        elif low_sales and high_stock:
            item["acao"] = "AÇÃO COMERCIAL + REVER ESTOQUE"
        elif low_sales:
            item["acao"] = "INVESTIGAR QUEDA"
        elif high_sales:
            item["acao"] = "MONITORAR ACELERAÇÃO"
        elif high_stock:
            item["acao"] = "REVER COBERTURA"
        else:
            item["acao"] = "MONITORAR"
        return item

    def analyze_with_correct_formula(payload: dict[str, Any], row_meta: dict[str, Any]) -> dict[str, Any]:
        result = original_analyze(payload, row_meta)
        result["formulaDDE"] = "estoque ÷ média de unidades vendidas × 30; sem média de venda, resultado 0"
        return result

    ci._product = product_with_correct_dde
    ci._analyze = analyze_with_correct_formula
    _INSTALLED = True
