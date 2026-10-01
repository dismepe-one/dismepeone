from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from .cache_reads import CacheReadError, cache_get


_INSTALLED = False


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _lab(value: Any) -> str:
    key = _norm(value)
    if key.startswith("GLOBO"):
        return "GLOBO"
    if key.startswith("HERBAMED"):
        return "HERBAMED"
    if key.startswith("BRG") or key.startswith("INTEGRAL"):
        return "BRG SUPLEMENTOS NUTRICIONAIS LTDA"
    return key


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text or text.startswith("#"):
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def _row_key(setor: str, row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        setor,
        _norm(row.get("__COLABORADOR") or row.get("colab") or row.get("colaborador")),
        _lab(row.get("__LAB") or row.get("lab") or row.get("laboratorio")),
        str(row.get("__COMPETENCIA") or row.get("competencia") or "").strip(),
    )


def _record_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("setor") or "").strip(),
        _norm(row.get("colaborador")),
        _lab(row.get("laboratorio")),
        str(row.get("competencia") or "").strip(),
    )


def _published_metrics(publication: dict[str, Any]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    monthly = publication.get("mensal")
    if not isinstance(monthly, dict):
        return {}

    indexed: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for field, sector in (("dadosVendedores", "Vendedor"), ("dadosTelevendas", "Televendas")):
        rows = monthly.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            detail = row.get("metricasParcial")
            if not isinstance(detail, dict):
                continue
            prize = _number(detail.get("valor"))
            if prize is None:
                continue
            key = _row_key(sector, row)
            if not key[1] or not key[2] or not key[3]:
                continue
            indexed[key] = {
                "premiacao": round(prize, 2),
                "metricasParcial": copy.deepcopy(detail),
                "metricasDetalhes": copy.deepcopy(
                    row.get("metricasDetalhes")
                    if isinstance(row.get("metricasDetalhes"), list)
                    else detail.get("componentes")
                    if isinstance(detail.get("componentes"), list)
                    else []
                ),
                "metricaPendente": bool(detail.get("pendente")),
                "motivoMetrica": str(detail.get("motivo") or ""),
                "metricaValor": round(prize, 2),
                "atingimento": _number(detail.get("atingimento")),
                "regra": copy.deepcopy(detail.get("regra")) if isinstance(detail.get("regra"), dict) else None,
            }
    return indexed


def _prize(row: dict[str, Any]) -> float:
    value = _number(row.get("premiacao"))
    return round(value or 0.0, 2)


def _rebuild_totals(payload: dict[str, Any]) -> None:
    rows = [item for item in payload.get("registros") or [] if isinstance(item, dict)]
    awarded = [
        item for item in rows
        if _prize(item) > 0 or str(item.get("premioTexto") or "").strip()
    ]

    def total(items, sector: str | None = None) -> float:
        return round(sum(
            _prize(item) for item in items
            if sector is None or str(item.get("setor") or "") == sector
        ), 2)

    payload["totais"] = {
        "total": total(rows),
        "vendedores": total(rows, "Vendedor"),
        "televendas": total(rows, "Televendas"),
        "colaboradores": len({
            (str(item.get("setor") or ""), _norm(item.get("colaborador")))
            for item in awarded if _norm(item.get("colaborador"))
        }),
        "laboratorios": len({
            _lab(item.get("laboratorio")) for item in awarded if _lab(item.get("laboratorio"))
        }),
    }

    collaborator_totals: dict[tuple[str, str], dict[str, Any]] = {}
    for item in awarded:
        sector = str(item.get("setor") or "")
        name = str(item.get("colaborador") or "").strip()
        key = (sector, _norm(name))
        if not key[1]:
            continue
        entry = collaborator_totals.setdefault(key, {"setor": sector, "colaborador": name, "total": 0.0})
        entry["total"] = round(float(entry["total"]) + _prize(item), 2)
    payload["porColaborador"] = sorted(
        collaborator_totals.values(),
        key=lambda item: (-float(item["total"]), _norm(item["colaborador"])),
    )

    lab_totals: dict[str, dict[str, Any]] = {}
    lab_people: dict[str, set[tuple[str, str]]] = {}
    for item in awarded:
        label = str(item.get("laboratorio") or "").strip()
        key = _lab(label)
        if not key:
            continue
        entry = lab_totals.setdefault(key, {"laboratorio": label, "total": 0.0, "colaboradores": 0})
        entry["total"] = round(float(entry["total"]) + _prize(item), 2)
        name = _norm(item.get("colaborador"))
        if name:
            lab_people.setdefault(key, set()).add((str(item.get("setor") or ""), name))
    for key, entry in lab_totals.items():
        entry["colaboradores"] = len(lab_people.get(key, set()))
    payload["porLaboratorio"] = sorted(
        lab_totals.values(),
        key=lambda item: (-float(item["total"]), _norm(item["laboratorio"])),
    )


def overlay_monthly_metrics(summary: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return summary
    indexed = _published_metrics(publication)
    if not indexed:
        return summary

    out = copy.deepcopy(summary)
    rows = out.get("registros")
    if not isinstance(rows, list):
        return summary

    changed = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("tipoRegistro") or "").upper() == "CAMPANHA_EXTRA":
            continue
        current = indexed.get(_record_key(item))
        if current is None:
            continue
        item["premiacao"] = current["premiacao"]
        item["metricasParcial"] = current["metricasParcial"]
        item["metricasDetalhes"] = current["metricasDetalhes"]
        item["metricaPendente"] = current["metricaPendente"]
        item["motivoMetrica"] = current["motivoMetrica"]
        item["metricaValor"] = current["metricaValor"]
        if current["atingimento"] is not None:
            item["atingimento"] = current["atingimento"]
        rule = current.get("regra")
        if isinstance(rule, dict):
            item["regra"] = copy.deepcopy(rule)
            item["regraAplicada"] = copy.deepcopy(rule)
            if str(rule.get("tipo") or "").strip():
                item["tipoPremio"] = str(rule.get("tipo"))
            if str(rule.get("premioTexto") or "").strip():
                item["premioTexto"] = str(rule.get("premioTexto"))
        components = current["metricasDetalhes"]
        if components and isinstance(components[0], dict):
            if str(components[0].get("metrica") or "").strip():
                item["metrica"] = str(components[0].get("metrica"))
        changed += 1

    if not changed:
        return summary
    _rebuild_totals(out)
    out["mensalSincronizadoComParciais"] = True
    out["linhasMensaisSincronizadas"] = changed
    return out


def install_resumo_monthly_overlay(app) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        from . import main as main_module
    except Exception:
        return

    original = getattr(main_module, "resumo_ganhos_snapshot", None)
    if not callable(original) or getattr(original, "__dismepe_monthly_overlay__", False):
        return

    async def wrapped_resumo_ganhos_snapshot(*args, **kwargs):
        result = await original(*args, **kwargs)
        try:
            publication, row = await cache_get(modulo="HOME_PUBLICATION", settings=main_module.settings)
            result = overlay_monthly_metrics(result, publication)
            if isinstance(result, dict) and result.get("mensalSincronizadoComParciais"):
                result["mensalAtualizadoEm"] = str(row.get("atualizado_em") or "")
                result["fonteMensalResumo"] = "HOME_PUBLICATION"
        except (CacheReadError, ValueError, TypeError):
            pass
        return result

    wrapped_resumo_ganhos_snapshot.__dismepe_monthly_overlay__ = True
    wrapped_resumo_ganhos_snapshot.__wrapped__ = original
    main_module.resumo_ganhos_snapshot = wrapped_resumo_ganhos_snapshot

    # A rota GET foi registrada durante a importação de api.main. Atualizar o
    # dependant mantém a mesma URL/permissão e troca somente a chamada final.
    for route in getattr(app, "routes", []):
        if getattr(route, "path", "") != "/data/resumo-ganhos":
            continue
        if "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        route.endpoint = wrapped_resumo_ganhos_snapshot
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependant.call = wrapped_resumo_ganhos_snapshot

    _INSTALLED = True
