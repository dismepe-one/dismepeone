from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jwt
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from .cache_reads import CacheReadError, cache_get as raw_cache_get
from .config import get_settings
from .herbamed_auto_metrics import enrich_herbamed_monthly_payload
from .monthly_business_days import enrich_monthly_payload
from .security import decode_session_token


settings = get_settings()
router = APIRouter()

HOME_PUBLICATION_MODULE = "HOME_PUBLICATION"
PERM_HOME_PUBLISH = "HOME_PUBLICAR_ATUALIZACAO"
PERM_LEGACY_CENTER = "CENTRO_ATUALIZACOES"
PERM_MONTHLY_UPDATE = "MENSAL_BASE_ATUALIZADA"
PERM_EXTRAS_UPDATE = "EXTRAS_BASE_ATUALIZADA"
BUILD = "PROD5.9.8.23"


class HomePublishRequest(BaseModel):
    atualizarHorario: bool = True
    inserirHistorico: bool = True


class HomeDecisionRequest(BaseModel):
    atualizarHorario: bool | None = None
    inserirHistorico: bool | None = None
    motivo: str = "CANCELADO"


def _now_recife() -> datetime:
    return datetime.now(ZoneInfo("America/Recife"))


def _format_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("America/Recife"))
        parsed = parsed.astimezone(ZoneInfo("America/Recife"))
        return parsed.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return text


def _profile(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=401, detail="Sessão ausente.")
    try:
        return decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida.") from exc


def _allowed(profile: dict[str, Any]) -> bool:
    role = str(profile.get("tipo") or "").strip().upper()
    if role in {"ADMINISTRADOR", "ADMIN"}:
        return True
    perms = profile.get("permissoes")
    perms = perms if isinstance(perms, dict) else {}
    return any(
        perms.get(key) is True
        for key in (
            PERM_HOME_PUBLISH,
            PERM_LEGACY_CENTER,
            PERM_MONTHLY_UPDATE,
            PERM_EXTRAS_UPDATE,
        )
    )


def _authorized(session: str | None) -> dict[str, Any]:
    profile = _profile(session)
    if not _allowed(profile):
        raise HTTPException(
            status_code=403,
            detail="Você não possui permissão para publicar novos números na HOME.",
        )
    return profile


