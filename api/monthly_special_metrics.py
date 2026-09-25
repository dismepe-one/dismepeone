"""Recalculate only monthly GLOBO/HERBAMED/BRG special indicators.

Read-only Sheets input. The HOME publisher alone persists the resulting snapshot.
Never changes sales, targets, financial rules, historical months or RESUMO_PREMIACOES.
"""
from __future__ import annotations

import asyncio
import copy
import os
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .monthly_commercial_live import _credentials, current_source, CommercialSyncError


class SpecialMetricsError(RuntimeError):
    pass


_SHEET = "1P2NgRBt9e3MnMQD1K-O42Pv8tN6wPkpK2GcL9FFpNsM"
_RANGES = {
    "GLOBO_CLIENTES": ("A1:F5000", ("VENDEDOR", "COD CLIENTE", "CLIENTE", "PEDIDOS POR", "POSITIVACAO", "DATA")),
    "METRICA_GLOBO": ("A1:D500", ("VENDEDOR TELEVENDAS", "TIPO", "META CLIENTES", "PREMIO")),
    "HERB_COM": ("A1:K5000", ("VENDEDOR", "CLIENTE", "COD CLIENTE", "CNPJ", "FORNECEDOR", "PRODUTO", "COD PRODUTO", "DATA", "TOTAL UNIDADE", "VENDA LIQUIDA R", "PEDIDOS POR")),
    "INT_PONTOS": ("A1:F5000", ("DATA", "PEDIDOS POR", "VENDEDOR", "COD PRODUTO", "TOTAL UNIDADE", "FATURADO")),
    "INTEGRAL_PRODUTOS": ("A1:C1000", ("COD PRODUTO", "PRODUTO", "PONTOS")),
    "INTEGRAL_FAIXAS": ("A1:B500", ("PONTOS", "PREMIO")),
}


def norm(value: Any) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in value if not unicodedata.combining(c)).upper())


def channel(value: Any) -> str:
    value = norm(value)
    if value in ("TELEVENDAS", "TELEVENDA", "TLV", "TLVS"):
        return "T"
    if value in ("ELETRONICO", "ELETRONICA", "VENDEDOR", "VENDEDORES", "V"):
        return "V"
    return ""


def month(value: Any) -> str:
    value = str(value or "").strip()
    m = re.fullmatch(r"\d{2}/(\d{2})/(20\d{2})", value)
    return f"{m[1]}/{m[2]}" if m else ""


