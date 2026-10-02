from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


_TZ = ZoneInfo("America/Recife")
_INSTALLED = False

_MARKUP_KEYS = (
    "markup_medio", "markupMedio", "markup", "mkp_medio", "mkpMedio", "mkp",
    "markup médio", "markup medio", "markup_médio",
)
_LOT_KEYS = ("lote", "lote_produto", "loteProduto")
_EXPIRY_KEYS = (
    "vencimento", "validade", "data_validade", "dataValidade", "dt_validade",
    "data_vencimento", "dataVencimento",
)


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _parse_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    # O mapa complementar traz principalmente validade em MM/AAAA. Nesse
    # formato a validade comercial vai até o último dia do mês informado.
    try:
        month_text, year_text = raw.split("/", 1)
        if len(month_text) in (1, 2) and len(year_text) == 4:
            month = int(month_text)
            year = int(year_text)
            if 1 <= month <= 12:
                last_day = monthrange(year, month)[1]
                return datetime(year, month, last_day, tzinfo=_TZ)
    except (TypeError, ValueError):
        pass

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw[:10], fmt).replace(tzinfo=_TZ)
        except ValueError:
            continue
    return None


def _limit_12_months(now: datetime) -> datetime:
    year = now.year + (now.month - 1 + 12) // 12
    month = (now.month - 1 + 12) % 12 + 1
    day = min(now.day, monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def install_commercial_intelligence_portfolio_insights() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence as ci

    original_product = ci._product
    original_analyze = ci._analyze

    def product_with_future_fields(row: dict[str, Any], labels: list[str]) -> dict[str, Any]:
        item = original_product(row, labels)

        markup_raw = _first(row, _MARKUP_KEYS)
        markup = max(0.0, ci._num(markup_raw)) if markup_raw not in (None, "") else 0.0
        lot = str(_first(row, _LOT_KEYS) or "").strip()
        expiry_raw = _first(row, _EXPIRY_KEYS)
        expiry = str(expiry_raw or "").strip()
        expiry_date = _parse_date(expiry_raw)
        now = datetime.now(_TZ)
        days_expiry: int | None = None
        expiry_near = False
        expired = False
        if expiry_date is not None:
            days_expiry = (expiry_date.date() - now.date()).days
            expiry_near = now.date() <= expiry_date.date() <= _limit_12_months(now).date()
            expired = expiry_date.date() < now.date()

        item["markupMedio"] = ci._round(markup, 2)
        item["temMarkup"] = bool(markup_raw not in (None, "") and markup > 0)
        item["lote"] = lot
        item["vencimento"] = expiry
        item["diasVencimento"] = days_expiry
        # Regra comercial: considera próximo do vencimento todo produto com
        # validade entre hoje e os próximos 12 meses de calendário.
        item["vencimentoProximo"] = expiry_near
        item["vencido"] = expired
        return item

    def analyze_with_insights(payload: dict[str, Any], row_meta: dict[str, Any]) -> dict[str, Any]:
        result = original_analyze(payload, row_meta)
        products = [item for item in (result.get("produtos") or []) if isinstance(item, dict)]
        suppliers = [item for item in (result.get("fornecedores") or []) if isinstance(item, dict)]

        markup_values = [float(item.get("markupMedio") or 0) for item in products if item.get("temMarkup")]
        median_markup = float(median(markup_values)) if markup_values else 0.0

        weighted_markup_num = 0.0
        weighted_markup_den = 0.0
        for item in products:
            markup = float(item.get("markupMedio") or 0)
            if markup <= 0:
                continue
            weight = max(1.0, float(item.get("mediaUnidades") or 0))
            weighted_markup_num += markup * weight
            weighted_markup_den += weight
        weighted_markup = weighted_markup_num / weighted_markup_den if weighted_markup_den else 0.0

        value_no_turn = sum(float(item.get("valorEstoque") or 0) for item in products if item.get("semGiro"))
        value_risk = sum(float(item.get("valorEstoque") or 0) for item in products if item.get("riscoRuptura"))
        new_count = sum(1 for item in products if item.get("produtoNovo"))
        expiring_count = sum(1 for item in products if item.get("vencimentoProximo"))
        expired_count = sum(1 for item in products if item.get("vencido"))

        for item in products:
            stock = float(item.get("estoque") or 0)
            avg = float(item.get("mediaUnidades") or 0)
            markup = float(item.get("markupMedio") or 0)
            high_markup = bool(median_markup > 0 and markup >= median_markup)
            low_markup = bool(median_markup > 0 and 0 < markup < median_markup)

            opportunity = "MONITORAR"
            priority = "NORMAL"
            if item.get("ruptura"):
                opportunity = "GARANTIR ESTOQUE"
                priority = "URGENTE"
            elif item.get("riscoRupturaAlto") or item.get("riscoRuptura"):
                opportunity = "GARANTIR ESTOQUE"
                priority = "ALTA"
            elif item.get("semGiro") and not item.get("produtoNovo"):
                opportunity = "CAPITAL PARADO / AÇÃO DE GIRO"
                priority = "ALTA" if stock > 0 else "NORMAL"
            elif item.get("baixo") and item.get("estoqueAlto"):
                opportunity = "ACELERAR VENDA"
                priority = "ALTA"
            elif item.get("alta") and low_markup:
                opportunity = "REVER PREÇO / MARGEM"
                priority = "OPORTUNIDADE"
            elif item.get("alta") and high_markup:
                opportunity = "PRODUTO ESTRELA"
                priority = "OPORTUNIDADE"
            elif (item.get("baixo") or item.get("semGiro")) and high_markup:
                opportunity = "MARGEM ALTA / GIRO BAIXO"
                priority = "OPORTUNIDADE"
            elif item.get("alta"):
                opportunity = "MONITORAR ACELERAÇÃO"
                priority = "OPORTUNIDADE"
            elif item.get("produtoNovo"):
                opportunity = "PRODUTO NOVO / AGUARDAR GIRO"
                priority = "MONITORAR"

            if item.get("vencido"):
                opportunity = "VERIFICAR VENCIMENTO"
                priority = "URGENTE"
            elif item.get("vencimentoProximo") and priority not in ("URGENTE",):
                opportunity = "PRIORIZAR GIRO ANTES DO VENCIMENTO"
                priority = "ALTA"

            item["oportunidade"] = opportunity
            item["prioridade"] = priority
            item["markupAcimaMediana"] = high_markup
            item["markupAbaixoMediana"] = low_markup
            item["indiceGiro"] = ci._round(avg, 2)

        top_drop = sorted(
            [item for item in products if item.get("baixo")],
            key=lambda item: float(item.get("variacaoPct") or 0),
        )[:15]
        top_high = sorted(
            [item for item in products if item.get("alta")],
            key=lambda item: float(item.get("variacaoPct") or 0),
            reverse=True,
        )[:15]
        top_stock_suppliers = sorted(
            suppliers,
            key=lambda item: float(item.get("valorEstoque") or 0),
            reverse=True,
        )[:15]
        upcoming_expiry = sorted(
            [item for item in products if item.get("diasVencimento") is not None],
            key=lambda item: int(item.get("diasVencimento") or 0),
        )[:15]

        status_counts = {
            "riscoRuptura": sum(1 for item in products if item.get("riscoRuptura")),
            "semGiro": sum(1 for item in products if item.get("semGiro") and not item.get("produtoNovo")),
            "produtoNovo": new_count,
            "emQueda": sum(1 for item in products if item.get("baixo")),
            "emAlta": sum(1 for item in products if item.get("alta")),
            "vencimentoProximo": expiring_count,
        }
        flagged = {
            id(item)
            for item in products
            if item.get("riscoRuptura") or item.get("semGiro") or item.get("produtoNovo")
            or item.get("baixo") or item.get("alta") or item.get("vencimentoProximo")
        }
        status_counts["normal"] = max(0, len(products) - len(flagged))

        opportunity_groups = {
            "garantirEstoque": [item for item in products if item.get("oportunidade") == "GARANTIR ESTOQUE"],
            "acelerarVenda": [item for item in products if item.get("oportunidade") == "ACELERAR VENDA"],
            "capitalParado": [item for item in products if str(item.get("oportunidade") or "").startswith("CAPITAL PARADO")],
            "produtoEstrela": [item for item in products if item.get("oportunidade") == "PRODUTO ESTRELA"],
            "reverPreco": [item for item in products if item.get("oportunidade") == "REVER PREÇO / MARGEM"],
            "margemAltaGiroBaixo": [item for item in products if item.get("oportunidade") == "MARGEM ALTA / GIRO BAIXO"],
            "vencimento": [item for item in products if item.get("vencimentoProximo") or item.get("vencido")],
        }

        summary = result.get("resumo") if isinstance(result.get("resumo"), dict) else {}
        summary.update({
            "produtosNovos": new_count,
            "valorSemGiro": ci._round(value_no_turn),
            "valorRiscoRuptura": ci._round(value_risk),
            "markupMedioPonderado": ci._round(weighted_markup, 2),
            "produtosComMarkup": len(markup_values),
            "vencimentoProximo": expiring_count,
            "vencidos": expired_count,
        })
        result["resumo"] = summary
        result["insights"] = {
            "topQueda": top_drop,
            "topAlta": top_high,
            "topEstoqueFornecedores": top_stock_suppliers,
            "status": status_counts,
            "markupDisponivel": bool(markup_values),
            "markupMediana": ci._round(median_markup, 2),
            "vencimentoDisponivel": any(item.get("vencimento") for item in products),
            "loteDisponivel": any(item.get("lote") for item in products),
            "proximosVencimentos": upcoming_expiry,
            "oportunidades": {
                key: {
                    "quantidade": len(items),
                    "produtos": items[:15],
                }
                for key, items in opportunity_groups.items()
            },
        }
        return result

    ci._product = product_with_future_fields
    ci._analyze = analyze_with_insights
    _INSTALLED = True
