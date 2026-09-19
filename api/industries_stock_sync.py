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
import sys
import tempfile
import unicodedata
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
TARGET_PDF_NAME = "Sugestão de compras com EAN.pdf"
STOCK_CACHE_MODULE = "MAPA_ESTOQUE"
WORKER_PID_FILE = DATA_DIR / "stock_worker.pid"
WORKER_LOG_FILE = DATA_DIR / "stock_worker.log"

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


def _default_schedule_values() -> list[str]:
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

    multi = os.getenv("DISMEPE_INDUSTRIES_DRIVE_SCHEDULES", "").strip()
    if multi:
        parsed = _normalize_schedule_values(re.split(r"[,;|]", multi))
        if parsed:
            return parsed
    return [f"{hour:02d}:{minute:02d}"]


def _normalize_schedule_values(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if not match:
            continue
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            continue
        normalized = f"{hour:02d}:{minute:02d}"
        if normalized not in output:
            output.append(normalized)
    output.sort()
    return output[:12]


SCHEDULE_CONFIG_KEY = "INDUSTRIES_STOCK_SYNC_SCHEDULES_V1"
_SCHEDULE_OVERRIDE: list[str] | None = None
_SCHEDULE_CONFIG_LOADED = False
_SCHEDULE_CONFIG_LOCK: asyncio.Lock | None = None
_WAKE_EVENT: asyncio.Event | None = None


def _wake_event() -> asyncio.Event:
    global _WAKE_EVENT
    if _WAKE_EVENT is None:
        _WAKE_EVENT = asyncio.Event()
    return _WAKE_EVENT


async def load_stock_sync_schedule_config(force: bool = False) -> list[str]:
    global _SCHEDULE_OVERRIDE, _SCHEDULE_CONFIG_LOADED, _SCHEDULE_CONFIG_LOCK

    if _SCHEDULE_CONFIG_LOADED and not force:
        return list(_SCHEDULE_OVERRIDE if _SCHEDULE_OVERRIDE is not None else _default_schedule_values())

    if _SCHEDULE_CONFIG_LOCK is None:
        _SCHEDULE_CONFIG_LOCK = asyncio.Lock()

    async with _SCHEDULE_CONFIG_LOCK:
        if _SCHEDULE_CONFIG_LOADED and not force:
            return list(_SCHEDULE_OVERRIDE if _SCHEDULE_OVERRIDE is not None else _default_schedule_values())

        from .config import get_settings
        import httpx

        cfg_settings = get_settings()
        endpoint = cfg_settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
        headers = {
            "apikey": cfg_settings.supabase_publishable_key,
            "x-dismepe-token": cfg_settings.edge_token,
            "content-type": "application/json",
            "accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=max(8.0, cfg_settings.request_timeout_seconds)) as client:
                response = await client.post(
                    endpoint,
                    json={"acao": "CONFIG_GET", "chave": SCHEDULE_CONFIG_KEY},
                    headers=headers,
                )
            data = response.json()
            if response.status_code >= 200 and response.status_code < 300 and data.get("sucesso") is True:
                value = data.get("valor")
                if isinstance(value, dict):
                    values = value.get("horarios")
                elif isinstance(value, list):
                    values = value
                else:
                    values = []
                parsed = _normalize_schedule_values(values)
                if isinstance(values, list):
                    _SCHEDULE_OVERRIDE = parsed  # [] significa rotina automática desativada
                _SCHEDULE_CONFIG_LOADED = True
        except Exception:
            return list(_SCHEDULE_OVERRIDE if _SCHEDULE_OVERRIDE is not None else _default_schedule_values())

    return list(_SCHEDULE_OVERRIDE if _SCHEDULE_OVERRIDE is not None else _default_schedule_values())


async def set_stock_sync_schedules(values: list[str]) -> list[str]:
    global _SCHEDULE_OVERRIDE, _SCHEDULE_CONFIG_LOADED
    parsed = _normalize_schedule_values(values)
    _SCHEDULE_OVERRIDE = parsed  # [] desativa a execução automática.
    _SCHEDULE_CONFIG_LOADED = True
    _wake_event().set()
    return list(parsed)


def drive_sync_config() -> dict[str, Any]:
    folder_id = _configured_folder_id()
    timezone_name = os.getenv("DISMEPE_INDUSTRIES_DRIVE_TIMEZONE", "America/Recife").strip() or "America/Recife"
    try:
        ZoneInfo(timezone_name)
    except Exception:
        timezone_name = "America/Recife"

    schedules = list(_SCHEDULE_OVERRIDE if _SCHEDULE_OVERRIDE is not None else _default_schedule_values())
    first = schedules[0] if schedules else "10:00"
    hour, minute = [int(x) for x in first.split(":")]

    has_credentials = bool(
        os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        or os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_B64", "").strip()
        or os.getenv("DISMEPE_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    )
    return {
        "configured": bool(folder_id and has_credentials),
        "folderConfigured": bool(folder_id),
        "credentialsConfigured": has_credentials,
        "targetFileName": TARGET_PDF_NAME,
        "scheduleHour": hour,
        "scheduleMinute": minute,
        "timezone": timezone_name,
        "schedule": ", ".join(schedules),
        "schedules": schedules,
        "automaticEnabled": bool(schedules),
    }


def _schedule_timezone(cfg: dict[str, Any] | None = None) -> ZoneInfo:
    cfg = cfg or drive_sync_config()
    try:
        return ZoneInfo(str(cfg.get("timezone") or "America/Recife"))
    except Exception:
        return ZoneInfo("America/Recife")


def _schedule_datetimes_for_day(now_local: datetime, cfg: dict[str, Any]) -> list[tuple[str, datetime]]:
    schedules = _normalize_schedule_values(cfg.get("schedules"))
    output: list[tuple[str, datetime]] = []
    for value in schedules:
        hour, minute = [int(x) for x in value.split(":")]
        dt = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        output.append((value, dt))
    output.sort(key=lambda item: item[1])
    return output


def _completed_schedule_keys(state: dict[str, Any]) -> set[str]:
    values = state.get("lastScheduledKeys")
    if not isinstance(values, list):
        values = []
    return {str(x) for x in values if str(x).strip()}


def _next_scheduled_local(cfg: dict[str, Any], state: dict[str, Any] | None = None) -> datetime | None:
    tz = _schedule_timezone(cfg)
    now = datetime.now(tz)
    state = state or {}
    completed = _completed_schedule_keys(state)

    today_rows = _schedule_datetimes_for_day(now, cfg)
    if not today_rows:
        return None  # Sem horários: nenhuma execução automática futura.
    due = [
        (value, dt)
        for value, dt in today_rows
        if dt <= now and f"{now.date().isoformat()}|{value}" not in completed
    ]
    if due:
        return now

    for value, dt in today_rows:
        if dt > now:
            return dt

    tomorrow = now + timedelta(days=1)
    tomorrow_rows = _schedule_datetimes_for_day(tomorrow, cfg)
    return tomorrow_rows[0][1] if tomorrow_rows else tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)


def _read_worker_pid() -> int | None:
    try:
        value = int(WORKER_PID_FILE.read_text(encoding="utf-8").strip())
        return value if value > 0 else None
    except Exception:
        return None


def _worker_is_running() -> bool:
    pid = _read_worker_pid()
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        try:
            WORKER_PID_FILE.unlink()
        except OSError:
            pass
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def stock_sync_public_status() -> dict[str, Any]:
    cfg = drive_sync_config()
    state = _read_json(STATE_FILE, {}) or {}
    next_local = _next_scheduled_local(cfg, state) if cfg["configured"] and cfg["automaticEnabled"] else None
    return {
        **cfg,
        "running": bool(_TASK and not _TASK.done()),
        "workerRunning": _worker_is_running(),
        "workerPid": _read_worker_pid(),
        "lastStatus": state.get("lastStatus") or ("WAITING_CONFIGURATION" if not cfg["configured"] else "WAITING"),
        "lastSuccessAt": state.get("lastSuccessAt"),
        "lastAttemptAt": state.get("lastAttemptAt"),
        "lastScheduledDate": state.get("lastScheduledDate"),
        "lastScheduledRunAt": state.get("lastScheduledRunAt"),
        "lastScheduledKeys": state.get("lastScheduledKeys") if isinstance(state.get("lastScheduledKeys"), list) else [],
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


def _drive_filename_key(value: Any) -> str:
    # Google Drive, macOS e Windows podem representar o mesmo acento com
    # sequências Unicode diferentes. NFC evita que isso quebre a rotina diária.
    return unicodedata.normalize("NFC", str(value or "")).strip().casefold()


def _target_pdf(service: Any, folder_id: str) -> dict[str, Any] | None:
    safe_folder = folder_id.replace("'", "\\'")
    safe_name = TARGET_PDF_NAME.replace("'", "\\'")
    query = (
        f"'{safe_folder}' in parents and trashed = false and "
        "mimeType = 'application/pdf' and "
        f"name = '{safe_name}'"
    )
    request = service.files().list(
        q=query,
        orderBy="modifiedTime desc",
        pageSize=10,
        fields="files(id,name,mimeType,modifiedTime,size,md5Checksum)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    )
    try:
        result = request.execute(num_retries=5)
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 429:
            raise RuntimeError(
                "Google Drive limitou temporariamente a leitura (HTTP 429) "
                "mesmo após tentativas automáticas. A última base válida permanece ativa."
            ) from exc
        raise
    target_key = _drive_filename_key(TARGET_PDF_NAME)
    for item in result.get("files") or []:
        if _drive_filename_key(item.get("name")) == target_key:
            return item
    return None


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
        _, done = downloader.next_chunk(num_retries=5)
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


def _parse_stock_pdf_layout(pdf_bytes: bytes, *, source_name: str = "Mapa de Estoque.pdf") -> dict[str, Any]:
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


def _pdftotext_tsv(pdf_bytes: bytes) -> str:
    executable = shutil.which("pdftotext")
    if not executable:
        raise RuntimeError(
            "O leitor de PDF (pdftotext/poppler) não está instalado no servidor."
        )
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        proc = subprocess.run(
            [executable, "-tsv", "-enc", "UTF-8", tmp.name, "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError("Não foi possível ler o PDF do mapa" + (f": {message}" if message else "."))
    return proc.stdout.decode("utf-8", errors="replace")


_TSV_CODE_RE = re.compile(r"^[\d.]+$")
_TSV_NUM_RE = re.compile(r"^-?[\d.]+$")
_TSV_VALID_NUM_RE = re.compile(r"^-?(?:\d+|\d{1,3}(?:\.\d{3})+)$")
_TSV_PRICE_RE = re.compile(r"^-?[\d.]+,\d{2}$")
_TSV_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TSV_CURVE_RE = re.compile(r"^[A-Z]/[A-Z]$")
_TSV_NUMERIC_RIGHTS = (285.0, 309.6, 333.6, 357.6, 381.6, 405.6, 429.6)
_TSV_CHAR_WIDTH = 4.2


def _tsv_number_splits(value: str, parts_count: int) -> list[list[str]]:
    result: list[list[str]] = []

    def walk(pos: int, parts: list[str]) -> None:
        remaining = parts_count - len(parts)
        if remaining == 0:
            if pos == len(value):
                result.append(parts[:])
            return
        max_end = min(len(value) - (remaining - 1), pos + 11)
        for end in range(pos + 1, max_end + 1):
            part = value[pos:end]
            if _TSV_VALID_NUM_RE.fullmatch(part):
                walk(end, [*parts, part])

    walk(0, [])
    return result


def _tsv_numeric_columns(record: list[dict[str, Any]], row_top: float) -> list[str]:
    tokens = [
        word
        for word in record
        if 265 <= word["left"] < 430
        and abs(word["top"] - row_top) < 1.0
        and _TSV_NUM_RE.fullmatch(word["text"])
    ]
    candidates: dict[int, list[tuple[float, int, int, list[str]]]] = {}
    for token_index, word in enumerate(tokens):
        value = word["text"]
        for start in range(7):
            for count in range(1, 8 - start):
                for parts in _tsv_number_splits(value, count):
                    starts = [
                        _TSV_NUMERIC_RIGHTS[start + offset] - _TSV_CHAR_WIDTH * len(part)
                        for offset, part in enumerate(parts)
                    ]
                    predicted_left = min(starts)
                    predicted_right = _TSV_NUMERIC_RIGHTS[start + count - 1]
                    score = abs(predicted_left - word["left"]) + 0.5 * abs(
                        predicted_right - word["right"]
                    )
                    if score <= 18:
                        candidates.setdefault(start, []).append(
                            (score, token_index, count, parts)
                        )

    best_score = float("inf")
    best_values: list[str] | None = None

    def solve(
        field_index: int,
        used: set[int],
        values: list[str],
        score: float,
    ) -> None:
        nonlocal best_score, best_values
        if score >= best_score:
            return
        if field_index >= 7:
            final_score = score + 5.0 * (len(tokens) - len(used))
            if final_score < best_score:
                best_score = final_score
                best_values = values[:]
            return

        for cand_score, token_index, count, parts in candidates.get(field_index, []):
            if token_index not in used:
                solve(
                    field_index + count,
                    used | {token_index},
                    [*values, *parts],
                    score + cand_score,
                )

        solve(field_index + 1, used, [*values, ""], score + 25.0)

    solve(0, set(), [], 0.0)
    return (best_values or [""] * 7)[:7]


def _parse_stock_pdf_tsv(
    pdf_bytes: bytes,
    *,
    source_name: str = "Mapa de Estoque.pdf",
) -> dict[str, Any]:
    tsv = _pdftotext_tsv(pdf_bytes)
    words: list[dict[str, Any]] = []
    generated_at = ""
    origin_file = ""

    for raw in tsv.splitlines()[1:]:
        cols = raw.split("\t", 11)
        if len(cols) != 12 or cols[0] != "5":
            continue
        try:
            word = {
                "page": int(cols[1]),
                "left": float(cols[6]),
                "top": float(cols[7]),
                "width": float(cols[8]),
                "text": cols[11],
            }
        except (TypeError, ValueError):
            continue

        word["right"] = word["left"] + word["width"]
        words.append(word)

        if not generated_at and word["text"].startswith("Data:"):
            generated_at = word["text"].split("Data:", 1)[-1]
        elif (
            generated_at
            and len(generated_at) == 10
            and re.fullmatch(r"\d{2}:\d{2}:\d{2}", word["text"])
        ):
            generated_at += " " + word["text"]

        if not origin_file and word["text"].startswith("Arquivo:"):
            origin_file = word["text"].split("Arquivo:", 1)[-1].strip()

    pages: dict[int, list[dict[str, Any]]] = {}
    for word in words:
        pages.setdefault(word["page"], []).append(word)

    rows: list[dict[str, str]] = []
    suppliers: list[str] = []

    def first(items: list[dict[str, Any]], key=lambda word: 0):
        return min(items, key=key) if items else None

    for page_number in sorted(pages):
        page_words = sorted(
            pages[page_number],
            key=lambda word: (word["top"], word["left"]),
        )
        supplier = ""
        for word in page_words:
            if word["text"].startswith("FORNECEDOR:"):
                y = word["top"]
                same_line = sorted(
                    [
                        item
                        for item in page_words
                        if abs(item["top"] - y) < 0.2 and item["left"] < 216
                    ],
                    key=lambda item: item["left"],
                )
                supplier_line = " ".join(item["text"] for item in same_line)
                supplier = _clean_spaces(
                    supplier_line.split("FORNECEDOR:", 1)[-1]
                ).upper()
                break

        if supplier and supplier not in suppliers:
            suppliers.append(supplier)

        starts = [
            word
            for word in page_words
            if 15 <= word["left"] < 45
            and word["top"] > 90
            and _TSV_CODE_RE.fullmatch(word["text"])
        ]
        totals = sorted(
            {
                word["top"]
                for word in page_words
                if word["text"] == "Totais" and 45 <= word["left"] < 80
            }
        )
        footers = sorted(
            {
                word["top"]
                for word in page_words
                if word["text"].startswith("Seleção:") and word["left"] < 40
            }
        )

        for index, start_word in enumerate(starts):
            bounds = (
                ([starts[index + 1]["top"]] if index + 1 < len(starts) else [])
                + [value for value in totals if value > start_word["top"]]
                + [value for value in footers if value > start_word["top"]]
                + [560.0]
            )
            end_top = min(bounds)
            record = [
                word
                for word in page_words
                if start_word["top"] - 0.1 <= word["top"] < end_top
            ]

            curve = first(
                [
                    word
                    for word in record
                    if 205 <= word["left"] < 238
                    and _TSV_CURVE_RE.fullmatch(word["text"])
                ],
                key=lambda word: abs(word["left"] - 216.6),
            )
            price = first(
                [
                    word
                    for word in record
                    if 225 <= word["left"] < 270
                    and _TSV_PRICE_RE.fullmatch(word["text"])
                ],
                key=lambda word: (
                    abs(word["top"] - start_word["top"]),
                    abs(word["right"] - 265.8),
                ),
            )

            numeric = _tsv_numeric_columns(record, start_word["top"])

            ean_words = [
                word
                for word in record
                if 430 <= word["left"] < 500
                and not _TSV_DATE_RE.fullmatch(word["text"])
            ]
            ean = _clean_spaces(
                " ".join(
                    word["text"]
                    for word in sorted(
                        ean_words,
                        key=lambda item: (item["top"], item["left"]),
                    )
                )
            )

            est_ate = first(
                [
                    word
                    for word in record
                    if 495 <= word["left"] < 536
                    and _TSV_DATE_RE.fullmatch(word["text"])
                ],
                key=lambda word: (word["top"], word["left"]),
            )
            ultima = first(
                [
                    word
                    for word in record
                    if 532 <= word["left"] < 585
                    and _TSV_DATE_RE.fullmatch(word["text"])
                ],
                key=lambda word: (word["top"], word["left"]),
            )

            tail = sorted(
                [
                    word
                    for word in record
                    if 555 <= word["left"] < 624.5
                    and _TSV_NUM_RE.fullmatch(word["text"])
                ],
                key=lambda word: (word["top"], word["left"]),
            )
            quant = first(
                tail,
                key=lambda word: abs(word["right"] - 594.6),
            )
            sugest = (
                first(
                    [word for word in tail if word is not quant],
                    key=lambda word: abs(word["right"] - 621.6),
                )
                if len(tail) > 1
                else None
            )
            blocked = first(
                [
                    word
                    for word in record
                    if word["left"] >= 645 and word["text"].upper() == "BC"
                ]
            )

            excluded = {id(start_word), *(id(word) for word in ean_words)}
            for selected in (curve, price, est_ate, ultima, quant, sugest, blocked):
                if selected:
                    excluded.add(id(selected))

            for word in record:
                if (
                    265 <= word["left"] < 430
                    and abs(word["top"] - start_word["top"]) < 1.0
                    and _TSV_NUM_RE.fullmatch(word["text"])
                ):
                    excluded.add(id(word))

            description_words = [
                word
                for word in record
                if id(word) not in excluded
                and 48 <= word["left"] < 305
                and word["text"]
                not in {
                    "Código",
                    "Descrição",
                    "Curva",
                    "Preço",
                    "UFO",
                    "Resumo",
                    "Tot.Unds.",
                    "Tot.Pc.Custo",
                    "Tot.Pc.Venda",
                }
            ]
            description = _clean_spaces(
                " ".join(
                    word["text"]
                    for word in sorted(
                        description_words,
                        key=lambda item: (item["top"], item["left"]),
                    )
                )
            )

            raw_row = {
                "codigo": start_word["text"],
                "descricao": description,
                "curva": curve["text"] if curve else "",
                "preco": price["text"] if price else "",
                "ufo": numeric[0],
                "estoque": numeric[1],
                "jun_26": numeric[2],
                "jul_26": numeric[3],
                "ago_26": numeric[4],
                "set_26": numeric[5],
                "media": numeric[6],
                "ean": ean,
                "est_ate": est_ate["text"] if est_ate else "",
                "ultima_entrada": ultima["text"] if ultima else "",
                "quant": quant["text"] if quant else "",
                "sugest": sugest["text"] if sugest else "",
                "bloq_compra": "BC" if blocked else "",
            }

            if (
                supplier
                and raw_row["codigo"]
                and raw_row["descricao"]
                and raw_row["curva"]
                and raw_row["preco"]
                and raw_row["estoque"] != ""
                and raw_row["media"] != ""
            ):
                rows.append(_finish_row(raw_row, supplier))

    if len(rows) < 50 or not suppliers:
        raise RuntimeError(
            f"Leitura posicional insuficiente: {len(rows)} itens e "
            f"{len(suppliers)} fornecedores."
        )

    return {
        "gerado_em": generated_at
        or datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "arquivo_origem": origin_file,
        "fonte": source_name,
        "fornecedores": suppliers,
        "linhas": rows,
    }


def parse_stock_pdf(
    pdf_bytes: bytes,
    *,
    source_name: str = "Mapa de Estoque.pdf",
) -> dict[str, Any]:
    try:
        return _parse_stock_pdf_tsv(pdf_bytes, source_name=source_name)
    except Exception:
        # Compatibilidade: se o Poppler do ambiente não suportar TSV ou
        # aparecer um relatório legado, preserva exatamente o parser anterior.
        return _parse_stock_pdf_layout(pdf_bytes, source_name=source_name)

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


def _persist_stock_snapshot_blocking(data: dict[str, Any]) -> None:
    from .config import get_settings
    import httpx

    cfg_settings = get_settings()
    endpoint = cfg_settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    headers = {
        "apikey": cfg_settings.supabase_publishable_key,
        "x-dismepe-token": cfg_settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = {
        "acao": "CACHE_SET",
        "modulo": STOCK_CACHE_MODULE,
        "payload": data,
        "atualizado_por": "STOCK_WORKER",
        "nome": TARGET_PDF_NAME,
        "tamanho": len(encoded),
        "versao": "PROD5.9.8.23.13_FAST_PARSER_V1",
    }
    try:
        with httpx.Client(timeout=max(60.0, cfg_settings.request_timeout_seconds)) as client:
            response = client.post(endpoint, json=body, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise RuntimeError("Não foi possível persistir o mapa no Supabase.") from exc

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"O Supabase respondeu em formato inválido (HTTP {response.status_code})."
        ) from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(
            str(result.get("erro") or result.get("error") or f"Supabase HTTP {response.status_code}.")
        )
    if result.get("sucesso") is not True and result.get("success") is not True and result.get("ok") is not True:
        raise RuntimeError(
            str(result.get("erro") or result.get("error") or "O Supabase não confirmou a gravação do mapa.")
        )


def _load_persisted_stock_snapshot_blocking() -> dict[str, Any] | None:
    # Lê somente o último mapa confirmado no Supabase.
    # Falha desta consulta nunca derruba a atualização.
    from .config import get_settings
    import httpx

    cfg_settings = get_settings()
    endpoint = cfg_settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    headers = {
        "apikey": cfg_settings.supabase_publishable_key,
        "x-dismepe-token": cfg_settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    try:
        with httpx.Client(timeout=max(15.0, cfg_settings.request_timeout_seconds)) as client:
            response = client.post(
                endpoint,
                json={"acao": "CACHE_GET", "modulo": STOCK_CACHE_MODULE},
                headers=headers,
            )
        if response.status_code < 200 or response.status_code >= 300:
            return None
        result = response.json()
    except Exception:
        return None

    if result.get("sucesso") is not True or result.get("encontrado") is not True:
        return None
    cache = result.get("cache")
    if not isinstance(cache, dict):
        return None
    payload = cache.get("payload")
    return payload if isinstance(payload, dict) else None


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
    newest = _target_pdf(service, folder_id)
    if not newest:
        return _state_update(
            lastStatus="TARGET_PDF_NOT_FOUND",
            lastAttemptAt=now_iso,
            lastError=f"Arquivo '{TARGET_PDF_NAME}' não encontrado na pasta configurada.",
        )

    state = _read_json(STATE_FILE, {}) or {}
    persisted = _load_persisted_stock_snapshot_blocking() or {}

    local_same_file = (
        state.get("lastFileId") == newest.get("id")
        and state.get("lastFileModifiedTime") == newest.get("modifiedTime")
    )
    persisted_same_file = (
        persisted.get("drive_file_id") == newest.get("id")
        and persisted.get("drive_modified_time") == newest.get("modifiedTime")
    )
    if (local_same_file or persisted_same_file) and not force:
        return _state_update(
            lastStatus="UP_TO_DATE",
            lastAttemptAt=now_iso,
            lastFileId=newest.get("id"),
            lastFileName=newest.get("name"),
            lastFileModifiedTime=newest.get("modifiedTime"),
            lastSha256=persisted.get("sha256") or state.get("lastSha256"),
            lastRows=len(persisted.get("linhas") or []) or state.get("lastRows"),
            lastSuppliers=persisted.get("fornecedores") or state.get("lastSuppliers") or [],
            lastError=None,
        )

    _state_update(lastStatus="DOWNLOADING", lastAttemptAt=now_iso, lastError=None)
    pdf_bytes = _download_drive_file(service, str(newest["id"]))
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    known_sha = state.get("lastSha256") or persisted.get("sha256")
    if not force and known_sha == digest:
        if persisted:
            persisted = dict(persisted)
            persisted["drive_file_id"] = str(newest.get("id") or "")
            persisted["drive_modified_time"] = str(newest.get("modifiedTime") or "")
            _persist_stock_snapshot_blocking(persisted)
        return _state_update(
            lastStatus="UP_TO_DATE",
            lastAttemptAt=now_iso,
            lastFileId=newest.get("id"),
            lastFileName=newest.get("name"),
            lastFileModifiedTime=newest.get("modifiedTime"),
            lastSha256=digest,
            lastRows=len(persisted.get("linhas") or []) or state.get("lastRows"),
            lastSuppliers=persisted.get("fornecedores") or state.get("lastSuppliers") or [],
            lastError=None,
        )

    _state_update(lastStatus="PARSING", lastAttemptAt=now_iso, lastError=None)

    parsed = parse_stock_pdf(pdf_bytes, source_name=str(newest.get("name") or "Mapa de Estoque.pdf"))
    _validate_against_current(parsed)
    parsed["drive_file_id"] = str(newest.get("id") or "")
    parsed["drive_modified_time"] = str(newest.get("modifiedTime") or "")
    parsed["importado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    parsed["sha256"] = digest

    _state_update(lastStatus="PERSISTING", lastAttemptAt=now_iso, lastError=None)
    _persist_stock_snapshot_blocking(parsed)
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


def _launch_stock_worker(force: bool = False) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    if _worker_is_running():
        return _state_update(
            lastStatus="RUNNING",
            lastAttemptAt=now_iso,
            workerPid=_read_worker_pid(),
            lastError=None,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    command = [sys.executable, "-m", "api.industries_stock_worker"]
    if force:
        command.append("--force")

    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        start_new_session=True,
        close_fds=True,
        env=os.environ.copy(),
    )

    WORKER_PID_FILE.write_text(str(process.pid), encoding="utf-8")
    return _state_update(
        lastStatus="QUEUED",
        lastAttemptAt=now_iso,
        workerPid=process.pid,
        lastError=None,
    )


async def sync_stock_once(force: bool = False) -> dict[str, Any]:
    global _SYNC_LOCK
    if _SYNC_LOCK is None:
        _SYNC_LOCK = asyncio.Lock()
    async with _SYNC_LOCK:
        return await asyncio.to_thread(_launch_stock_worker, force)


async def _sync_loop() -> None:
    while True:
        await load_stock_sync_schedule_config()
        cfg = drive_sync_config()
        if not cfg["configured"]:
            return

        if not cfg['automaticEnabled']:
            _state_update(nextScheduledAt=None)
            event = _wake_event()
            event.clear()
            try:
                await event.wait()  # Aguardar um novo horário salvo, sem verificar o PDF.
            except asyncio.CancelledError:
                raise
            continue

        tz = _schedule_timezone(cfg)
        now = datetime.now(tz)
        state = _read_json(STATE_FILE, {}) or {}
        completed = _completed_schedule_keys(state)
        rows = _schedule_datetimes_for_day(now, cfg)
        today = now.date().isoformat()

        due = [
            (value, dt)
            for value, dt in rows
            if dt <= now and f"{today}|{value}" not in completed
        ]

        if due:
            try:
                await sync_stock_once(force=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                for value, _dt in due:
                    completed.add(f"{today}|{value}")
                keep_after = (now.date() - timedelta(days=3)).isoformat()
                completed = {
                    key for key in completed
                    if key.split("|", 1)[0] >= keep_after
                }
                _state_update(
                    lastScheduledDate=today,
                    lastScheduledRunAt=datetime.now(timezone.utc).isoformat(),
                    lastScheduledKeys=sorted(completed),
                )
            continue

        next_run = _next_scheduled_local(cfg, state)
        _state_update(nextScheduledAt=next_run.isoformat())
        delay = max(1.0, (next_run - now).total_seconds())

        event = _wake_event()
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise


async def start_stock_sync() -> None:
    global _TASK
    await load_stock_sync_schedule_config()
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
