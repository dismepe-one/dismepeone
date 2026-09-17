from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .industries_sales_sync import ensure_general_sales_fresh


ROOT = Path(__file__).resolve().parents[1]
GENERAL_SALES_FILE = ROOT / "data" / "industries" / "venda_geral_atual.json"
TARGET_LAB = "HERBAMED"


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean(value).replace("R$", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _row_competence(row: dict[str, Any]) -> str:
    return _clean(
        row.get("__COMPETENCIA")
        or row.get("competencia")
        or row.get("Competencia")
        or row.get("Competência")
        or row.get("COMPETENCIA")
        or ""
    )


def _row_lab(row: dict[str, Any]) -> str:
    return _clean(
        row.get("__LAB")
        or row.get("lab")
        or row.get("laboratorio")
        or row.get("Laboratório")
        or row.get("Laboratorio")
        or row.get("LABORATORIO")
        or ""
    )


def _source_value(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[float, bool]:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return _num(row.get(key)), True
    return 0.0, False


def _herbamed_totals_from_file() -> dict[str, Any] | None:
    if not GENERAL_SALES_FILE.exists():
        return None
    try:
        payload = json.loads(GENERAL_SALES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    rows = payload.get("linhas")
    if not isinstance(rows, list):
        return None

    source_comp = _clean(payload.get("competencia") or "")
    sale = 0.0
    positivity = 0.0
    found_sale = False
    found_positivity = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        if _key(row.get("laboratorio") or row.get("lab") or row.get("fornecedor")) != TARGET_LAB:
            continue

        row_comp = _clean(row.get("competencia") or row.get("mes") or row.get("periodo") or "")
        if source_comp and row_comp and row_comp != source_comp:
            continue

        value, present = _source_value(
            row,
            ("venda_total", "venda", "total", "faturamento"),
        )
        if present:
            sale += value
            found_sale = True

        value, present = _source_value(
            row,
            (
                "positivacao_total",
                "positivacao",
                "positivação",
                "positivados",
                "clientes_positivados",
            ),
        )
        if present:
            positivity += value
            found_positivity = True

    if not found_sale or not found_positivity:
        return None

    return {
        "competencia": source_comp,
        "faturamento": round(sale, 2),
        "positivacao": int(round(positivity)),
        "atualizadoEm": _clean(payload.get("gerado_em") or payload.get("atualizado_em") or ""),
        "fonte": _clean(payload.get("fonte") or payload.get("arquivo_origem") or ""),
    }


def _display_number(value: Any, metric: str) -> str:
    number = _num(value)
    if metric == "FATURAMENTO_LABORATORIO":
        return f"{number:.2f}"
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _rebuild_observation(components: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in components:
        metric = _clean(item.get("metrica")).upper()
        criterion = _clean(item.get("criterio") or metric.replace("_", " "))
        if not criterion:
            continue
        parts.append(
            f"{criterion}: {_display_number(item.get('realizado'), metric)} / "
            f"{_display_number(item.get('meta'), metric)}"
        )
    return " | ".join(parts)


def _apply_to_row(row: dict[str, Any], totals: dict[str, Any]) -> bool:
    if _key(_row_lab(row)) != TARGET_LAB:
        return False

    source_comp = _clean(totals.get("competencia") or "")
    row_comp = _row_competence(row)
    if source_comp and row_comp and row_comp != source_comp:
        return False

    calc = row.get("metricasParcial")
    if not isinstance(calc, dict):
        return False
    components = calc.get("componentes")
    if not isinstance(components, list):
        return False

    changed = False
    for component in components:
        if not isinstance(component, dict):
            continue
        metric = _clean(component.get("metrica")).upper()
        if metric == "FATURAMENTO_LABORATORIO":
            realized = float(totals["faturamento"])
        elif metric == "POSITIVACAO_GERAL":
            realized = float(totals["positivacao"])
        else:
            # POSITIVACAO_CLIENTES continua individual por colaborador.
            continue

        component["realizado"] = int(realized) if metric == "POSITIVACAO_GERAL" else round(realized, 2)
        component["pendente"] = False
        component["motivo"] = ""

        meta = _num(component.get("meta"))
        configured = _num(component.get("premioConfigurado"))
        component["premio"] = round(configured, 2) if meta > 0 and realized >= meta else 0
        changed = True

    if not changed:
        return False

    total_prize = round(
        sum(_num(item.get("premio")) for item in components if isinstance(item, dict)),
        2,
    )
    calc["valor"] = total_prize
    calc["pendente"] = False
    calc["motivo"] = ""
    calc["fonteIndicadoresGerais"] = "VENDA_GERAL"
    calc["indicadoresGeraisAtualizadoEm"] = _clean(totals.get("atualizadoEm") or "")

    rule = calc.get("regra")
    if isinstance(rule, dict):
        rule["valor"] = total_prize
        rule["observacao"] = _rebuild_observation(
            [item for item in components if isinstance(item, dict)]
        )
        rule["fonteIndicadoresGerais"] = "VENDA_GERAL"

    return True


async def enrich_herbamed_monthly_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Substitui apenas os totais gerais da HERBAMED pela VENDA GERAL.

    - Faturamento geral -> VENDA GERAL / Venda Líquida.
    - Positivação geral -> VENDA GERAL / Positivação.
    - Positivação individual permanece exatamente como veio da apuração mensal.
    - Nunca altera competência histórica diferente da competência da fotografia do Drive.
    """
    if not isinstance(payload, dict):
        return payload

    try:
        await ensure_general_sales_fresh(max_age_seconds=10.0)
    except Exception:
        # A fotografia local válida continua sendo utilizada como fallback.
        pass

    totals = _herbamed_totals_from_file()
    if not totals:
        return payload

    result = copy.deepcopy(payload)
    changed = False
    for key in ("dadosVendedores", "dadosTelevendas", "CAMPANHA VEND", "CAMPANHAS TLVS"):
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and _apply_to_row(row, totals):
                changed = True

    if changed:
        result["herbamedIndicadoresGerais"] = {
            "competencia": totals.get("competencia"),
            "faturamento": totals.get("faturamento"),
            "positivacao": totals.get("positivacao"),
            "fonte": "VENDA_GERAL",
            "arquivoOrigem": totals.get("fonte"),
            "atualizadoEm": totals.get("atualizadoEm"),
        }
    return result
