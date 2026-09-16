from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industries"
CURRENT_FILE = DATA_DIR / "mapa_estoque_atual.json"
FALLBACK_FILE = DATA_DIR / "mapa_estoque_2026-09-16.json"
STATE_FILE = DATA_DIR / "drive_sync_state.json"
FOLDER_CONFIG_FILE = DATA_DIR / "drive_folder_config.json"
HISTORY_DIR = DATA_DIR / "history"

_TASK: asyncio.Task | None = None
_SYNC_LOCK: asyncio.Lock | None = None

NUM = r"-?[\d.]+"
PRICE = r"-?[\d.]+,\d{2}"

_ROW_RE = re.compile(
    rf"^\s*(?P<codigo>[\d.]+)\s+(?P<descricao>.*?)(?P<curva>[A-Z]/[A-Z])\s+"
    rf"(?P<preco>{PRICE})\s+(?P<ufo>{NUM})\s+(?P<estoque>{NUM})\s+"
    rf"(?P<jun_26>{NUM})\s+(?P<jul_26>{NUM})\s+(?P<ago_26>{NUM})\s+"
    rf"(?P<set_26>{NUM})\s+(?P<media>{NUM})\s+(?P<ean>\d{{4,14}})\s+"
    rf"(?P<est_ate>\d{{2}}/\d{{2}}/\d{{4}})\s+"
    rf"(?P<ultima_entrada>\d{{2}}/\d{{2}}/\d{{4}})\s+"
    rf"(?P<quant>{NUM})\s+(?P<sugest>{NUM})\s+\[______\]\s*"
    rf"(?P<bloq_compra>BC)?\s*$"
)

_CONT_RE = re.compile(
    rf"^\s*(?P<curva>[A-Z]/[A-Z])\s+(?P<preco>{PRICE})\s+"
    rf"(?P<ufo>{NUM})\s+(?P<estoque>{NUM})\s+(?P<jun_26>{NUM})\s+"
    rf"(?P<jul_26>{NUM})\s+(?P<ago_26>{NUM})\s+(?P<set_26>{NUM})\s+"
    rf"(?P<media>{NUM})\s+(?P<ean>\d{{4,14}})\s+"
    rf"(?P<est_ate>\d{{2}}/\d{{2}}/\d{{4}})\s+"
    rf"(?P<ultima_entrada>\d{{2}}/\d{{2}}/\d{{4}})\s+"
    rf"(?P<quant>{NUM})\s+(?P<sugest>{NUM})\s+\[______\]\s*"
    rf"(?P<bloq_compra>BC)?\s*$"
)

# Caso raro do relatório Átrio em que a curva termina na primeira linha e a
# continuação da descrição aparece antes do preço na segunda linha.
_CONT_WITH_DESC_RE = re.compile(
    rf"^\s*(?P<continuacao>.*?)\s+(?P<preco>{PRICE})\s+"
    rf"(?P<ufo>{NUM})\s+(?P<estoque>{NUM})\s+(?P<jun_26>{NUM})\s+"
    rf"(?P<jul_26>{NUM})\s+(?P<ago_26>{NUM})\s+(?P<set_26>{NUM})\s+"
    rf"(?P<media>{NUM})\s+(?P<ean>\d{{4,14}})\s+"
    rf"(?P<est_ate>\d{{2}}/\d{{2}}/\d{{4}})\s+"
    rf"(?P<ultima_entrada>\d{{2}}/\d{{2}}/\d{{4}})\s+"
    rf"(?P<quant>{NUM})\s+(?P<sugest>{NUM})\s+\[______\]\s*"
    rf"(?P<bloq_compra>BC)?\s*$"
)


