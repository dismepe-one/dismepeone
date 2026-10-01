from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo


TZ = ZoneInfo("America/Recife")
_INSTALLED = False
_MONTHS = {
    "JANEIRO": 1,
    "FEVEREIRO": 2,
    "MARCO": 3,
    "ABRIL": 4,
    "MAIO": 5,
    "JUNHO": 6,
    "JULHO": 7,
    "AGOSTO": 8,
    "SETEMBRO": 9,
    "OUTUBRO": 10,
    "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}


def _text_key(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _normalize_competence(value: Any, *, fallback_year: int | None = None) -> str:
    now = datetime.now(TZ)
    year_default = int(fallback_year or now.year)

    if isinstance(value, datetime):
        return value.strftime("%m/%Y")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number.is_integer() and 1 <= int(number) <= 12:
            return f"{int(number):02d}/{year_default:04d}"
        if number.is_integer() and 190001 <= int(number) <= 210012:
            raw = str(int(number))
            year = int(raw[:4])
            month = int(raw[4:])
            if 1 <= month <= 12:
                return f"{month:02d}/{year:04d}"
        # Quando o Excel grava MÊS como data, o leitor XML recebe o serial.
        if 20000 <= number <= 100000:
            try:
                dt = datetime(1899, 12, 30) + timedelta(days=number)
                return dt.strftime("%m/%Y")
            except Exception:
                return ""

    text = str(value or "").strip()
    if not text:
        return ""

    patterns = (
        (r"^(\d{1,2})[/-](\d{4})$", False),
        (r"^(\d{4})[/-](\d{1,2})$", True),
    )
    for pattern, year_first in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        if year_first:
            year, month = int(match.group(1)), int(match.group(2))
        else:
            month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f"{month:02d}/{year:04d}"

    if re.fullmatch(r"\d{1,2}", text):
        month = int(text)
        if 1 <= month <= 12:
            return f"{month:02d}/{year_default:04d}"

    key = _text_key(text)
    match = re.fullmatch(r"([A-Z]+)\s+(\d{4})", key)
    if match and match.group(1) in _MONTHS:
        return f"{_MONTHS[match.group(1)]:02d}/{int(match.group(2)):04d}"
    if key in _MONTHS:
        return f"{_MONTHS[key]:02d}/{year_default:04d}"
    return ""


def _comp_order(value: Any) -> int:
    comp = _normalize_competence(value)
    if not comp:
        return 0
    month, year = comp.split("/")
    return int(year) * 100 + int(month)


def _find_index(header: list[Any], predicate: Callable[[str], bool]) -> int | None:
    for idx, value in enumerate(header):
        if predicate(_text_key(value)):
            return idx
    return None


def _row_value(row: list[Any], idx: int | None) -> Any:
    if idx is None or idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _aggregate_snapshot_for_lab(industries_module, snapshot: dict[str, Any], lab: str, target_comp: str):
    rows = snapshot.get("linhas")
    if not isinstance(rows, list):
        return None
    all_labs = industries_module._is_all_labs_request(lab)
    lab_keys = industries_module._portal_source_keys(lab)
    total = 0.0
    objective = 0.0
    positivity = 0.0
    found = False
    has_objective = False
    has_positivity = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_comp = _normalize_competence(
            row.get("competencia") or row.get("mes") or row.get("periodo") or ""
        )
        if target_comp and row_comp != target_comp:
            continue
        row_lab = (
            row.get("laboratorio")
            or row.get("lab")
            or row.get("fornecedor")
            or row.get("industria")
        )
        if not all_labs and industries_module._lab_key(row_lab) not in lab_keys:
            continue
        raw_value = row.get("venda_total")
        if raw_value is None:
            raw_value = row.get("venda")
        if raw_value is None:
            raw_value = row.get("total")
        if raw_value is None:
            raw_value = row.get("faturamento")
        if raw_value in (None, ""):
            continue
        total += industries_module._num(raw_value)
        found = True

        raw_obj = row.get("objetivo_total")
        if raw_obj is None:
            raw_obj = row.get("objetivo")
        if raw_obj not in (None, ""):
            objective += industries_module._num(raw_obj)
            has_objective = True

        raw_pos = row.get("positivacao_total")
        if raw_pos is None:
            raw_pos = row.get("positivacao")
        if raw_pos is None:
            raw_pos = row.get("positivação")
        if raw_pos is None:
            raw_pos = row.get("positivados")
        if raw_pos not in (None, ""):
            positivity += industries_module._num(raw_pos)
            has_positivity = True

    if not found:
        return None
    return {
        "venda": round(total, 2),
        "objetivo": round(objective, 2) if has_objective else None,
        "positivacao": int(round(positivity)) if has_positivity else None,
        "atualizadoEm": str(snapshot.get("gerado_em") or snapshot.get("atualizado_em") or ""),
        "arquivoOrigem": str(snapshot.get("fonte") or snapshot.get("arquivo_origem") or ""),
    }


def _build_snapshot_with_competence(sales_sync, raw_xlsx: bytes, *, source_item: dict[str, Any]) -> dict[str, Any]:
    vendas = sales_sync._read_sheet(raw_xlsx, "VENDA GERAL")
    objetivos = sales_sync._read_sheet(raw_xlsx, "OBJETIVO")
    if len(vendas) < 2:
        raise RuntimeError("A aba VENDA GERAL está vazia.")
    if len(objetivos) < 2:
        raise RuntimeError("A aba OBJETIVO está vazia.")

    venda_header = vendas[0]
    objetivo_header = objetivos[0]
    venda_lab_idx = _find_index(venda_header, lambda key: key == "FORNECEDOR")
    venda_value_idx = _find_index(venda_header, lambda key: "VENDA" in key)
    venda_pos_idx = _find_index(venda_header, lambda key: "POSITIVACAO" in key)
    venda_comp_idx = _find_index(
        venda_header,
        lambda key: key in {"MES", "COMPETENCIA", "MES COMPETENCIA", "PERIODO"}
        or "COMPETENCIA" in key,
    )
    obj_lab_idx = _find_index(objetivo_header, lambda key: key == "FORNECEDOR")
    obj_value_idx = _find_index(objetivo_header, lambda key: "OBJETIVO" in key)
    obj_comp_idx = _find_index(
        objetivo_header,
        lambda key: key in {"MES", "COMPETENCIA", "MES COMPETENCIA", "PERIODO"}
        or "COMPETENCIA" in key,
    )

    if venda_lab_idx is None:
        raise RuntimeError("Cabeçalho Fornecedor não encontrado na aba VENDA GERAL.")
    if venda_value_idx is None:
        raise RuntimeError("Cabeçalho Venda não encontrado na aba VENDA GERAL.")
    if venda_pos_idx is None:
        raise RuntimeError("Cabeçalho Positivação não encontrado na aba VENDA GERAL.")
    if obj_lab_idx is None:
        raise RuntimeError("Cabeçalho Fornecedor não encontrado na aba OBJETIVO.")
    if obj_value_idx is None:
        raise RuntimeError("Cabeçalho Objetivo não encontrado na aba OBJETIVO.")

    now = datetime.now(TZ)
    default_comp = now.strftime("%m/%Y")
    objective_by_comp: dict[tuple[str, str], float | None] = {}
    objective_by_lab: dict[str, float | None] = {}

    for row in objetivos[1:]:
        lab = sales_sync._clean(_row_value(row, obj_lab_idx))
        if not lab:
            continue
        value = sales_sync._number(_row_value(row, obj_value_idx))
        lab_key = sales_sync._key(lab)
        if obj_comp_idx is None:
            objective_by_lab[lab_key] = value
            continue
        comp = _normalize_competence(_row_value(row, obj_comp_idx), fallback_year=now.year)
        if not comp:
            continue
        objective_by_comp[(lab_key, comp)] = value

    lines: list[dict[str, Any]] = []
    competences: set[str] = set()
    for row in vendas[1:]:
        lab = sales_sync._clean(_row_value(row, venda_lab_idx))
        sale = sales_sync._number(_row_value(row, venda_value_idx))
        positivity = sales_sync._number(_row_value(row, venda_pos_idx))
        if not lab or sale is None:
            continue

        if venda_comp_idx is None:
            comp = default_comp
        else:
            comp = _normalize_competence(_row_value(row, venda_comp_idx), fallback_year=now.year)
            if not comp:
                continue

        lab_key = sales_sync._key(lab)
        objective = (
            objective_by_comp.get((lab_key, comp))
            if obj_comp_idx is not None
            else objective_by_lab.get(lab_key)
        )
        lines.append({
            "laboratorio": lab,
            "competencia": comp,
            "venda_total": round(sale, 2),
            "positivacao_total": int(round(positivity)) if positivity is not None else None,
            "objetivo_total": round(objective, 2) if objective is not None else None,
        })
        competences.add(comp)

    if len(lines) < 10:
        raise RuntimeError(
            f"Base rejeitada por segurança: somente {len(lines)} laboratórios válidos."
        )

    digest = hashlib.sha256(raw_xlsx).hexdigest()
    ordered_competences = sorted(competences, key=_comp_order, reverse=True)
    single_comp = ordered_competences[0] if len(ordered_competences) == 1 else ""
    return {
        "idAtualizacao": now.strftime("%Y%m%d_%H%M%S") + "_" + digest[:10],
        "fonte": str(source_item.get("name") or sales_sync._target_filename()),
        "competencia": single_comp,
        "competencias": ordered_competences,
        "competenciaVendaOrigem": "PLANILHA" if venda_comp_idx is not None else "CALENDARIO",
        "competenciaObjetivoOrigem": "PLANILHA" if obj_comp_idx is not None else "CALENDARIO",
        "schema": sales_sync.SNAPSHOT_SCHEMA,
        "gerado_em": now.strftime("%d/%m/%Y %H:%M:%S"),
        "drive_file_id": str(source_item.get("id") or ""),
        "drive_modified_time": str(source_item.get("modifiedTime") or ""),
        "sha256": digest,
        "linhas": lines,
    }


def install_industry_competence_fields() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from . import industries as industries_module
        from . import industries_sales_sync as sales_sync
        from . import industry_operational_sales_guard as sales_guard
    except Exception:
        return

    original_days = getattr(industries_module, "_days_remaining", None)
    if callable(original_days) and not getattr(original_days, "__dismepe_past_competence_zero__", False):
        def days_remaining(payload, comp):
            normalized = _normalize_competence(comp)
            current = datetime.now(TZ).strftime("%m/%Y")
            if normalized and _comp_order(normalized) < _comp_order(current):
                return 0.0
            return original_days(payload, comp)

        days_remaining.__dismepe_past_competence_zero__ = True
        days_remaining.__wrapped__ = original_days
        industries_module._days_remaining = days_remaining

    original_current = getattr(sales_guard, "_current_snapshot_for_lab", None)
    if callable(original_current) and not getattr(original_current, "__dismepe_sheet_competence__", False):
        def current_snapshot_for_lab(industries_mod, lab: str):
            path = getattr(industries_mod, "GENERAL_SALES_FILE", None)
            if path is None or not path.exists():
                return original_current(industries_mod, lab)
            try:
                import json
                snapshot = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return original_current(industries_mod, lab)

            if str(snapshot.get("competenciaVendaOrigem") or "").upper() != "PLANILHA":
                return original_current(industries_mod, lab)
            target = _normalize_competence(sales_guard._OPERATIONAL_COMPETENCE.get())
            if not target:
                return original_current(industries_mod, lab)
            return _aggregate_snapshot_for_lab(industries_mod, snapshot, lab, target)

        current_snapshot_for_lab.__dismepe_sheet_competence__ = True
        current_snapshot_for_lab.__wrapped__ = original_current
        sales_guard._current_snapshot_for_lab = current_snapshot_for_lab

    sales_sync.SNAPSHOT_SCHEMA = "VENDA_GERAL_V3_COMPETENCIA"
    sales_sync.build_snapshot = lambda raw_xlsx, *, source_item: _build_snapshot_with_competence(
        sales_sync, raw_xlsx, source_item=source_item
    )
    _INSTALLED = True
