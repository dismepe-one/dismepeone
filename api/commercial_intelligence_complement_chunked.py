from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import Cookie, HTTPException, Request

from .config import get_settings


settings = get_settings()
_INSTALLED = False
_ROOT = Path('/tmp/dismepe_ci_complement_uploads')
_CHUNK_MAX = 1024 * 1024
_TOTAL_MAX = 12 * 1024 * 1024
_MAX_CHUNKS = 32


def _safe_upload_id(value: str) -> str:
    raw = str(value or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,96}', raw):
        raise HTTPException(status_code=400, detail='Identificador de upload inválido.')
    return raw


def _upload_dir(owner: str, upload_id: str) -> Path:
    owner_hash = hashlib.sha256(owner.encode('utf-8')).hexdigest()[:16]
    return _ROOT / f'{owner_hash}-{upload_id}'


def _cleanup_old() -> None:
    try:
        _ROOT.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 3600
        for child in _ROOT.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except Exception:
                continue
    except Exception:
        pass


def install_commercial_intelligence_complement_chunked(app: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import commercial_intelligence_complement as cc

    async def upload_chunk(
        request: Request,
        session: str | None = Cookie(default=None, alias=settings.cookie_name),
    ):
        owner = cc._owner(session)
        upload_id = _safe_upload_id(request.headers.get('x-upload-id') or '')
        try:
            index = int(request.headers.get('x-chunk-index') or '-1')
            total = int(request.headers.get('x-chunk-total') or '0')
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='Informações dos blocos inválidas.') from exc
        if total < 1 or total > _MAX_CHUNKS or index < 0 or index >= total:
            raise HTTPException(status_code=400, detail='Sequência de blocos inválida.')

        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail='Bloco vazio.')
        if len(body) > _CHUNK_MAX + 65536:
            raise HTTPException(status_code=413, detail='Bloco maior que o limite permitido.')

        _cleanup_old()
        folder = _upload_dir(owner, upload_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{index:04d}.part').write_bytes(body)
        (folder / 'total.txt').write_text(str(total), encoding='utf-8')
        return {'sucesso': True, 'indice': index, 'total': total}

    async def finalize_upload(
        request: Request,
        session: str | None = Cookie(default=None, alias=settings.cookie_name),
    ):
        owner = cc._owner(session)
        upload_id = _safe_upload_id(request.headers.get('x-upload-id') or '')
        file_name = unquote(str(request.headers.get('x-file-name') or '').strip())
        if not file_name:
            raise HTTPException(status_code=400, detail='Nome do arquivo não informado.')

        folder = _upload_dir(owner, upload_id)
        if not folder.exists():
            raise HTTPException(status_code=404, detail='Upload temporário não encontrado. Envie o arquivo novamente.')
        try:
            total = int((folder / 'total.txt').read_text(encoding='utf-8').strip())
        except Exception as exc:
            raise HTTPException(status_code=400, detail='Upload incompleto.') from exc

        parts: list[bytes] = []
        total_bytes = 0
        try:
            for index in range(total):
                part = folder / f'{index:04d}.part'
                if not part.exists():
                    raise HTTPException(status_code=409, detail=f'Falta o bloco {index + 1} de {total}.')
                data = part.read_bytes()
                total_bytes += len(data)
                if total_bytes > _TOTAL_MAX:
                    raise HTTPException(status_code=413, detail='O arquivo complementar deve ter no máximo 12 MB.')
                parts.append(data)
            content = b''.join(parts)

            # PDF é CPU-bound; processa fora do event loop para não travar health/portal.
            lines = await asyncio.to_thread(cc._parse_file, file_name, content)
            if not lines:
                raise HTTPException(status_code=400, detail='Nenhum produto foi reconhecido no arquivo complementar.')

            # Mantém somente os campos necessários, reduzindo o payload persistido.
            compact: list[dict[str, Any]] = []
            for item in lines:
                if not isinstance(item, dict):
                    continue
                compact.append({
                    'codigo': str(item.get('codigo') or '').strip(),
                    'precoMedio': float(item.get('precoMedio') or 0),
                    'lote': str(item.get('lote') or '').strip(),
                    'vencimento': str(item.get('vencimento') or '').strip(),
                    'quantidadeUltimaEntrada': float(item.get('quantidadeUltimaEntrada') or 0),
                    'lotes': (item.get('lotes') if isinstance(item.get('lotes'), list) else [])[:3],
                })

            stored = await cc._rpc('UPSERT', owner, {
                'fileName': file_name[:240],
                'rowCount': len(compact),
                'payload': {'linhas': compact},
            })
            record = stored.get('complemento') if isinstance(stored.get('complemento'), dict) else {}
            return {
                'sucesso': True,
                'arquivo': str(record.get('file_name') or file_name),
                'enviadoEm': str(record.get('uploaded_at') or ''),
                'codigos': len(compact),
                'campos': ['Pc.Custo', 'Lote', 'Qtd', 'Venc.'],
            }
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    app.add_api_route('/data/inteligencia-comercial/complemento/upload-chunk', upload_chunk, methods=['POST'])
    app.add_api_route('/data/inteligencia-comercial/complemento/upload-finalize', finalize_upload, methods=['POST'])