def number(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise SpecialMetricsError("Indicador numerico ausente ou invalido.")
    raw = str(value).replace("R$", "").replace(" ", "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        n = Decimal(raw)
    except InvalidOperation as exc:
        raise SpecialMetricsError("Indicador numerico invalido.") from exc
    if not n.is_finite() or n < 0:
        raise SpecialMetricsError("Indicador numerico invalido.")
    return n


def integer(value: Any) -> int:
    n = number(value)
    if n != n.to_integral_value():
        raise SpecialMetricsError("Quantidade nao inteira.")
    return int(n)


def read_sources() -> dict[str, list[list[Any]]]:
    # Reuse the exclusive monthly reader already validated in production.
    # The industries Drive account may be different and cannot be assumed
    # to have permission to read the administrative campaign workbook.
    try:
        info = _credentials()
    except CommercialSyncError as exc:
        raise SpecialMetricsError(
            "O leitor Google mensal exclusivo nao esta configurado para consultar "
            "as bases auxiliares de positivacao."
        ) from exc
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    cred = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    client = build("sheets", "v4", credentials=cred, cache_discovery=False)
    sid = os.getenv("DISMEPE_SPECIAL_METRICS_SHEET_ID", _SHEET).strip() or _SHEET
    result = client.spreadsheets().values().batchGet(
        spreadsheetId=sid,
        ranges=[f"'{name}'!{spec[0]}" for name, spec in _RANGES.items()],
        valueRenderOption="FORMATTED_VALUE",
    ).execute(num_retries=2)
    matrices = result.get("valueRanges") or []
    if len(matrices) != len(_RANGES):
        raise SpecialMetricsError("Bases auxiliares incompletas.")
    out = {}
    for (name, (_bounds, header)), entry in zip(_RANGES.items(), matrices):
        vals = entry.get("values") or []
        if not vals or tuple(norm(x) for x in vals[0][:len(header)]) != tuple(norm(x) for x in header):
            raise SpecialMetricsError("Cabecalho auxiliar inesperado: " + name)
        out[name] = vals[1:]
    return out


def unique_clients(rows, comp: str, herb: bool = False):
    unique = defaultdict(set)
    for row in rows:
        if len(row) < (11 if herb else 6) or month(row[7 if herb else 5]) != comp:
            continue
        c = channel(row[10 if herb else 3])
        if not c or (not herb and str(row[4]).strip() not in ("1", "1.0")):
            continue
        name = norm(row[0])
        code = str((row[2] or row[3]) if herb else row[1]).strip()
        if c and name and code:
            unique[(c, name)].add(code)
    if not unique:
        raise SpecialMetricsError("Sem positivacoes validas para a competencia.")
    return {key: len(value) for key, value in unique.items()}


def integral_sources(tables, comp):
    products = {}
    for row in tables["INTEGRAL_PRODUTOS"]:
        if len(row) >= 3 and str(row[0]).strip():
            products[str(row[0]).strip()] = (str(row[1]).strip(), number(row[2]))
    tiers = {}
    for row in tables["INTEGRAL_FAIXAS"]:
        if len(row) >= 2 and str(row[0]).strip():
            tiers[integer(row[0])] = number(row[1])
    if not products or not tiers:
        raise SpecialMetricsError("Configuracao Integral incompleta.")
    quantities = defaultdict(lambda: defaultdict(int))
    for row in tables["INT_PONTOS"]:
        # Invalid rows are ignored individually, not the entire base.
        if len(row) < 6 or month(row[0]) != comp or norm(row[5]) not in ("SIM", "FATURADO", "FATURADA"):
            continue
        c, name, code = channel(row[1]), norm(row[2]), str(row[3]).strip()
        if not c or not name or code not in products:
            continue
        try:
            qty = integer(row[4])
        except SpecialMetricsError:
            continue
        quantities[(c, name)][code] += qty
    if not quantities:
        raise SpecialMetricsError("Sem produtos Integral validos na competencia.")
    points = {key: sum((Decimal(q) * products[code][1] for code, q in items.items()), Decimal(0))
              for key, items in quantities.items()}
    return products, tiers, quantities, points, sum(points.values(), Decimal(0))


def lab_of(row):
    lab = norm(row.get("__LAB") or row.get("lab"))
    if lab.startswith("GLOBO"):
        return "GLOBO"
    if lab.startswith("HERBAMED"):
        return "HERBAMED"
    if lab.startswith(("BRG", "INTEGRAL")):
        return "INTEGRAL"
    return ""


def calculate(payload: dict, sources: dict) -> dict:
    """Pure calculation; no I/O or writes, returns copy only if all sources validate."""
    try:
        comp, _ = current_source(payload)
    except CommercialSyncError as exc:
        raise SpecialMetricsError("Competencia atual nao confirmada.") from exc
    globo = unique_clients(sources["GLOBO_CLIENTES"], comp)
    herb = unique_clients(sources["HERB_COM"], comp, herb=True)
    goals = {}
    for r in sources["METRICA_GLOBO"]:
        if len(r) < 4 or not norm(r[0]) or not channel(r[1]):
            continue
        key = (channel(r[1]), norm(r[0]))
        if key in goals:
            raise SpecialMetricsError("Meta Globo duplicada.")
        goals[key] = (integer(r[2]), number(r[3]))
    products, tiers, quantities, points, overall = integral_sources(sources, comp)
    if not goals:
        raise SpecialMetricsError("Metas Globo ausentes.")
    out = copy.deepcopy(payload)
    processed = {lab: 0 for lab in ("GLOBO", "HERBAMED", "INTEGRAL")}
    for field, c in (("dadosVendedores", "V"), ("dadosTelevendas", "T")):
        if not isinstance(out.get(field), list):
            raise SpecialMetricsError("Parciais mensais incompletas.")
        for row in out[field]:
            if not isinstance(row, dict) or str(row.get("__COMPETENCIA") or row.get("competencia") or "") != comp:
                continue
            lab = lab_of(row)
            if not lab:
                continue
            detail = row.get("metricasParcial")
            if not isinstance(detail, dict) or not isinstance(detail.get("componentes"), list):
                raise SpecialMetricsError("Metricas especiais ausentes: " + lab)
            key = (c, norm(row.get("__COLABORADOR") or row.get("colab")))
            changed = False
            for part in detail["componentes"]:
                if not isinstance(part, dict):
                    continue
                metric = str(part.get("metrica") or "").upper()
                if lab == "GLOBO" and metric == "POSITIVACAO_CLIENTES":
                    if key not in goals or goals[key][0] <= 0:
                        raise SpecialMetricsError("Meta individual Globo ausente.")
                    target, prize = goals[key]
                    actual = globo.get(key, 0)
                    part.update(meta=target, realizado=actual, premio=float(prize if actual >= target else 0),
                                premioConfigurado=float(prize), pendente=False, motivo="")
                    changed = True
                elif lab == "HERBAMED" and metric == "POSITIVACAO_CLIENTES":
                    target = integer(part.get("meta"))
                    prize = number(part.get("premioConfigurado"))
                    if target <= 0:
                        raise SpecialMetricsError("Meta individual Herbamed invalida.")
                    actual = herb.get(key, 0)
                    part.update(realizado=actual, premio=float((actual // target) * prize), pendente=False, motivo="")
                    changed = True
                elif lab == "INTEGRAL" and metric == "PONTUACAO_PRODUTO":
                    actual = points.get(key, Decimal(0))
                    gate = number(part.get("metaPontosGerais"))
                    if gate <= 0:
                        raise SpecialMetricsError("Gatilho Integral ausente.")
                    prize = Decimal(0)
                    for threshold, award in sorted(tiers.items()):
                        if actual >= threshold:
                            prize = award
                    if overall < gate:
                        prize = Decimal(0)
                    items = [{"codigo": code, "produto": products[code][0], "quantidade": qty,
                              "pontos": float(Decimal(qty) * products[code][1])}
                             for code, qty in sorted(quantities.get(key, {}).items())]
                    part.update(meta=min(tiers), realizado=float(actual), pontosGerais=float(overall),
                                gatilhoGeralOK=overall >= gate, premio=float(prize), pendente=False,
                                motivo="", produtosPositivados=items, totalProdutosPositivados=len(items),
                                faixas=[{"pontos": t, "premio": float(v)} for t, v in sorted(tiers.items())])
                    changed = True
            if changed:
                total = sum((number(p.get("premio", 0)) for p in detail["componentes"]), Decimal(0))
                detail["valor"] = float(total)
                detail["pendente"] = any(p.get("pendente") is True for p in detail["componentes"])
                detail["motivo"] = " | ".join(
                    str(p.get("motivo") or "") for p in detail["componentes"] if p.get("pendente")
                )
                if len(detail["componentes"]) == 1:
                    metric = detail["componentes"][0]
                    detail["realizado"] = metric.get("realizado")
                    target = number(metric.get("meta"))
                    detail["atingimento"] = (
                        float(number(metric.get("realizado")) / target * 100) if target else 0
                    )
                rule = detail.get("regra")
                if isinstance(rule, dict):
                    rule["valor"] = float(total)
                    rule["observacao"] = " | ".join(
                        f"{p.get('criterio') or p.get('metrica')}: {p.get('realizado')} / {p.get('meta')}"
                        for p in detail["componentes"])
                row["metricasDetalhes"] = detail["componentes"]
                row["metricaPendente"] = detail["pendente"]
                row["Premiação"] = float(total)
                row["premiacao"] = float(total)
                row["premiacaoComBaseAnterior"] = True
                processed[lab] += 1
    if any(not value for value in processed.values()):
        raise SpecialMetricsError("Metricas especiais incompletas.")
    out["metricasEspeciais"] = {"competencia": comp, "fonte": "BASES_DISMEPE_ONE",
                               "linhasProcessadas": processed, "resumoFinanceiro": "LEGADO_PRESERVADO"}
    return out


async def enrich_special_metrics(payload: dict) -> dict:
    sources = await asyncio.wait_for(asyncio.to_thread(read_sources), timeout=40)
    return calculate(payload, sources)
