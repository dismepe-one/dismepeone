#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
TZ = ZoneInfo("America/Recife")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean(value).replace("R$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    out: list[str] = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")))
    return out


def _sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    by_id = {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in rels.findall(f"{{{NS_PKG_REL}}}Relationship")
    }
    out: dict[str, str] = {}
    sheets = workbook.find(f"{{{NS_MAIN}}}sheets")
    if sheets is None:
        return out
    for sheet in sheets.findall(f"{{{NS_MAIN}}}sheet"):
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get(f"{{{NS_REL}}}id", "")
        target = by_id.get(rid, "")
        if not name or not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.lstrip("/")
        path = re.sub(r"(^|/)\.(/|$)", r"\1", path)
        while "/../" in path:
            parts = []
            for part in path.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                elif part not in {"", "."}:
                    parts.append(part)
            path = "/".join(parts)
        out[name] = path
    return out


def _cell_value(cell: ET.Element, shared: list[str]) -> Any:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{{{NS_MAIN}}}t"))
    v = cell.find(f"{{{NS_MAIN}}}v")
    raw = "" if v is None or v.text is None else v.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except Exception:
            return ""
    if cell_type in {"str", "e"}:
        return raw
    if raw == "":
        return None
    try:
        n = float(raw)
        return int(n) if n.is_integer() else n
    except ValueError:
        return raw


def _read_sheet(path: Path, sheet_name: str) -> list[list[Any]]:
    with zipfile.ZipFile(path, "r") as zf:
        shared = _shared_strings(zf)
        paths = _sheet_paths(zf)
        target = paths.get(sheet_name)
        if not target:
            raise RuntimeError(f"A aba '{sheet_name}' não foi encontrada em {path.name}.")
        root = ET.fromstring(zf.read(target))
        rows: list[list[Any]] = []
        sheet_data = root.find(f"{{{NS_MAIN}}}sheetData")
        if sheet_data is None:
            return rows
        for row in sheet_data.findall(f"{{{NS_MAIN}}}row"):
            values: dict[int, Any] = {}
            max_col = 0
            for cell in row.findall(f"{{{NS_MAIN}}}c"):
                ref = cell.attrib.get("r", "A1")
                letters = "".join(ch for ch in ref if ch.isalpha()).upper()
                col = 0
                for ch in letters:
                    col = col * 26 + (ord(ch) - 64)
                if col <= 0:
                    continue
                values[col] = _cell_value(cell, shared)
                max_col = max(max_col, col)
            rows.append([values.get(i) for i in range(1, max_col + 1)] if max_col else [])
        return rows


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def build_snapshot(xlsx: Path, competencia: str) -> dict[str, Any]:
    vendas = _read_sheet(xlsx, "VENDA GERAL")
    objetivos = _read_sheet(xlsx, "OBJETIVO")
    if len(vendas) < 2:
        raise RuntimeError("A aba VENDA GERAL está vazia.")
    if len(objetivos) < 2:
        raise RuntimeError("A aba OBJETIVO está vazia.")

    objective_by_lab: dict[str, float | None] = {}
    for row in objetivos[1:]:
        lab = _clean(row[0] if len(row) > 0 else "")
        if not lab:
            continue
        objective_by_lab[_key(lab)] = _number(row[1] if len(row) > 1 else None)

    lines: list[dict[str, Any]] = []
    for row in vendas[1:]:
        lab = _clean(row[0] if len(row) > 0 else "")
        sale = _number(row[1] if len(row) > 1 else None)
        if not lab or sale is None:
            continue
        lines.append({
            "laboratorio": lab,
            "competencia": competencia,
            "venda_total": round(sale, 2),
            "objetivo_total": (
                round(objective_by_lab[_key(lab)], 2)
                if objective_by_lab.get(_key(lab)) is not None
                else None
            ),
        })

    if len(lines) < 10:
        raise RuntimeError(f"Base rejeitada por segurança: somente {len(lines)} laboratórios válidos.")

    raw = xlsx.read_bytes()
    now = datetime.now(TZ)
    return {
        "idAtualizacao": now.strftime("%Y%m%d_%H%M%S") + "_" + hashlib.sha256(raw).hexdigest()[:10],
        "fonte": xlsx.name,
        "competencia": competencia,
        "gerado_em": now.strftime("%d/%m/%Y %H:%M:%S"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "linhas": lines,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa OBJETIVO X VENDA.xlsx para DISMEPE ONE INDÚSTRIAS.")
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/industries"))
    parser.add_argument("--competencia", default="")
    args = parser.parse_args()

    xlsx = args.xlsx.expanduser().resolve()
    if not xlsx.exists():
        raise SystemExit(f"Arquivo não encontrado: {xlsx}")
    now = datetime.now(TZ)
    competencia = args.competencia.strip() or f"{now.month:02d}/{now.year:04d}"
    if not re.fullmatch(r"\d{2}/\d{4}", competencia):
        raise SystemExit("Competência inválida. Use MM/AAAA.")

    snapshot = build_snapshot(xlsx, competencia)
    out_dir = args.output_dir
    current_path = out_dir / "venda_geral_atual.json"
    history_path = out_dir / "venda_geral_historico.json"

    history = _read_json(history_path, {})
    updates = history.get("atualizacoes") if isinstance(history, dict) else []
    if not isinstance(updates, list):
        updates = []
    updates = [item for item in updates if isinstance(item, dict) and item.get("sha256") != snapshot["sha256"]]
    updates.insert(0, snapshot)
    updates = updates[:3]

    _write_json(current_path, snapshot)
    _write_json(history_path, {"limiteHistorico": 3, "atualizacoes": updates})

    natulab = next((x for x in snapshot["linhas"] if _key(x.get("laboratorio")) == "NATULAB"), None)
    print(f"Base importada: {len(snapshot['linhas'])} laboratórios")
    print(f"Competência: {competencia}")
    print(f"Históricos preservados: {len(updates)} de 3")
    if natulab:
        print(f"NATULAB venda={natulab['venda_total']:.2f} objetivo={natulab['objetivo_total']}")
    print(f"Atual: {current_path}")
    print(f"Histórico: {history_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
