from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from .industries_stock_sync import _build_drive_service, _configured_folder_id, drive_sync_config


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industries"
CURRENT_FILE = DATA_DIR / "venda_geral_atual.json"
HISTORY_FILE = DATA_DIR / "venda_geral_historico.json"
STATE_FILE = DATA_DIR / "general_sales_sync_state.json"

TARGET_XLSX_NAME = "OBJETIVO X VENDA.xlsx"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
TZ = ZoneInfo("America/Recife")

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_TASK: asyncio.Task | None = None
_SYNC_LOCK: asyncio.Lock | None = None
_LAST_CHECK_MONOTONIC = 0.0


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _filename_key(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().casefold()


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


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp.replace(path)


def _state_update(**changes: Any) -> dict[str, Any]:
    state = _read_json(STATE_FILE, {}) or {}
    state.update(changes)
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(STATE_FILE, state)
    return state


def _sales_folder_id() -> str:
    override = os.getenv("DISMEPE_INDUSTRIES_SALES_FOLDER_ID", "").strip()
    return override or _configured_folder_id()


def _target_filename() -> str:
    return (
        os.getenv("DISMEPE_INDUSTRIES_SALES_FILE_NAME", TARGET_XLSX_NAME).strip()
        or TARGET_XLSX_NAME
    )


def _poll_seconds() -> int:
    raw = os.getenv("DISMEPE_INDUSTRIES_SALES_POLL_SECONDS", "30").strip()
    try:
        seconds = int(raw)
    except ValueError:
        seconds = 30
    return min(900, max(15, seconds))


def general_sales_sync_config() -> dict[str, Any]:
    stock_cfg = drive_sync_config()
    folder_id = _sales_folder_id()
    has_credentials = bool(stock_cfg.get("credentialsConfigured"))
    return {
        "configured": bool(folder_id and has_credentials),
        "folderConfigured": bool(folder_id),
        "credentialsConfigured": has_credentials,
        "targetFileName": _target_filename(),
        "pollSeconds": _poll_seconds(),
        "timezone": "America/Recife",
    }


def general_sales_sync_public_status() -> dict[str, Any]:
    cfg = general_sales_sync_config()
    state = _read_json(STATE_FILE, {}) or {}
    return {
        **cfg,
        "running": bool(_TASK and not _TASK.done()),
        "lastStatus": state.get("lastStatus")
        or ("WAITING_CONFIGURATION" if not cfg["configured"] else "WAITING"),
        "lastAttemptAt": state.get("lastAttemptAt"),
        "lastSuccessAt": state.get("lastSuccessAt"),
        "lastFileId": state.get("lastFileId"),
        "lastFileName": state.get("lastFileName"),
        "lastFileModifiedTime": state.get("lastFileModifiedTime"),
        "lastSha256": state.get("lastSha256"),
        "lastRows": state.get("lastRows"),
        "lastError": state.get("lastError"),
    }


def _target_xlsx(service: Any, folder_id: str) -> dict[str, Any] | None:
    safe_folder = folder_id.replace("'", "\\'")
    target_key = _filename_key(_target_filename())
    page_token: str | None = None

    while True:
        request = service.files().list(
            q=f"'{safe_folder}' in parents and trashed = false",
            orderBy="modifiedTime desc",
            pageSize=100,
            pageToken=page_token,
            fields="nextPageToken,files(id,name,mimeType,modifiedTime,size,md5Checksum)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        try:
            result = request.execute(num_retries=5)
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 429:
                raise RuntimeError(
                    "Google Drive limitou temporariamente a leitura de OBJETIVO X VENDA.xlsx."
                ) from exc
            raise

        for item in result.get("files") or []:
            if _filename_key(item.get("name")) != target_key:
                continue
            mime = str(item.get("mimeType") or "")
            if mime in {XLSX_MIME, GOOGLE_SHEET_MIME}:
                return item

        page_token = str(result.get("nextPageToken") or "").strip() or None
        if not page_token:
            return None


def _download_xlsx(service: Any, item: dict[str, Any]) -> bytes:
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except Exception as exc:
        raise RuntimeError("Dependências do Google Drive não estão instaladas.") from exc

    file_id = str(item.get("id") or "").strip()
    if not file_id:
        raise RuntimeError("Google Drive retornou OBJETIVO X VENDA.xlsx sem ID.")

    mime = str(item.get("mimeType") or "")
    if mime == GOOGLE_SHEET_MIME:
        request = service.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    out = io.BytesIO()
    downloader = MediaIoBaseDownload(out, request, chunksize=1024 * 1024)
    done = False
    max_bytes = 20 * 1024 * 1024
    while not done:
        _, done = downloader.next_chunk(num_retries=5)
        if out.tell() > max_bytes:
            raise RuntimeError("OBJETIVO X VENDA.xlsx excede o limite de segurança de 20 MB.")
    return out.getvalue()


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return [
        "".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t"))
        for si in root.findall(f"{{{NS_MAIN}}}si")
    ]


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
            parts: list[str] = []
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

    value = cell.find(f"{{{NS_MAIN}}}v")
    raw = "" if value is None or value.text is None else value.text

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
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def _read_sheet(raw_xlsx: bytes, sheet_name: str) -> list[list[Any]]:
    with zipfile.ZipFile(io.BytesIO(raw_xlsx), "r") as zf:
        shared = _shared_strings(zf)
        paths = _sheet_paths(zf)
        target = paths.get(sheet_name)
        if not target:
            raise RuntimeError(
                f"A aba '{sheet_name}' não foi encontrada em {_target_filename()}."
            )

        root = ET.fromstring(zf.read(target))
        sheet_data = root.find(f"{{{NS_MAIN}}}sheetData")
        if sheet_data is None:
            return []

        rows: list[list[Any]] = []
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

            rows.append(
                [values.get(i) for i in range(1, max_col + 1)]
                if max_col
                else []
            )

        return rows


def build_snapshot(raw_xlsx: bytes, *, source_item: dict[str, Any]) -> dict[str, Any]:
    vendas = _read_sheet(raw_xlsx, "VENDA GERAL")
    objetivos = _read_sheet(raw_xlsx, "OBJETIVO")

    if len(vendas) < 2:
        raise RuntimeError("A aba VENDA GERAL está vazia.")
    if len(objetivos) < 2:
        raise RuntimeError("A aba OBJETIVO está vazia.")

    venda_header = vendas[0] if vendas else []
    objetivo_header = objetivos[0] if objetivos else []
    if _key(venda_header[0] if len(venda_header) > 0 else "") != "FORNECEDOR":
        raise RuntimeError("Cabeçalho Fornecedor não encontrado na aba VENDA GERAL.")
    if "VENDA" not in _key(venda_header[1] if len(venda_header) > 1 else ""):
        raise RuntimeError("Cabeçalho Venda não encontrado na aba VENDA GERAL.")
    if _key(objetivo_header[0] if len(objetivo_header) > 0 else "") != "FORNECEDOR":
        raise RuntimeError("Cabeçalho Fornecedor não encontrado na aba OBJETIVO.")
    if "OBJETIVO" not in _key(objetivo_header[1] if len(objetivo_header) > 1 else ""):
        raise RuntimeError("Cabeçalho Objetivo não encontrado na aba OBJETIVO.")

    objective_by_lab: dict[str, float | None] = {}
    for row in objetivos[1:]:
        lab = _clean(row[0] if len(row) > 0 else "")
        if not lab:
            continue
        objective_by_lab[_key(lab)] = _number(row[1] if len(row) > 1 else None)

    competence = datetime.now(TZ).strftime("%m/%Y")
    lines: list[dict[str, Any]] = []
    for row in vendas[1:]:
        lab = _clean(row[0] if len(row) > 0 else "")
        sale = _number(row[1] if len(row) > 1 else None)
        if not lab or sale is None:
            continue

        objective = objective_by_lab.get(_key(lab))
        lines.append(
            {
                "laboratorio": lab,
                "competencia": competence,
                "venda_total": round(sale, 2),
                "objetivo_total": round(objective, 2) if objective is not None else None,
            }
        )

    if len(lines) < 10:
        raise RuntimeError(
            f"Base rejeitada por segurança: somente {len(lines)} laboratórios válidos."
        )

    digest = hashlib.sha256(raw_xlsx).hexdigest()
    now = datetime.now(TZ)
    return {
        "idAtualizacao": now.strftime("%Y%m%d_%H%M%S") + "_" + digest[:10],
        "fonte": str(source_item.get("name") or _target_filename()),
        "competencia": competence,
        "gerado_em": now.strftime("%d/%m/%Y %H:%M:%S"),
        "drive_file_id": str(source_item.get("id") or ""),
        "drive_modified_time": str(source_item.get("modifiedTime") or ""),
        "sha256": digest,
        "linhas": lines,
    }


def _save_snapshot(snapshot: dict[str, Any]) -> None:
    history = _read_json(HISTORY_FILE, {}) or {}
    updates = history.get("atualizacoes") if isinstance(history, dict) else []
    if not isinstance(updates, list):
        updates = []

    digest = str(snapshot.get("sha256") or "")
    updates = [
        item
        for item in updates
        if isinstance(item, dict) and str(item.get("sha256") or "") != digest
    ]
    updates.insert(0, snapshot)
    updates = updates[:3]

    _atomic_json(CURRENT_FILE, snapshot)
    _atomic_json(
        HISTORY_FILE,
        {"limiteHistorico": 3, "atualizacoes": updates},
    )


def _sync_general_sales_once_blocking(force: bool = False) -> dict[str, Any]:
    cfg = general_sales_sync_config()
    now_iso = datetime.now(timezone.utc).isoformat()

    if not cfg["configured"]:
        return _state_update(
            lastStatus="WAITING_CONFIGURATION",
            lastAttemptAt=now_iso,
            lastError=None,
        )

    _state_update(lastStatus="CHECKING", lastAttemptAt=now_iso, lastError=None)

    service = _build_drive_service()
    newest = _target_xlsx(service, _sales_folder_id())
    if not newest:
        return _state_update(
            lastStatus="TARGET_XLSX_NOT_FOUND",
            lastAttemptAt=now_iso,
            lastError=(
                f"Arquivo '{_target_filename()}' não encontrado na pasta configurada."
            ),
        )

    state = _read_json(STATE_FILE, {}) or {}
    same_file = (
        state.get("lastFileId") == newest.get("id")
        and state.get("lastFileModifiedTime") == newest.get("modifiedTime")
    )
    if same_file and CURRENT_FILE.exists() and not force:
        return _state_update(
            lastStatus="UP_TO_DATE",
            lastAttemptAt=now_iso,
            lastError=None,
        )

    raw_xlsx = _download_xlsx(service, newest)
    digest = hashlib.sha256(raw_xlsx).hexdigest()
    current = _read_json(CURRENT_FILE, {}) or {}
    if (
        not force
        and str(current.get("sha256") or "") == digest
        and isinstance(current.get("linhas"), list)
        and current.get("linhas")
    ):
        current["drive_file_id"] = str(newest.get("id") or "")
        current["drive_modified_time"] = str(newest.get("modifiedTime") or "")
        _atomic_json(CURRENT_FILE, current)
        return _state_update(
            lastStatus="UP_TO_DATE",
            lastAttemptAt=now_iso,
            lastSuccessAt=datetime.now(timezone.utc).isoformat(),
            lastFileId=newest.get("id"),
            lastFileName=newest.get("name"),
            lastFileModifiedTime=newest.get("modifiedTime"),
            lastSha256=digest,
            lastRows=len(current.get("linhas") or []),
            lastError=None,
        )

    snapshot = build_snapshot(raw_xlsx, source_item=newest)
    _save_snapshot(snapshot)

    return _state_update(
        lastStatus="IMPORTED",
        lastAttemptAt=now_iso,
        lastSuccessAt=datetime.now(timezone.utc).isoformat(),
        lastFileId=newest.get("id"),
        lastFileName=newest.get("name"),
        lastFileModifiedTime=newest.get("modifiedTime"),
        lastSha256=snapshot.get("sha256"),
        lastRows=len(snapshot.get("linhas") or []),
        lastError=None,
    )


async def sync_general_sales_once(force: bool = False) -> dict[str, Any]:
    global _SYNC_LOCK, _LAST_CHECK_MONOTONIC

    if _SYNC_LOCK is None:
        _SYNC_LOCK = asyncio.Lock()

    async with _SYNC_LOCK:
        try:
            return await asyncio.to_thread(_sync_general_sales_once_blocking, force)
        except Exception as exc:
            _state_update(
                lastStatus="ERROR",
                lastAttemptAt=datetime.now(timezone.utc).isoformat(),
                lastError=str(exc)[:700],
            )
            raise
        finally:
            _LAST_CHECK_MONOTONIC = time.monotonic()


async def ensure_general_sales_fresh(max_age_seconds: float = 10.0) -> dict[str, Any]:
    if (
        _LAST_CHECK_MONOTONIC > 0
        and time.monotonic() - _LAST_CHECK_MONOTONIC < max(1.0, max_age_seconds)
    ):
        return general_sales_sync_public_status()
    return await sync_general_sales_once(force=False)


async def _sync_loop() -> None:
    while True:
        try:
            await sync_general_sales_once(force=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        try:
            await asyncio.sleep(_poll_seconds())
        except asyncio.CancelledError:
            raise


async def start_general_sales_sync() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    _TASK = asyncio.create_task(
        _sync_loop(),
        name="industries-general-sales-drive-sync",
    )


async def stop_general_sales_sync() -> None:
    global _TASK
    if not _TASK:
        return
    _TASK.cancel()
    try:
        await _TASK
    except asyncio.CancelledError:
        pass
    _TASK = None
