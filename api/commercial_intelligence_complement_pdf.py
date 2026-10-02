from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pypdf import PdfReader


_INSTALLED = False


def _flat(value: Any) -> str:
    raw = str(value or "").lower().replace("\t", " ")
    raw = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")


_PATTERNS: dict[str, tuple[str, ...]] = {
    "codigo": (
        r"\bcodigo\b",
        r"\bcod\.?\b",
    ),
    # Neste modelo do mapa, Pc.Custo é o preço de custo médio usado
    # como base do markup da promoção.
    "precoMedio": (
        r"\bpc\.?\s*custo\b",
        r"\bpreco\s+(?:de\s+)?custo\b",
        r"\bcusto\s+medio\b",
        r"\bpreco\s+medio\b",
    ),
    "lote": (
        r"\blote\b",
    ),
    "vencimento": (
        r"\bvenc\.?\b",
        r"\bvalidade\b",
        r"\bvencimento\b",
    ),
    # Qtd neste relatório representa as últimas unidades que entraram.
    "quantidadeUltimaEntrada": (
        r"\bqtd\.?\b",
        r"\bqtde\.?\b",
        r"\bquantidade\b",
    ),
}


def _field_position(line: str, key: str) -> int | None:
    flat = _flat(line)
    for pattern in _PATTERNS[key]:
        match = re.search(pattern, flat, flags=re.I)
        if match:
            return match.start()
    return None


def _header_window(lines: list[str]) -> tuple[int, int, dict[str, int]] | None:
    best: tuple[int, int, dict[str, int]] | None = None
    for start in range(min(len(lines), 50)):
        mapping: dict[str, int] = {}
        used_end = start
        # Alguns PDFs quebram o cabeçalho em 2 ou 3 linhas.
        for offset in range(3):
            idx = start + offset
            if idx >= len(lines):
                break
            line = lines[idx]
            for key in _PATTERNS:
                if key in mapping:
                    continue
                pos = _field_position(line, key)
                if pos is not None:
                    mapping[key] = pos
                    used_end = max(used_end, idx)
        if "codigo" in mapping and "precoMedio" in mapping:
            candidate = (start, used_end, mapping)
            if best is None or len(mapping) > len(best[2]):
                best = candidate
    return best


def _first_number(value: str) -> float:
    from . import commercial_intelligence_complement as cc

    match = re.search(r"-?\d[\d.]*,\d+|-?\d+(?:\.\d+)?", str(value or ""))
    return cc._num(match.group(0)) if match else 0.0


def _extract_date(value: str) -> str:
    from . import commercial_intelligence_complement as cc

    raw = str(value or "")
    full = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", raw)
    if full:
        return cc._date_text(full.group(0).replace("-", "/"))
    month_year = re.search(r"\b\d{1,2}[/-]\d{4}\b", raw)
    return month_year.group(0).replace("-", "/") if month_year else ""


def _extract_code(value: str) -> str:
    match = re.search(r"(?<!\d)(\d{1,9})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


def _page_rows(text: str) -> list[dict[str, Any]]:
    lines = [line.rstrip("\n") for line in str(text or "").splitlines() if line.strip()]
    header = _header_window(lines)
    if header is None:
        return []

    _, header_end, mapping = header
    ordered = sorted(mapping.items(), key=lambda item: item[1])
    result: list[dict[str, Any]] = []

    for line in lines[header_end + 1:]:
        normalized = " ".join(_flat(line).split())
        if "pc.custo" in normalized or ("codigo" in normalized and "custo" in normalized):
            continue

        cells: dict[str, str] = {}
        for index, (key, start) in enumerate(ordered):
            end = ordered[index + 1][1] if index + 1 < len(ordered) else len(line)
            cells[key] = line[start:end].strip() if start < len(line) else ""

        code = _extract_code(cells.get("codigo", ""))
        if not code:
            continue

        cost = max(0.0, _first_number(cells.get("precoMedio", "")))
        lot = str(cells.get("lote", "") or "").strip()
        expiry = _extract_date(cells.get("vencimento", ""))
        qty = max(0.0, _first_number(cells.get("quantidadeUltimaEntrada", "")))

        if cost <= 0 and not lot and not expiry and qty <= 0:
            continue

        result.append({
            "codigo": code,
            "precoMedio": round(cost, 4),
            "lote": lot,
            "vencimento": expiry,
            "quantidadeUltimaEntrada": round(qty, 3),
        })
    return result


def _finalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from . import commercial_intelligence_complement as cc

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("codigo") or "").strip()
        if not code:
            continue
        target = grouped.setdefault(code, {
            "codigo": code,
            "precoMedio": 0.0,
            "lote": "",
            "vencimento": "",
            "quantidadeUltimaEntrada": 0.0,
            "lotes": [],
        })
        cost = float(row.get("precoMedio") or 0)
        if cost > 0:
            target["precoMedio"] = cost
        lot = str(row.get("lote") or "").strip()
        expiry = str(row.get("vencimento") or "").strip()
        qty = float(row.get("quantidadeUltimaEntrada") or 0)
        if lot or expiry or qty > 0:
            target["lotes"].append({
                "lote": lot,
                "vencimento": expiry,
                "quantidadeUltimaEntrada": round(qty, 3),
            })

    for target in grouped.values():
        lots = target.get("lotes") or []
        if lots:
            lots.sort(key=lambda item: cc._date_sort(str(item.get("vencimento") or "")))
            primary = lots[0]
            target["lote"] = str(primary.get("lote") or "")
            target["vencimento"] = str(primary.get("vencimento") or "")
            target["quantidadeUltimaEntrada"] = float(primary.get("quantidadeUltimaEntrada") or 0)
    return list(grouped.values())


def _parse_pdf(content: bytes) -> list[dict[str, Any]]:
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Não foi possível abrir o PDF complementar.") from exc

    rows: list[dict[str, Any]] = []
    for page in reader.pages:
        try:
            text = page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False) or ""
        except Exception:
            text = page.extract_text() or ""
        rows.extend(_page_rows(text))

    parsed = _finalize(rows)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail=(
                "O PDF foi recebido, mas não consegui identificar as linhas do relatório. "
                "São esperados os campos Código, Pc.Custo, Qtd, Venc. e, quando houver, Lote."
            ),
        )
    return parsed


def install_commercial_intelligence_complement_pdf() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence_complement as cc

    original_parse_file = cc._parse_file

    def parse_file_with_pdf(file_name: str, content: bytes) -> list[dict[str, Any]]:
        if Path(file_name).suffix.lower() == ".pdf":
            return _parse_pdf(content)
        return original_parse_file(file_name, content)

    cc._parse_file = parse_file_with_pdf
    _INSTALLED = True