async def _edge_call(
    action: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 35.0,
) -> dict[str, Any]:
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    body = {"acao": action, **payload}

    try:
        async with httpx.AsyncClient(timeout=max(timeout_seconds, settings.request_timeout_seconds)) as client:
            response = await client.post(endpoint, json=body, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise RuntimeError("O serviço de publicação não respondeu dentro do tempo esperado.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"O serviço de publicação respondeu em formato inválido (HTTP {response.status_code})."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(str(data.get("erro") or data.get("error") or f"HTTP {response.status_code}"))
    if data.get("sucesso") is not True and data.get("success") is not True and data.get("ok") is not True:
        raise RuntimeError(str(data.get("erro") or data.get("error") or "A operação não foi confirmada."))
    return data


async def _audit(
    profile: dict[str, Any],
    *,
    action: str,
    details: dict[str, Any],
    identifier: str = "",
) -> None:
    record = {
        "id": str(uuid.uuid4()),
        "data_hora": _now_recife().isoformat(),
        "epoch_ms": int(time.time() * 1000),
        "usuario": str(profile.get("usuario") or profile.get("sub") or ""),
        "nome": str(profile.get("nome") or profile.get("vendedor") or ""),
        "cargo": str(profile.get("tipo") or ""),
        "modulo": "HOME",
        "acao": action,
        "entidade": "HOME_PUBLICATION",
        "identificador": identifier,
        "detalhes": json.dumps(details, ensure_ascii=False, separators=(",", ":")),
        "origem": BUILD,
    }
    try:
        await _edge_call("LOG_ALTERACAO_ADD", {"registro": record}, timeout_seconds=15.0)
    except Exception:
        pass


async def _read_publication(
    *,
    cfg_settings=None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    cfg_settings = cfg_settings or settings
    try:
        payload, row = await raw_cache_get(
            modulo=HOME_PUBLICATION_MODULE,
            settings=cfg_settings,
        )
    except CacheReadError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    return payload, row


async def home_publication_cache_get(
    *,
    modulo: str,
    settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = str(modulo or "").strip().upper()
    if normalized not in {"MENSAL", "EXTRAS"}:
        return await raw_cache_get(modulo=normalized, settings=settings)

    publication, publication_row = await _read_publication(cfg_settings=settings)
    key = "mensal" if normalized == "MENSAL" else "extras"

    if not publication or not isinstance(publication.get(key), dict):
        return await raw_cache_get(modulo=normalized, settings=settings)

    payload = copy.deepcopy(publication[key])

    if normalized == "MENSAL":
        try:
            payload = await enrich_monthly_payload(payload)
        except Exception:
            pass

    row = dict(publication_row or {})
    display_times = publication.get("displayTimes")
    display_times = display_times if isinstance(display_times, dict) else {}
    time_info = display_times.get(key)
    time_info = time_info if isinstance(time_info, dict) else {}

    row.update({
        "modulo": normalized,
        "atualizado_em": str(time_info.get("iso") or row.get("atualizado_em") or ""),
        "atualizado_por": str(publication.get("publicadoPor") or row.get("atualizado_por") or ""),
        "nome": f"HOME {normalized}",
        "versao": f"{BUILD}_HOME_PUBLICATION",
    })
    return payload, row


async def _source_snapshot(module: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return await raw_cache_get(modulo=module, settings=settings)
    except CacheReadError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"A base {module} ainda não está disponível para publicação.",
        ) from exc


def _source_meta(row: dict[str, Any]) -> dict[str, Any]:
    raw = str(row.get("atualizado_em") or "")
    return {
        "atualizadoEm": raw,
        "atualizadoEmFormatado": _format_time(raw),
        "versao": str(row.get("versao") or ""),
        "atualizadoPor": str(row.get("atualizado_por") or ""),
    }


@router.get("/admin/home-publication/status")
async def home_publication_status(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _authorized(session)

    mensal_result, extras_result, publication_result = await asyncio.gather(
        _source_snapshot("MENSAL"),
        _source_snapshot("EXTRAS"),
        _read_publication(),
    )

    _, mensal_row = mensal_result
    _, extras_row = extras_result
    publication, publication_row = publication_result
    publication = publication or {}

    return {
        "sucesso": True,
        "podePublicar": True,
        "permissao": (
            "ADMIN"
            if str(profile.get("tipo") or "").strip().upper() in {"ADMINISTRADOR", "ADMIN"}
            else next(
                (
                    key
                    for key in (
                        PERM_HOME_PUBLISH,
                        PERM_LEGACY_CENTER,
                        PERM_MONTHLY_UPDATE,
                        PERM_EXTRAS_UPDATE,
                    )
                    if isinstance(profile.get("permissoes"), dict)
                    and profile["permissoes"].get(key) is True
                ),
                "",
            )
        ),
        "inicializada": bool(publication),
        "ultimaPublicacao": str(publication.get("publicadoEm") or ""),
        "ultimaPublicacaoFormatada": _format_time(publication.get("publicadoEm")),
        "publicadoPor": str(publication.get("publicadoPor") or ""),
        "displayTimes": publication.get("displayTimes") if isinstance(publication.get("displayTimes"), dict) else {},
        "historico": (
            publication.get("historico")[:3]
            if isinstance(publication.get("historico"), list)
            else []
        ),
        "fontes": {
            "mensal": _source_meta(mensal_row),
            "extras": _source_meta(extras_row),
        },
        "snapshotAtualizadoEm": str((publication_row or {}).get("atualizado_em") or ""),
    }


@router.post("/admin/home-publication/publish")
async def home_publication_publish(
    body: HomePublishRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _authorized(session)
    publication_id = str(uuid.uuid4())
    username = str(profile.get("usuario") or profile.get("sub") or "")
    now = _now_recife()
    now_iso = now.isoformat()
    now_display = now.strftime("%d/%m/%Y %H:%M:%S")

    try:
        (mensal_payload, mensal_row), (extras_payload, extras_row), current_result = await asyncio.gather(
            _source_snapshot("MENSAL"),
            _source_snapshot("EXTRAS"),
            _read_publication(),
        )
        current, _current_row = current_result
        current = current or {}

        mensal_publicado = copy.deepcopy(mensal_payload)
        try:
            mensal_publicado = await enrich_monthly_payload(mensal_publicado)
        except Exception:
            pass
        try:
            mensal_publicado = await enrich_herbamed_monthly_payload(mensal_publicado)
        except Exception:
            pass

        extras_publicado = copy.deepcopy(extras_payload)

        old_times = current.get("displayTimes")
        old_times = old_times if isinstance(old_times, dict) else {}

        if body.atualizarHorario:
            display_times = {
                "mensal": {"iso": now_iso, "display": now_display},
                "extras": {"iso": now_iso, "display": now_display},
            }
        else:
            mensal_old = old_times.get("mensal") if isinstance(old_times.get("mensal"), dict) else {}
            extras_old = old_times.get("extras") if isinstance(old_times.get("extras"), dict) else {}
            mensal_iso = str(mensal_old.get("iso") or mensal_row.get("atualizado_em") or "")
            extras_iso = str(extras_old.get("iso") or extras_row.get("atualizado_em") or "")
            display_times = {
                "mensal": {
                    "iso": mensal_iso,
                    "display": str(mensal_old.get("display") or _format_time(mensal_iso)),
                },
                "extras": {
                    "iso": extras_iso,
                    "display": str(extras_old.get("display") or _format_time(extras_iso)),
                },
            }

        history = current.get("historico")
        history = list(history) if isinstance(history, list) else []

        history_entry = {
            "id": publication_id,
            "publicadoEm": now_iso,
            "publicadoEmFormatado": now_display,
            "publicadoPor": username,
            "horarioHomeAlterado": bool(body.atualizarHorario),
            "fonteMensal": _source_meta(mensal_row),
            "fonteExtras": _source_meta(extras_row),
        }
        if body.inserirHistorico:
            history = [history_entry, *history][:3]
        else:
            history = history[:3]

        publication = {
            "schema": "HOME_PUBLICATION_V1",
            "publicationId": publication_id,
            "publicadoEm": now_iso,
            "publicadoPor": username,
            "atualizouHorario": bool(body.atualizarHorario),
            "inseriuHistorico": bool(body.inserirHistorico),
            "displayTimes": display_times,
            "fontes": {
                "mensal": _source_meta(mensal_row),
                "extras": _source_meta(extras_row),
            },
            "historico": history,
            "mensal": mensal_publicado,
            "extras": extras_publicado,
        }

        size = len(json.dumps(publication, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        await _edge_call(
            "CACHE_SET",
            {
                "modulo": HOME_PUBLICATION_MODULE,
                "payload": publication,
                "atualizado_por": username,
                "nome": "Fotografia publicada da HOME",
                "tamanho": size,
                "versao": f"{BUILD}_HOME_PUBLICATION_V1",
            },
            timeout_seconds=45.0,
        )

        await _audit(
            profile,
            action="PUBLICACAO_HOME_SUCESSO",
            identifier=publication_id,
            details={
                "atualizarHorario": bool(body.atualizarHorario),
                "inserirHistorico": bool(body.inserirHistorico),
                "fonteMensal": _source_meta(mensal_row),
                "fonteExtras": _source_meta(extras_row),
                "horariosExibidos": display_times,
                "resultado": "SUCESSO",
            },
        )

        return {
            "sucesso": True,
            "publicationId": publication_id,
            "publicadoEm": now_iso,
            "publicadoEmFormatado": now_display,
            "atualizouHorario": bool(body.atualizarHorario),
            "inseriuHistorico": bool(body.inserirHistorico),
            "displayTimes": display_times,
            "historico": history,
            "mensagem": "Novos números publicados na HOME.",
        }

    except HTTPException:
        raise
    except Exception as exc:
        await _audit(
            profile,
            action="PUBLICACAO_HOME_ERRO",
            identifier=publication_id,
            details={
                "atualizarHorario": bool(body.atualizarHorario),
                "inserirHistorico": bool(body.inserirHistorico),
                "resultado": "ERRO",
                "erro": str(exc)[:500],
            },
        )
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível publicar os números da HOME: {exc}",
        ) from exc


@router.post("/admin/home-publication/decision")
async def home_publication_decision(
    body: HomeDecisionRequest,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    profile = _authorized(session)
    await _audit(
        profile,
        action="PUBLICACAO_HOME_CANCELADA",
        details={
            "atualizarHorario": body.atualizarHorario,
            "inserirHistorico": body.inserirHistorico,
            "motivo": str(body.motivo or "CANCELADO")[:120],
            "resultado": "CANCELADO",
        },
    )
    return {"sucesso": True, "registradoNoLog": True}