def _clean_spaces(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def _state_update(**changes: Any) -> dict[str, Any]:
    state = _read_json(STATE_FILE, {}) or {}
    state.update(changes)
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(STATE_FILE, state)
    return state


def _service_account_info() -> dict[str, Any] | None:
    raw = os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError as exc:
            raise RuntimeError("DISMEPE_GOOGLE_SERVICE_ACCOUNT_JSON não contém um JSON válido.") from exc

    raw_b64 = os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_B64", "").strip()
    if raw_b64:
        try:
            value = json.loads(base64.b64decode(raw_b64).decode("utf-8"))
            return value if isinstance(value, dict) else None
        except Exception as exc:
            raise RuntimeError("DISMEPE_GOOGLE_SERVICE_ACCOUNT_B64 é inválido.") from exc

    file_path = os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if file_path:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise RuntimeError("Arquivo da conta de serviço do Google não foi encontrado.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except Exception as exc:
            raise RuntimeError("Arquivo da conta de serviço do Google é inválido.") from exc
    return None


def _configured_folder_id() -> str:
    # Prioridade: variável de ambiente. No piloto, quando ela não existir,
    # usamos somente o arquivo local de configuração sem qualquer segredo.
    env_folder = os.getenv("DISMEPE_INDUSTRIES_DRIVE_FOLDER_ID", "").strip()
    if env_folder:
        return env_folder
    config = _read_json(FOLDER_CONFIG_FILE, {}) or {}
    return str(config.get("folderId") or "").strip()


def drive_sync_config() -> dict[str, Any]:
    folder_id = _configured_folder_id()
    timezone_name = os.getenv("DISMEPE_INDUSTRIES_DRIVE_TIMEZONE", "America/Recife").strip() or "America/Recife"
    hour_raw = os.getenv("DISMEPE_INDUSTRIES_DRIVE_HOUR", "10").strip()
    minute_raw = os.getenv("DISMEPE_INDUSTRIES_DRIVE_MINUTE", "0").strip()
    try:
        hour = min(23, max(0, int(hour_raw)))
    except ValueError:
        hour = 10
    try:
        minute = min(59, max(0, int(minute_raw)))
    except ValueError:
        minute = 0
    try:
        ZoneInfo(timezone_name)
    except Exception:
        timezone_name = "America/Recife"
    has_credentials = bool(
        os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        or os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_B64", "").strip()
        or os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    )
    return {
        "configured": bool(folder_id and has_credentials),
        "folderConfigured": bool(folder_id),
        "credentialsConfigured": has_credentials,
        "scheduleHour": hour,
        "scheduleMinute": minute,
        "timezone": timezone_name,
        "schedule": f"{hour:02d}:{minute:02d}",
    }


def _schedule_timezone(cfg: dict[str, Any] | None = None) -> ZoneInfo:
    cfg = cfg or drive_sync_config()
    try:
        return ZoneInfo(str(cfg.get("timezone") or "America/Recife"))
    except Exception:
        return ZoneInfo("America/Recife")


def _scheduled_today(now_local: datetime, cfg: dict[str, Any]) -> datetime:
    return now_local.replace(
        hour=int(cfg.get("scheduleHour", 10)),
        minute=int(cfg.get("scheduleMinute", 0)),
        second=0,
        microsecond=0,
    )


def _next_scheduled_local(cfg: dict[str, Any], state: dict[str, Any] | None = None) -> datetime:
    tz = _schedule_timezone(cfg)
    now = datetime.now(tz)
    state = state or {}
    scheduled = _scheduled_today(now, cfg)
    today = now.date().isoformat()
    if now < scheduled:
        return scheduled
    if state.get("lastScheduledDate") != today:
        return now
    return scheduled + timedelta(days=1)


def stock_sync_public_status() -> dict[str, Any]:
    cfg = drive_sync_config()
    state = _read_json(STATE_FILE, {}) or {}
    next_local = _next_scheduled_local(cfg, state) if cfg["configured"] else None
    return {
        **cfg,
        "running": bool(_TASK and not _TASK.done()),
        "lastStatus": state.get("lastStatus") or ("WAITING_CONFIGURATION" if not cfg["configured"] else "WAITING"),
        "lastSuccessAt": state.get("lastSuccessAt"),
        "lastAttemptAt": state.get("lastAttemptAt"),
        "lastScheduledDate": state.get("lastScheduledDate"),
        "lastScheduledRunAt": state.get("lastScheduledRunAt"),
        "nextScheduledAt": next_local.isoformat() if next_local else None,
        "lastFileName": state.get("lastFileName"),
        "lastFileModifiedTime": state.get("lastFileModifiedTime"),
        "lastRows": state.get("lastRows"),
        "lastSuppliers": state.get("lastSuppliers"),
        "lastError": state.get("lastError"),
    }


def _build_drive_service():
    info = _service_account_info()
    if not info:
        raise RuntimeError("Credencial do Google Drive não configurada.")
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError("Dependências do Google Drive não estão instaladas.") from exc
    credentials = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _newest_pdf(service: Any, folder_id: str) -> dict[str, Any] | None:
    safe_folder = folder_id.replace("'", "\\'")
    query = (
        f"'{safe_folder}' in parents and trashed = false and "
        "mimeType = 'application/pdf'"
    )
    result = service.files().list(
        q=query,
        orderBy="modifiedTime desc",
        pageSize=20,
        fields="files(id,name,mimeType,modifiedTime,size,md5Checksum)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = result.get("files") or []
    if not files:
        return None
    return files[0]


def _download_drive_file(service: Any, file_id: str) -> bytes:
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except Exception as exc:
        raise RuntimeError("Dependências do Google Drive não estão instaladas.") from exc
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    out = io.BytesIO()
    downloader = MediaIoBaseDownload(out, request, chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        if out.tell() > 30 * 1024 * 1024:
            raise RuntimeError("PDF do mapa excede o limite de 30 MB do piloto.")
    return out.getvalue()


def _pdftotext_layout(pdf_bytes: bytes) -> str:
    executable = shutil.which("pdftotext")
    if not executable:
        raise RuntimeError(
            "O leitor de PDF (pdftotext/poppler) não está instalado no servidor."
        )
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        proc = subprocess.run(
            [executable, "-layout", "-enc", "UTF-8", tmp.name, "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError("Não foi possível ler o PDF do mapa" + (f": {message}" if message else "."))
    return proc.stdout.decode("utf-8", errors="replace")


def _finish_row(raw: dict[str, Any], supplier: str) -> dict[str, str]:
    row = {k: (v or "") for k, v in raw.items()}
    row["fornecedor"] = supplier
    row["descricao"] = _clean_spaces(row.get("descricao"))
    row["bloq_compra"] = "BC" if _clean_spaces(row.get("bloq_compra")).upper() == "BC" else ""
    return {k: str(v) for k, v in row.items()}


def parse_stock_pdf(pdf_bytes: bytes, *, source_name: str = "Mapa de Estoque.pdf") -> dict[str, Any]:
    text = _pdftotext_layout(pdf_bytes)
    rows: list[dict[str, str]] = []
    suppliers: list[str] = []
    supplier = ""
    pending: dict[str, str] | None = None
    generated_at = ""
    origin_file = ""

    for line in text.splitlines():
        if not generated_at:
            match_date = re.search(r"Data:(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})", line)
            if match_date:
                generated_at = f"{match_date.group(1)} {match_date.group(2)}"
        if not origin_file:
            match_origin = re.search(r"Arquivo:([^\s]+)", line)
            if match_origin:
                origin_file = match_origin.group(1).strip()

        match_supplier = re.match(r"\s*FORNECEDOR:\s*(.+?)\s*$", line)
        if match_supplier:
            supplier = _clean_spaces(match_supplier.group(1)).upper()
            pending = None
            if supplier and supplier not in suppliers:
                suppliers.append(supplier)
            continue

        full = _ROW_RE.match(line)
        if full and supplier:
            rows.append(_finish_row(full.groupdict(), supplier))
            pending = None
            continue

        # Primeira linha de um produto cuja descrição estourou a largura da coluna.
        possible = re.match(r"^\s*([\d.]+)\s+(.*\S)\s*$", line)
        if possible and supplier:
            lead = len(line) - len(line.lstrip())
            code = possible.group(1)
            desc = possible.group(2).strip()
            if lead <= 6 and re.fullmatch(r"[\d.]+", code) and re.search(r"[A-Za-zÀ-ÿ]", desc):
                pending = {"codigo": code, "descricao": desc, "supplier": supplier}
                continue

        if pending and line.strip():
            continuation = _CONT_RE.match(line)
            if continuation:
                data = continuation.groupdict()
                data.update(codigo=pending["codigo"], descricao=pending["descricao"])
                rows.append(_finish_row(data, pending["supplier"]))
                pending = None
                continue

            # Ex.: descrição termina em "... C/16"; curva aparece no fim da
            # primeira linha e "EFER" continua na segunda antes do preço.
            curve_at_end = re.search(r"([A-Z]/[A-Z])\s*$", pending["descricao"])
            continuation_with_desc = _CONT_WITH_DESC_RE.match(line)
            if curve_at_end and continuation_with_desc:
                data = continuation_with_desc.groupdict()
                extra = _clean_spaces(data.pop("continuacao", ""))
                desc = pending["descricao"][: curve_at_end.start()].rstrip()
                if extra:
                    desc = f"{desc} {extra}".strip()
                data.update(
                    codigo=pending["codigo"],
                    descricao=desc,
                    curva=curve_at_end.group(1),
                )
                rows.append(_finish_row(data, pending["supplier"]))
                pending = None
                continue

        if line.startswith("Seleção:"):
            pending = None

    if len(rows) < 50:
        raise RuntimeError(f"PDF rejeitado: somente {len(rows)} itens reconhecidos.")
    if not suppliers:
        raise RuntimeError("PDF rejeitado: nenhum fornecedor foi reconhecido.")

    required = {
        "fornecedor", "codigo", "descricao", "curva", "preco", "estoque",
        "media", "ean", "est_ate", "ultima_entrada",
    }
    invalid = [row for row in rows if not required.issubset(row) or not row["codigo"] or not row["descricao"]]
    if invalid:
        raise RuntimeError("PDF rejeitado: existem linhas sem a estrutura obrigatória do mapa.")

    return {
        "gerado_em": generated_at or datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "arquivo_origem": origin_file,
        "fonte": source_name,
        "fornecedores": suppliers,
        "linhas": rows,
    }


def _validate_against_current(data: dict[str, Any]) -> None:
    new_count = len(data.get("linhas") or [])
    current = _read_json(CURRENT_FILE) or _read_json(FALLBACK_FILE) or {}
    old_count = len(current.get("linhas") or [])
    if old_count >= 100 and new_count < max(50, int(old_count * 0.50)):
        raise RuntimeError(
            f"PDF rejeitado por segurança: {new_count} itens; a última base válida possui {old_count}."
        )


def _save_history(data: dict[str, Any], *, file_id: str) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", file_id)[:24] or "drive"
    target = HISTORY_DIR / f"mapa_{stamp}_{safe_id}.json"
    _atomic_json(target, data)
    history = sorted(HISTORY_DIR.glob("mapa_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in history[10:]:
        try:
            old.unlink()
        except OSError:
            pass


def _sync_stock_once_blocking(force: bool = False) -> dict[str, Any]:
    cfg = drive_sync_config()
    now_iso = datetime.now(timezone.utc).isoformat()
    if not cfg["configured"]:
        return _state_update(
            lastStatus="WAITING_CONFIGURATION",
            lastAttemptAt=now_iso,
            lastError=None,
        )

    folder_id = _configured_folder_id()
    _state_update(lastStatus="CHECKING", lastAttemptAt=now_iso, lastError=None)
    service = _build_drive_service()
    newest = _newest_pdf(service, folder_id)
    if not newest:
        return _state_update(
            lastStatus="NO_PDF",
            lastAttemptAt=now_iso,
            lastError="Nenhum PDF foi encontrado na pasta configurada.",
        )

    state = _read_json(STATE_FILE, {}) or {}
    same_file = (
        state.get("lastFileId") == newest.get("id")
        and state.get("lastFileModifiedTime") == newest.get("modifiedTime")
    )
    if same_file and not force:
        return _state_update(
            lastStatus="UP_TO_DATE",
            lastAttemptAt=now_iso,
            lastError=None,
        )

    pdf_bytes = _download_drive_file(service, str(newest["id"]))
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    if not force and state.get("lastSha256") == digest:
        return _state_update(
            lastStatus="UP_TO_DATE",
            lastAttemptAt=now_iso,
            lastFileId=newest.get("id"),
            lastFileName=newest.get("name"),
            lastFileModifiedTime=newest.get("modifiedTime"),
            lastError=None,
        )

    parsed = parse_stock_pdf(pdf_bytes, source_name=str(newest.get("name") or "Mapa de Estoque.pdf"))
    _validate_against_current(parsed)
    parsed["drive_file_id"] = str(newest.get("id") or "")
    parsed["drive_modified_time"] = str(newest.get("modifiedTime") or "")
    parsed["importado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    parsed["sha256"] = digest

    _atomic_json(CURRENT_FILE, parsed)
    _save_history(parsed, file_id=str(newest.get("id") or "drive"))
    return _state_update(
        lastStatus="IMPORTED",
        lastAttemptAt=now_iso,
        lastSuccessAt=datetime.now(timezone.utc).isoformat(),
        lastFileId=newest.get("id"),
        lastFileName=newest.get("name"),
        lastFileModifiedTime=newest.get("modifiedTime"),
        lastSha256=digest,
        lastRows=len(parsed.get("linhas") or []),
        lastSuppliers=parsed.get("fornecedores") or [],
        lastError=None,
    )


async def sync_stock_once(force: bool = False) -> dict[str, Any]:
    global _SYNC_LOCK
    if _SYNC_LOCK is None:
        _SYNC_LOCK = asyncio.Lock()
    async with _SYNC_LOCK:
        try:
            return await asyncio.to_thread(_sync_stock_once_blocking, force)
        except Exception as exc:
            _state_update(
                lastStatus="ERROR",
                lastAttemptAt=datetime.now(timezone.utc).isoformat(),
                lastError=str(exc)[:700],
            )
            raise


async def _sync_loop() -> None:
    while True:
        cfg = drive_sync_config()
        if not cfg["configured"]:
            return
        tz = _schedule_timezone(cfg)
        now = datetime.now(tz)
        state = _read_json(STATE_FILE, {}) or {}
        scheduled = _scheduled_today(now, cfg)
        today = now.date().isoformat()

        # Se o servidor ficou fora exatamente às 10:00, faz uma única
        # recuperação ao voltar, sem transformar a rotina em polling.
        should_run = now >= scheduled and state.get("lastScheduledDate") != today
        if should_run:
            try:
                await sync_stock_once(force=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                _state_update(
                    lastScheduledDate=today,
                    lastScheduledRunAt=datetime.now(timezone.utc).isoformat(),
                )
            continue

        next_run = scheduled if now < scheduled else scheduled + timedelta(days=1)
        _state_update(nextScheduledAt=next_run.isoformat())
        delay = max(1.0, (next_run - now).total_seconds())
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise


async def start_stock_sync() -> None:
    global _TASK
    if not drive_sync_config()["configured"]:
        return
    if _TASK and not _TASK.done():
        return
    _TASK = asyncio.create_task(_sync_loop(), name="industries-drive-stock-sync")


async def stop_stock_sync() -> None:
    global _TASK
    if not _TASK:
        return
    _TASK.cancel()
    try:
        await _TASK
    except asyncio.CancelledError:
        pass
    _TASK = None
