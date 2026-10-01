from __future__ import annotations

import io
import json
import re
import unicodedata
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Request, Response
from fastapi.responses import FileResponse

from .cache_reads import cache_get
from .config import get_settings
from .security import decode_session_token

router = APIRouter()
settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "crm.html"
CRM_BUILD = "CRM-DEV1-20261001"
CRM_MODULE = "CRM_VENDAS_V1"
STOCK_JSON = ROOT / "data" / "industries" / "mapa_estoque_atual.json"
STOCK_FALLBACK = ROOT / "data" / "industries" / "mapa_estoque_2026-09-16.json"


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", str(v or ""))
                  .encode("ascii", "ignore").decode("ascii").upper()).strip()


def _admin_danton(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(401, "Sessão ausente.")
    try:
        profile = decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sessão inválida.") from exc
    tipo = _norm(profile.get("tipo"))
    usuario = _norm(profile.get("usuario") or profile.get("sub"))
    if tipo not in {"ADMIN", "ADMINISTRADOR"} or usuario != "DANTON":
        raise HTTPException(403, "CRM em desenvolvimento: acesso exclusivo do administrador Danton.")
    return profile


def _json(data: dict[str, Any], status: int = 200) -> Response:
    return Response(
        content=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        status_code=status,
        media_type="application/json",
        headers={"Cache-Control": "no-store, private", "X-DISMEPE-CRM": CRM_BUILD},
    )


async def _edge(acao: str, payload: dict[str, Any]) -> dict[str, Any]:
    import httpx
    url = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        response = await client.post(
            url,
            json={"acao": acao, **payload},
            headers={
                "apikey": settings.supabase_publishable_key,
                "x-dismepe-token": settings.edge_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Serviço de dados não retornou JSON válido.") from exc
    if not response.is_success or not isinstance(data, dict) or data.get("sucesso") is not True:
        raise RuntimeError(str(data.get("erro") if isinstance(data, dict) else "Falha no serviço de dados."))
    return data


def _stock_map() -> dict[str, dict[str, Any]]:
    for path in (STOCK_JSON, STOCK_FALLBACK):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            rows = obj.get("linhas") if isinstance(obj, dict) else []
            if isinstance(rows, list):
                return {re.sub(r"\D", "", str(r.get("codigo") or "")): r for r in rows if r.get("codigo")}
        except Exception:
            continue
    return {}


async def _positivacao_owner_map() -> dict[str, dict[str, Any]]:
    try:
        payload, _ = await cache_get(modulo="POSITIVACAO_GERAL_V1", settings=settings)
        if payload.get("schema") != "POSITIVACAO_GERAL_V1" or not payload.get("zip"):
            return {}
        import base64, zlib
        raw = zlib.decompress(base64.b64decode(payload["zip"], validate=True))
        data = json.loads(raw)
        rows = data.get("clientes") if isinstance(data, dict) else []
        return {str(r.get("codigo")): r for r in rows if isinstance(r, dict) and r.get("codigo")}
    except Exception:
        return {}


def _row_to_db(row: dict[str, Any], source: str) -> dict[str, Any]:
    def num(v, default=0):
        try:
            return float(v)
        except Exception:
            return default
    data = row.get("Data")
    if isinstance(data, datetime):
        d = data.date().isoformat()
    elif isinstance(data, date):
        d = data.isoformat()
    else:
        d = str(data or "").strip()[:10]
        if "/" in d:
            try:
                d = datetime.strptime(d, "%d/%m/%Y").date().isoformat()
            except ValueError:
                pass
    nf = int(float(row.get("Número NF") or 0))
    cliente = int(float(row.get("Cód. Cliente") or 0))
    produto = int(float(row.get("Cód. Produto") or 0))
    return {
        "data_venda": d,
        "numero_nf": nf,
        "cod_cliente": cliente,
        "cod_produto": produto,
        "total_unidade": num(row.get("Total Unidade")),
        "venda_liquida": num(row.get("Venda Líquida (R$)")),
        "fornecedor": str(row.get("Fornecedor") or "").strip(),
        "chave_origem": f"{d}|{nf}|{cliente}|{produto}|{num(row.get('Total Unidade'))}|{num(row.get('Venda Líquida (R$)'))}",
        "origem_arquivo": source,
    }


@router.get("/crm", include_in_schema=False)
async def crm_page(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store, private"})


@router.get("/crm/api/acesso")
async def crm_access(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    return _json({"sucesso": True, "usuario": "DANTON", "build": CRM_BUILD})


@router.get("/crm/api/resumo")
async def crm_summary(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_RESUMO", {})
    result["build"] = CRM_BUILD
    return _json(result)


@router.get("/crm/api/produtos")
async def crm_products(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_PRODUTOS", {})
    result["build"] = CRM_BUILD
    return _json(result)


@router.get("/crm/api/clientes")
async def crm_clients(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_CLIENTES", {})
    result["build"] = CRM_BUILD
    return _json(result)


CRM_UPLOAD_DIR = Path("/tmp/dismepe_crm_imports")
CRM_CHUNK_SIZE = 4 * 1024 * 1024
CRM_MAX_UPLOAD = 35 * 1024 * 1024
CRM_EXPECTED_HEADERS = ["Data", "Número NF", "Cód. Cliente", "Total Unidade", "Venda Líquida (R$)", "Fornecedor", "Cód. Produto"]


def _crm_upload_path(importacao_id: str) -> Path:
    CRM_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return CRM_UPLOAD_DIR / (importacao_id + ".part")


async def _crm_send_batch_with_retry(batch: list[dict[str, Any]], importacao_id: str) -> None:
    last: Exception | None = None
    for tentativa in range(3):
        try:
            await _edge("CRM_VENDAS_IMPORTAR", {
                "registros": batch,
                "importacao_id": importacao_id,
            })
            return
        except Exception as exc:
            last = exc
            if tentativa < 2:
                import asyncio
                await asyncio.sleep(2 * (tentativa + 1))
    raise last or RuntimeError("Falha ao importar lote CRM.")


async def _crm_process_import_file(path: Path, filename: str, importacao_id: str) -> None:
    try:
        ext = "csv" if filename.lower().endswith(".csv") else "xlsx"
        source = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{importacao_id[:8]}.{ext}"
        if ext == "csv":
            import csv
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                raw_lines = sum(1 for _ in fh)
            total_linhas = max(0, raw_lines - 1)
            await _edge("CRM_IMPORT_ATUALIZAR", {
                "importacao_id": importacao_id,
                "processadas": 0,
                "total_linhas": total_linhas,
            })
            fh = path.open("r", encoding="utf-8-sig", newline="")
            try:
                reader = csv.DictReader(fh)
                headers = [str(x or "").strip() for x in (reader.fieldnames or [])]
                if headers[:7] != CRM_EXPECTED_HEADERS:
                    raise ValueError("Cabeçalhos incompatíveis. Esperado: Data, Número NF, Cód. Cliente, Total Unidade, Venda Líquida (R$), Fornecedor, Cód. Produto.")
                rows = reader
                batch: list[dict[str, Any]] = []
                processadas = 0
                for row in rows:
                    if not row or all(v is None or str(v).strip() == "" for v in row.values()):
                        continue
                    dbrow = _row_to_db(row, source)
                    if dbrow["cod_cliente"] <= 0 or dbrow["cod_produto"] <= 0 or not dbrow["data_venda"]:
                        continue
                    batch.append(dbrow)
                    if len(batch) >= 1000:
                        await _crm_send_batch_with_retry(batch, importacao_id)
                        processadas += len(batch)
                        await _edge("CRM_IMPORT_ATUALIZAR", {"importacao_id": importacao_id, "processadas": processadas, "total_linhas": total_linhas})
                        batch = []
                if batch:
                    await _crm_send_batch_with_retry(batch, importacao_id)
                    processadas += len(batch)
                    await _edge("CRM_IMPORT_ATUALIZAR", {"importacao_id": importacao_id, "processadas": processadas, "total_linhas": total_linhas})
            finally:
                fh.close()
        else:
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                ws = wb.active
                total_linhas = max(0, int(ws.max_row or 0) - 1)
                await _edge("CRM_IMPORT_ATUALIZAR", {
                    "importacao_id": importacao_id,
                    "processadas": 0,
                    "total_linhas": total_linhas,
                })
                rows = (dict(zip(CRM_EXPECTED_HEADERS, values)) for values in ws.iter_rows(min_row=2, values_only=True))
                batch = []
                processadas = 0
                for row in rows:
                    if not row or all(v is None or str(v).strip() == "" for v in row.values()):
                        continue
                    dbrow = _row_to_db(row, source)
                    if dbrow["cod_cliente"] <= 0 or dbrow["cod_produto"] <= 0 or not dbrow["data_venda"]:
                        continue
                    batch.append(dbrow)
                    if len(batch) >= 1000:
                        await _crm_send_batch_with_retry(batch, importacao_id)
                        processadas += len(batch)
                        await _edge("CRM_IMPORT_ATUALIZAR", {"importacao_id": importacao_id, "processadas": processadas, "total_linhas": total_linhas})
                        batch = []
                if batch:
                    await _crm_send_batch_with_retry(batch, importacao_id)
                    processadas += len(batch)
                    await _edge("CRM_IMPORT_ATUALIZAR", {"importacao_id": importacao_id, "processadas": processadas, "total_linhas": total_linhas})
            finally:
                wb.close()
        await _edge("CRM_IMPORT_FINALIZAR", {"importacao_id": importacao_id, "sucesso": True})
    except Exception as exc:
        try:
            await _edge("CRM_IMPORT_FINALIZAR", {
                "importacao_id": importacao_id,
                "sucesso": False,
                "erro": str(exc)[:1000],
            })
        except Exception:
            pass
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


@router.post("/crm/api/importar/iniciar")
async def crm_importar_iniciar(
    request: Request,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _admin_danton(session)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Dados de início da importação inválidos.") from exc
    filename = str(body.get("nomeArquivo") or "base_crm.xlsx").strip()
    if not (filename.lower().endswith(".xlsx") or filename.lower().endswith(".csv")):
        raise HTTPException(400, "Formato não suportado. Envie XLSX ou CSV.")
    total_bytes = int(body.get("totalBytes") or 0)
    total_chunks = int(body.get("totalChunks") or 0)
    if total_bytes <= 0:
        raise HTTPException(400, "Arquivo vazio.")
    if total_bytes > CRM_MAX_UPLOAD:
        raise HTTPException(413, "Arquivo acima do limite de 35 MB.")
    if total_chunks <= 0 or total_chunks > 100:
        raise HTTPException(400, "Quantidade de partes inválida.")
    created = await _edge("CRM_IMPORT_CRIAR", {
        "nome_arquivo": filename,
        "total_linhas": 0,
        "usuario": str(profile.get("usuario") or "DANTON"),
    })
    importacao_id = str(created.get("id") or "")
    if not importacao_id:
        raise HTTPException(500, "O servidor não retornou o identificador da importação.")
    path = _crm_upload_path(importacao_id)
    path.write_bytes(b"")
    return _json({
        "sucesso": True,
        "importacaoId": importacao_id,
        "chunkSize": CRM_CHUNK_SIZE,
        "totalBytes": total_bytes,
        "totalChunks": total_chunks,
    }, status=201)


@router.post("/crm/api/importar/chunk")
async def crm_importar_chunk(
    request: Request,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_danton(session)
    importacao_id = (request.headers.get("x-importacao-id") or "").strip()
    if not importacao_id:
        raise HTTPException(400, "Identificador da importação ausente.")
    try:
        chunk_index = int(request.headers.get("x-chunk-index") or "-1")
        total_chunks = int(request.headers.get("x-total-chunks") or "0")
        total_bytes = int(request.headers.get("x-total-bytes") or "0")
    except ValueError as exc:
        raise HTTPException(400, "Metadados da parte inválidos.") from exc
    if chunk_index < 0 or total_chunks <= 0 or chunk_index >= total_chunks:
        raise HTTPException(400, "Índice da parte inválido.")
    if total_bytes <= 0 or total_bytes > CRM_MAX_UPLOAD:
        raise HTTPException(413, "Arquivo acima do limite permitido.")
    raw = await request.body()
    if not raw or len(raw) > CRM_CHUNK_SIZE:
        raise HTTPException(400, "Parte do arquivo inválida.")
    path = _crm_upload_path(importacao_id)
    mode = "r+b" if path.exists() else "wb"
    with path.open(mode) as fh:
        fh.seek(chunk_index * CRM_CHUNK_SIZE)
        fh.write(raw)
    return _json({
        "sucesso": True,
        "importacaoId": importacao_id,
        "chunk": chunk_index + 1,
        "totalChunks": total_chunks,
        "bytesRecebidos": len(raw),
    })


@router.post("/crm/api/importar/finalizar")
async def crm_importar_finalizar(
    request: Request,
    background_tasks: BackgroundTasks,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_danton(session)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Dados de finalização inválidos.") from exc
    importacao_id = str(body.get("importacaoId") or "").strip()
    filename = str(body.get("nomeArquivo") or "base_crm.xlsx").strip()
    total_bytes = int(body.get("totalBytes") or 0)
    if not importacao_id:
        raise HTTPException(400, "Identificador da importação ausente.")
    path = _crm_upload_path(importacao_id)
    if not path.exists():
        raise HTTPException(404, "Arquivo temporário da importação não encontrado.")
    if path.stat().st_size != total_bytes:
        raise HTTPException(400, f"Upload incompleto: {path.stat().st_size} de {total_bytes} bytes.")
    background_tasks.add_task(_crm_process_import_file, path, filename, importacao_id)
    return _json({
        "sucesso": True,
        "aceito": True,
        "importacaoId": importacao_id,
        "mensagem": "Upload concluído. O processamento da base foi iniciado.",
    }, status=202)


@router.get("/crm/api/import/status/{importacao_id}")
async def crm_import_status(
    importacao_id: str,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    _admin_danton(session)
    return _json(await _edge("CRM_IMPORT_STATUS", {"importacao_id": importacao_id}))
