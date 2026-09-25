"""Cálculo em memória das métricas especiais da campanha mensal.

Não publica snapshots. Entradas devem vir de fontes com revisão fixada.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import re
import unicodedata
from typing import Any


class SpecialAwardError(ValueError):
    """Falta de fonte/regras: nunca converter erro em premiação zero."""


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)).upper())


def money(value: Any) -> Decimal:
    if value is None or value == "" or isinstance(value, bool):
        raise SpecialAwardError("Indicador financeiro ausente.")
    raw = str(value).replace("R$", "").strip().replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        result = Decimal(raw)
    except (ValueError, InvalidOperation) as exc:
        raise SpecialAwardError("Indicador financeiro inválido.") from exc
    if not result.is_finite() or result < 0:
        raise SpecialAwardError("Indicador financeiro inválido.")
    return result


def channel(value: Any) -> str:
    name = norm(value)
    if name in ("VENDEDOR", "VENDEDORES", "ELETRONICO", "ELETRONICA"):
        return "VENDEDOR"
    if name in ("TELEVENDAS", "TELEVENDA"):
        return "TELEVENDAS"
    return ""


def competence(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%m/%Y")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return (date(1899, 12, 30) + timedelta(days=int(value))).strftime("%m/%Y")
        except (ValueError, OverflowError):
            return ""
    raw = str(value or "").strip()
    match = re.match(r"^(20\d{2})-(0[1-9]|1[0-2])(?:-\d{2})?$", raw)
    if match:
        return match[2] + "/" + match[1]
    match = re.match(r"^\d{1,2}/(0?[1-9]|1[0-2])/(20\d{2})$", raw)
    if match:
        return f"{int(match[1]):02d}/{match[2]}"
    match = re.fullmatch(r"(0?[1-9]|1[0-2])/(20\d{2})", raw)
    return f"{int(match[1]):02d}/{match[2]}" if match else ""


def records(matrix: list[list[Any]]) -> list[dict[str, Any]]:
    if not isinstance(matrix, list) or len(matrix) < 2:
        raise SpecialAwardError("Base auxiliar ausente.")
    headers = [norm(value) for value in matrix[0]]
    present = [key for key in headers if key]
    if not present or len(set(present)) != len(present):
        raise SpecialAwardError("Cabeçalho auxiliar vazio ou duplicado.")
    return [{key: row[index] if index < len(row) else None
             for index, key in enumerate(headers) if key}
            for row in matrix[1:] if any(str(value).strip() for value in row)]


def field(row: dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        value = row.get(norm(alias))
        if value is not None and value != "":
            return value
    return None


def component(rule: dict[str, Any], meta: Decimal | None,
              achieved: Decimal | None, prize: Decimal,
              reason: str = "") -> dict[str, Any]:
    pending = bool(reason) or meta is None or achieved is None
    return {"id": rule.get("id"), "metrica": rule.get("metrica"),
            "meta": meta, "realizado": achieved,
            "premio": Decimal(0) if pending else prize,
            "pendente": pending, "motivo": reason}


def globo(comp: str, canal: str, person: str, rule: dict[str, Any],
          teams: list[dict[str, Any]], customers: list[dict[str, Any]]) -> dict[str, Any]:
    team = [r for r in teams if norm(field(r, "VENDEDOR_TELEVENDAS")) == norm(person)
            and channel(field(r, "TIPO")) == channel(canal)]
    if len(team) != 1:
        return component(rule, None, None, Decimal(0), "Meta individual GLOBO ausente ou duplicada.")
    meta, prize = money(field(team[0], "META_CLIENTES")), money(field(team[0], "PREMIO"))
    if meta <= 0:
        return component(rule, None, None, Decimal(0), "Meta individual GLOBO inválida.")
    available = [r for r in customers if competence(field(r, "DATA", "COMPETENCIA")) == comp
                 and field(r, "COD CLIENTE", "CODIGO CLIENTE") is not None]
    if not available:
        return component(rule, meta, None, Decimal(0), "GLOBO_CLIENTES sem dados válidos da competência.")
    channels = {}
    for r in teams:
        channels.setdefault(norm(field(r, "VENDEDOR_TELEVENDAS")), set()).add(channel(field(r, "TIPO")))
    clients = set()
    for r in available:
        name = norm(field(r, "VENDEDOR", "VENDEDOR_TELEVENDAS"))
        explicit = channel(field(r, "CANAL", "TIPO"))
        known = channels.get(name, set()) - {""}
        assigned = explicit or (next(iter(known)) if len(known) == 1 else "")
        if name == norm(person) and assigned == channel(canal) and money(field(r, "POSITIVACAO") or 0) > 0:
            clients.add(str(field(r, "COD CLIENTE", "CODIGO CLIENTE")).strip())
    return component(rule, meta, Decimal(len(clients)),
                     prize if Decimal(len(clients)) >= meta else Decimal(0))


def herbamed_clients(comp: str, canal: str, person: str, rule: dict[str, Any],
                     meta: Decimal, prize: Decimal, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if meta <= 0:
        return component(rule, None, None, Decimal(0), "Meta HERBAMED inválida.")
    valid = [r for r in rows if competence(field(r, "DATA", "DATA FATURAMENTO", "COMPETENCIA")) == comp
             and norm(field(r, "VENDEDOR", "RESPONSAVEL", "COLABORADOR"))
             and field(r, "COD CLIENTE", "CNPJ") is not None
             and channel(field(r, "PEDIDOS POR", "CANAL"))]
    if not valid:
        return component(rule, meta, None, Decimal(0), "HERB_COM sem registros válidos da competência.")
    clients = {str(field(r, "COD CLIENTE", "CNPJ")).strip() for r in valid
               if norm(field(r, "VENDEDOR", "RESPONSAVEL", "COLABORADOR")) == norm(person)
               and channel(field(r, "PEDIDOS POR", "CANAL")) == channel(canal)}
    achieved = Decimal(len(clients))
    return component(rule, meta, achieved,
                     (achieved / meta).to_integral_value(rounding=ROUND_FLOOR) * prize)


def herbamed_general(rule: dict[str, Any], metric: str, meta: Decimal,
                     prize: Decimal, indicators: dict[str, Any]) -> dict[str, Any]:
    if meta <= 0:
        return component(rule, None, None, Decimal(0), "Meta HERBAMED inválida.")
    key = {"FATURAMENTO_LABORATORIO": "FATURAMENTO_GERAL_MANUAL",
           "POSITIVACAO_GERAL": "POSITIVACAO_GERAL_MANUAL"}.get(metric)
    if key is None:
        raise SpecialAwardError("Métrica geral HERBAMED desconhecida.")
    if key not in indicators:
        return component(rule, meta, None, Decimal(0), "Indicador manual ausente no SQL.")
    achieved = money(indicators[key])
    return component(rule, meta, achieved, prize if achieved >= meta else Decimal(0))
