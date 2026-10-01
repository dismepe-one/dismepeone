from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from .cache_reads import CacheReadError, cache_get
from .security import decode_session_token

SOURCE_MODULE = "PULSY_2026_09"
METRIC = "PREMIACAO_UNIDADES"
LAB = "PULSY"
_INSTALLED = False
_FRONTEND_MARKER = "DISMEPE_PULSY_UNITS_V1"


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _num(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0


def _source_index(source: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rules = source.get("rules") if isinstance(source.get("rules"), list) else []
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in source.get("rows") if isinstance(source.get("rows"), list) else []:
        if not isinstance(raw, dict):
            continue
        channel = "TELEVENDAS" if str(raw.get("s") or "").upper() == "T" else "VENDEDOR"
        collaborator = str(raw.get("c") or "").strip()
        quantities = raw.get("q") if isinstance(raw.get("q"), list) else []
        if not collaborator:
            continue

        components: list[dict[str, Any]] = []
        total_prize = 0.0
        total_units = 0.0
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            qty = _num(quantities[index] if index < len(quantities) else 0)
            minimum = _num(rule.get("min"))
            rate = _num(rule.get("rate"))
            prize = round(qty * rate, 2) if minimum > 0 and qty >= minimum else 0.0
            total_units += qty
            total_prize += prize
            components.append({
                "id": "PULSY_" + str(rule.get("id") or index),
                "metrica": METRIC,
                "criterio": str(rule.get("label") or rule.get("id") or "Produto PULSY"),
                "meta": minimum,
                "realizado": qty,
                "premio": prize,
                "premioConfigurado": rate,
                "valorPorUnidade": rate,
                "gatilhoAtingido": bool(minimum > 0 and qty >= minimum),
                "pendente": False,
                "motivo": "",
            })

        out[(channel, _norm(collaborator))] = {
            "channel": channel,
            "collaborator": collaborator,
            "components": components,
            "prize": round(total_prize, 2),
            "units": round(total_units, 2),
        }
    return out


def _monthly_row(source: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    comp = str(source.get("comp") or "09/2026")
    channel = item["channel"]
    collaborator = item["collaborator"]
    prize = item["prize"]
    components = copy.deepcopy(item["components"])
    rule = {
        "id": "PULSY_UNIDADES_" + comp.replace("/", ""),
        "tipo": "VALOR_POR_UNIDADE",
        "ativo": True,
        "canal": "TODOS",
        "valor": prize,
        "metrica": METRIC,
        "criterio": "Premiação por unidade vendida após atingir o gatilho mínimo de cada produto.",
        "gatilho": "MINIMO_POR_PRODUTO",
        "competencia": comp,
        "laboratorio": LAB,
        "premioTexto": "Premiação PULSY por unidades",
        "exigeFoco": False,
        "exigeSomaLaboratorio": False,
        "observacao": "Campanha válida de 01/09/2026 a 30/09/2026.",
    }
    detail = {
        "regra": rule,
        "valor": prize,
        "focoOK": True,
        "motivo": "",
        "pendente": False,
        "realizado": item["units"],
        "atingimento": 0,
        "componentes": components,
        "fonte": SOURCE_MODULE,
    }
    return {
        "__COLABORADOR": collaborator,
        "colab": collaborator,
        "Colaborador": collaborator,
        "__LAB": LAB,
        "lab": LAB,
        "Laboratorio": LAB,
        "Laboratório": LAB,
        "__COMPETENCIA": comp,
        "competencia": comp,
        "__CANAL": "TELEVENDAS" if channel == "TELEVENDAS" else "VENDEDORES",
        "canal": channel,
        "__VENDA": 0,
        "venda": 0,
        "Venda": 0,
        "Vendas": 0,
        "Realizado": 0,
        "__OBJETIVO": 0,
        "objetivo": 0,
        "Objetivo": 0,
        "Meta": 0,
        "%": 0,
        "Premiação": prize,
        "premiacao": prize,
        "metricasParcial": detail,
        "metricasDetalhes": components,
        "metricaPendente": False,
        "premiacaoComBaseAnterior": True,
        "pulsyUnidades": item["units"],
        "pulsyBase": SOURCE_MODULE,
    }


def overlay_monthly(payload: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(source, dict):
        return payload
    comp = str(source.get("comp") or "").strip()
    if not comp:
        return payload
    indexed = _source_index(source)
    if not indexed:
        return payload

    out = copy.deepcopy(payload)
    fields = (("dadosVendedores", "VENDEDOR"), ("dadosTelevendas", "TELEVENDAS"))
    inserted = 0
    total = 0.0
    for field, channel in fields:
        existing = out.get(field)
        if not isinstance(existing, list):
            continue
        clean = [
            row for row in existing
            if not (
                isinstance(row, dict)
                and _norm(row.get("__LAB") or row.get("lab")) == LAB
                and str(row.get("__COMPETENCIA") or row.get("competencia") or "").strip() == comp
                and str((row.get("metricasParcial") or {}).get("fonte") or "") == SOURCE_MODULE
            )
        ]
        for (row_channel, _name), item in indexed.items():
            if row_channel != channel:
                continue
            clean.append(_monthly_row(source, item))
            inserted += 1
            total += item["prize"]
        out[field] = clean

    out["pulsyUnidades"] = {
        "competencia": comp,
        "fonte": SOURCE_MODULE,
        "colaboradores": inserted,
        "premiados": sum(1 for item in indexed.values() if item["prize"] > 0),
        "premiacaoTotal": round(total, 2),
    }
    return out


def _is_management(profile: dict[str, Any]) -> bool:
    role = _norm(profile.get("tipo"))
    return role in {
        "ADMINISTRADOR", "ADMIN", "COMERCIAL", "GERENTE DE VENDAS",
        "SUP VENDAS", "SUP TELEVENDAS",
    } or "SUPERVISOR" in role


def _summary_record(source: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    comp = str(source.get("comp") or "09/2026")
    prize = item["prize"]
    return {
        "regra": {
            "id": "PULSY_UNIDADES_" + comp.replace("/", ""),
            "tipo": "VALOR_POR_UNIDADE",
            "ativo": True,
            "canal": "TODOS",
            "valor": prize,
            "metrica": METRIC,
            "criterio": "Premiação PULSY por unidade vendida com gatilho mínimo por produto.",
            "competencia": comp,
            "laboratorio": LAB,
            "premioTexto": "Premiação PULSY por unidades",
        },
        "setor": "Televendas" if item["channel"] == "TELEVENDAS" else "Vendedor",
        "venda": 0,
        "focoOK": True,
        "origem": "CAMPANHA MENSAL",
        "metrica": METRIC,
        "periodo": comp,
        "campanha": "Campanha mensal " + comp,
        "objetivo": 0,
        "premiacao": prize,
        "campanhaId": "CM18_" + comp.replace("/", ""),
        "tipoPremio": "VALOR_POR_UNIDADE",
        "atingimento": 0,
        "colaborador": item["collaborator"],
        "competencia": comp,
        "laboratorio": LAB,
        "premioTexto": "",
        "metricaValor": prize,
        "tipoRegistro": "CAMPANHA_MENSAL",
        "regraAplicada": "PULSY • VALOR_POR_UNIDADE • GATILHO_POR_PRODUTO",
        "metricasParcial": {
            "valor": prize,
            "componentes": copy.deepcopy(item["components"]),
            "fonte": SOURCE_MODULE,
        },
        "metricasDetalhes": copy.deepcopy(item["components"]),
        "objetivoVendaOK": True,
        "somaLaboratorioOK": True,
        "pulsyBase": SOURCE_MODULE,
    }


def overlay_summary(
    summary: dict[str, Any],
    source: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return summary
    indexed = _source_index(source)
    if not indexed:
        return summary

    candidates = {
        _norm(profile.get("vendedor")),
        _norm(profile.get("nome")),
        _norm(profile.get("usuario")),
    } - {""}
    management = _is_management(profile)

    out = copy.deepcopy(summary)
    rows = out.get("registros") if isinstance(out.get("registros"), list) else []
    rows = [
        row for row in rows
        if not (isinstance(row, dict) and str(row.get("pulsyBase") or "") == SOURCE_MODULE)
    ]
    added = 0
    for item in indexed.values():
        if item["prize"] <= 0:
            continue
        if not management and _norm(item["collaborator"]) not in candidates:
            continue
        rows.append(_summary_record(source, item))
        added += 1
    out["registros"] = rows

    try:
        from .resumo_monthly_overlay import _rebuild_totals
        _rebuild_totals(out)
    except Exception:
        pass
    out["pulsyUnidadesResumo"] = {
        "competencia": str(source.get("comp") or ""),
        "registrosAdicionados": added,
        "fonte": SOURCE_MODULE,
    }
    return out


def _patch_frontend(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return
    if _FRONTEND_MARKER in text:
        return

    marker = "<script>\n// V171: regras e parciais da competência, sem catálogo fixo por laboratório."
    if marker not in text:
        return
    text = text.replace(marker, "<script>\n// " + _FRONTEND_MARKER + "\n// V171: regras e parciais da competência, sem catálogo fixo por laboratório.", 1)
    old_labels = "PONTUACAO_PRODUTO:'Pontos individuais'};"
    text = text.replace(old_labels, "PONTUACAO_PRODUTO:'Pontos individuais',PREMIACAO_UNIDADES:'Premiação PULSY por unidades'};", 1)
    old_money = "const money=c.metrica==='FATURAMENTO_LABORATORIO';"
    new_money = "const unitPrize=c.metrica==='PREMIACAO_UNIDADES';\n    const money=c.metrica==='FATURAMENTO_LABORATORIO';"
    text = text.replace(old_money, new_money, 1)
    old_status = "const status=c.pendente?(c.motivo||'').includes('base vazia')?`${fmt(c.realizado||0)} clientes positivados registrados`:`Aguardando atualização: ${c.motivo}`:(herb?`${fmt(c.realizado)} / ${fmt(c.meta)}`:`${fmt(c.realizado)} / ${fmt(c.meta)} · Prêmio ${v171Money(c.premio)}`);"
    new_status = "const status=unitPrize?`${fmt(c.realizado)} / ${fmt(c.meta)} un. · ${v171Money(c.valorPorUnidade)}/un. · Prêmio ${v171Money(c.premio)}`:(c.pendente?(c.motivo||'').includes('base vazia')?`${fmt(c.realizado||0)} clientes positivados registrados`:`Aguardando atualização: ${c.motivo}`:(herb?`${fmt(c.realizado)} / ${fmt(c.meta)}`:`${fmt(c.realizado)} / ${fmt(c.meta)} · Prêmio ${v171Money(c.premio)}`));"
    text = text.replace(old_status, new_status, 1)
    try:
        temp = path.with_name(path.name + ".pulsy.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


def _route_for(app: Any, path: str, method: str) -> APIRoute | None:
    for route in getattr(app, "routes", []):
        if isinstance(route, APIRoute) and route.path == path and method.upper() in (route.methods or set()):
            return route
    return None


def install_pulsy_monthly_overlay(app: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import main as main_module

    original_home_get = main_module.home_publication_cache_get

    async def home_get_with_pulsy(*, modulo: str, settings):
        payload, row = await original_home_get(modulo=modulo, settings=settings)
        if str(modulo or "").strip().upper() != "MENSAL":
            return payload, row
        try:
            source, _ = await cache_get(modulo=SOURCE_MODULE, settings=settings)
            payload = overlay_monthly(payload, source)
        except CacheReadError:
            pass
        return payload, row

    main_module.home_publication_cache_get = home_get_with_pulsy

    original_summary = main_module.resumo_ganhos_snapshot

    async def summary_with_pulsy(session: str | None = None):
        result = await original_summary(session=session)
        if not session:
            return result
        try:
            profile = decode_session_token(
                session,
                secret=main_module.settings.jwt_secret,
                issuer=main_module.settings.jwt_issuer,
            )
            source, _ = await cache_get(modulo=SOURCE_MODULE, settings=main_module.settings)
            return overlay_summary(result, source, profile)
        except Exception:
            return result

    main_module.resumo_ganhos_snapshot = summary_with_pulsy
    route = _route_for(app, "/data/resumo-ganhos", "GET")
    if route is not None:
        route.endpoint = summary_with_pulsy
        route.dependant.call = summary_with_pulsy

    portal = getattr(main_module, "PORTAL_FILE", None)
    if isinstance(portal, Path):
        _patch_frontend(portal)

    _INSTALLED = True
