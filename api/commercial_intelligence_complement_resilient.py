from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import get_settings


settings = get_settings()
_INSTALLED = False
_LOG = logging.getLogger("dismepe.commercial_intelligence.complement")
_MAX_UPLOAD_BYTES = 12 * 1024 * 1024


def _fast_pdf_parser(content: bytes) -> list[dict[str, Any]]:
    from . import commercial_intelligence_complement as cc
    from . import commercial_intelligence_complement_pdf as pdfmod

    # O container já possui poppler-utils. Para PDFs grandes, pdftotext é muito
    # mais rápido e previsível que percorrer centenas de páginas com pypdf.
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as temp:
            temp.write(content)
            temp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", temp.name, "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=50,
                check=False,
            )
        if proc.returncode == 0 and proc.stdout:
            text = proc.stdout.decode("utf-8", errors="ignore")
            rows: list[dict[str, Any]] = []
            for line in text.splitlines():
                parsed = pdfmod._parse_product_line(line)
                if parsed is not None:
                    rows.append(parsed)
            finalized = pdfmod._finalize(rows)
            # O relatório real tem milhares de itens. Evita aceitar uma leitura
            # parcial causada por layout inesperado.
            if len(finalized) >= 100:
                return finalized
    except Exception as exc:
        _LOG.warning("complement pdf fast parser fallback: %s", exc)

    # Fallback compatível com o parser já validado no PDF real.
    return pdfmod._parse_pdf(content)


def _compact_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        code = str(item.get("codigo") or "").strip()
        if not code:
            continue
        lots = item.get("lotes") if isinstance(item.get("lotes"), list) else []
        compact.append(
            {
                "codigo": code,
                "precoMedio": float(item.get("precoMedio") or 0),
                "lote": str(item.get("lote") or "").strip(),
                "vencimento": str(item.get("vencimento") or "").strip(),
                "quantidadeUltimaEntrada": float(item.get("quantidadeUltimaEntrada") or 0),
                "lotes": lots[:2],
            }
        )
    return compact


def install_commercial_intelligence_complement_resilient(app: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import commercial_intelligence_complement as cc

    original_parse_file = cc._parse_file

    def parse_file_resilient(file_name: str, content: bytes) -> list[dict[str, Any]]:
        if Path(file_name).suffix.lower() == ".pdf":
            return _fast_pdf_parser(content)
        return original_parse_file(file_name, content)

    cc._parse_file = parse_file_resilient

    @app.middleware("http")
    async def commercial_intelligence_complement_upload_guard(request: Request, call_next):
        if request.url.path != "/data/inteligencia-comercial/complemento/upload" or request.method.upper() != "POST":
            return await call_next(request)

        try:
            session = request.cookies.get(settings.cookie_name)
            owner = cc._owner(session)
            file_name = unquote(str(request.headers.get("x-file-name") or "").strip())
            if not file_name:
                return JSONResponse({"detail": "Nome do arquivo não informado."}, status_code=400)

            content = await request.body()
            if not content:
                return JSONResponse({"detail": "Arquivo vazio."}, status_code=400)
            if len(content) > _MAX_UPLOAD_BYTES:
                return JSONResponse({"detail": "O arquivo complementar deve ter no máximo 12 MB."}, status_code=413)

            _LOG.info(
                "complement upload received owner=%s file=%s bytes=%s",
                owner,
                file_name,
                len(content),
            )

            # Não bloqueia o event loop do único worker do Render.
            lines = await asyncio.to_thread(cc._parse_file, file_name, content)
            compact = _compact_lines(lines)
            if not compact:
                return JSONResponse({"detail": "Nenhum produto foi reconhecido no arquivo complementar."}, status_code=400)

            _LOG.info(
                "complement upload parsed owner=%s file=%s rows=%s",
                owner,
                file_name,
                len(compact),
            )

            stored = await cc._rpc(
                "UPSERT",
                owner,
                {
                    "fileName": file_name[:240],
                    "rowCount": len(compact),
                    "payload": {"linhas": compact},
                },
            )
            record = stored.get("complemento") if isinstance(stored.get("complemento"), dict) else {}

            _LOG.info(
                "complement upload stored owner=%s file=%s rows=%s",
                owner,
                file_name,
                len(compact),
            )

            return JSONResponse(
                {
                    "sucesso": True,
                    "arquivo": str(record.get("file_name") or file_name),
                    "enviadoEm": str(record.get("uploaded_at") or ""),
                    "codigos": len(compact),
                    "campos": ["Pc.Custo", "Lote", "Qtd", "Venc."],
                },
                headers={"Cache-Control": "no-store"},
            )
        except Exception as exc:
            status = int(getattr(exc, "status_code", 500) or 500)
            detail = str(getattr(exc, "detail", "") or "Falha ao processar o mapa complementar.")
            _LOG.exception("complement upload failed: %s", exc)
            return JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})
