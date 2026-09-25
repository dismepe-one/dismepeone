from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jwt
from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException
from pydantic import BaseModel

from .cache_reads import CacheReadError, cache_get as raw_cache_get
from .config import get_settings
from .herbamed_auto_metrics import enrich_herbamed_monthly_payload
from .monthly_business_days import enrich_monthly_payload
from .security import decode_session_token
from .push_notifications import deliver_notice


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
    somenteExtras: bool = False
    notificarVendas: bool = False


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


def _partial_numbers(payload: dict[str, Any], key: str) -> list[str]:
    # A parcial é comparada pelos valores de venda e identificadores estáveis,
    # sem usar timestamps ou dias úteis que mudam sem novas vendas.
    fields = (
        "__COMPETENCIA", "competencia", "__COLABORADOR", "colab",
        "__LAB", "lab", "__CODIGO_FOCO", "produto",
        "__VENDA", "venda", "Venda", "Vendas", "Realizado",
        "__VENDA_FOCO", "vendaFoco",
    )
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return sorted(
        json.dumps(
            {field: row[field] for field in fields if field in row},
            ensure_ascii=False, sort_keys=True, default=str,
        )
        for row in rows if isinstance(row, dict)
    )


def _partial_sales_changed(previous: dict[str, Any], candidate: dict[str, Any]) -> bool:
    # Ambas as parciais precisam estar completas para publicar um novo horário.
    keys = ("dadosVendedores", "dadosTelevendas")
    if any(not _partial_numbers(candidate, key) for key in keys):
        raise RuntimeError(
            "As parciais de Vendedores e Televendas não estão completas; "
            "o horário da HOME foi preservado."
        )
    older = previous.get("mensal")
    if not isinstance(older, dict):
        return True
    return any(
        _partial_numbers(older, key) != _partial_numbers(candidate, key)
        for key in keys
    )


def _partial_signature(payload: dict[str, Any]) -> str:
    values = {
        key: _partial_numbers(payload, key)
        for key in ("dadosVendedores", "dadosTelevendas")
    }
    serialized = json.dumps(values, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _history_current_rows(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    channels: list[list[dict[str, Any]]] = []
    for key in ("dadosVendedores", "dadosTelevendas"):
        rows = payload.get(key)
        channels.append(
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list) else []
        )
    comps = {
        str(row.get("__COMPETENCIA") or row.get("competencia") or "").strip()
        for rows in channels for row in rows
    }
    valid = [
        value for value in comps
        if len(value) == 7 and value[2] == "/" and value[:2].isdigit()
        and value[3:].isdigit() and 1 <= int(value[:2]) <= 12
    ]
    if not valid:
        raise RuntimeError("Não foi possível identificar a competência das novas parciais.")
    comp = max(valid, key=lambda value: (int(value[3:]), int(value[:2])))
    selected = [
        [row for row in rows if str(row.get("__COMPETENCIA") or row.get("competencia") or "").strip() == comp]
        for rows in channels
    ]
    if not selected[0] or not selected[1]:
        raise RuntimeError("As novas parciais não contêm os dois canais da competência atual.")
    return comp, selected[0], selected[1]


def _history_sum(rows: list[dict[str, Any]], *fields: str) -> float:
    total = 0.0
    for row in rows:
        for field in fields:
            if row.get(field) is not None:
                try:
                    total += float(row[field])
                except (ValueError, TypeError):
                    pass
                break
    return round(total, 2)


def _history_date_recife(value: Any) -> str:
    """Dia calendario da fotografia no fuso da operacao, inclusive ISO com Z."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        recife = ZoneInfo("America/Recife")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=recife)
        return parsed.astimezone(recife).date().isoformat()
    except (ValueError, OverflowError):
        return ""


def _daily_history(items: list[dict[str, Any]], timestamp_key: str) -> list[dict[str, Any]]:
    """No maximo uma fotografia por dia (a mais recente), preservando dias anteriores."""
    dated = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = str(item.get(timestamp_key) or "")
        day = _history_date_recife(raw)
        if not day:
            continue
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=ZoneInfo("America/Recife"))
            epoch = moment.timestamp()
        except (ValueError, OverflowError):
            continue
        dated.append((epoch, day, item))
    dated.sort(key=lambda record: record[0], reverse=True)
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, day, item in dated:
        if day in seen:
            continue
        seen.add(day)
        chosen.append(item)
        if len(chosen) == 3:
            break
    return chosen


async def _ensure_monthly_publication_history(
    *,
    payload: dict[str, Any],
    profile: dict[str, Any],
    publication_id: str,
    now: datetime,
) -> None:
    # Preserva as fotografias anteriores: nunca troca seus valores pelos atuais.
    # Se a origem já criou a nova fotografia correta, não grava uma duplicata.
    comp, vend, tlv = _history_current_rows(payload)
    try:
        existing, _row = await raw_cache_get(modulo="HISTORICO_MENSAL", settings=settings)
    except CacheReadError as exc:
        raise RuntimeError("O histórico Mensal não está disponível; publicação interrompida.") from exc
    old_items = existing.get("atualizacoes")
    if not isinstance(old_items, list):
        raise RuntimeError("O histórico Mensal não possui uma lista válida de atualizações.")
    items = _daily_history(
        [entry for entry in old_items if isinstance(entry, dict)], "dataHoraISO"
    )
    current_rows = {"dadosVendedores": vend, "dadosTelevendas": tlv}
    # Uma publicacao adicional no mesmo dia nao regrava a fotografia salva.
    # A HOME ainda pode receber numeros novos, sem expulsar os dias anteriores.
    if any(
        _history_date_recife(entry.get("dataHoraISO")) == now.date().isoformat()
        for entry in items
    ):
        return
    # Uma fotografia com numeros identicos aos da ultima data nao deve
    # expulsar a anterior apenas porque o calendario mudou.
    latest = items[0] if items else {}
    if (
        str(latest.get("competencia") or "") == comp
        and _partial_signature({
            "dadosVendedores": latest.get("dadosVendedores"),
            "dadosTelevendas": latest.get("dadosTelevendas"),
        }) == _partial_signature(current_rows)
    ):
        return

    entry = {
        "idAtualizacao": publication_id,
        "competencia": comp,
        "origem": "CAMPANHAS MENSAIS",
        "dataHoraISO": now.isoformat(),
        "dataHoraFormatado": now.strftime("%d/%m/%Y %H:%M:%S"),
        "usuario": str(profile.get("usuario") or profile.get("sub") or ""),
        "registrosVendedores": len(vend),
        "registrosTelevendas": len(tlv),
        "objetivoVendedores": _history_sum(vend, "__OBJETIVO", "objetivo", "Objetivo", "Meta"),
        "vendaVendedores": _history_sum(vend, "__VENDA", "venda", "Venda", "Vendas"),
        "objetivoTelevendas": _history_sum(tlv, "__OBJETIVO", "objetivo", "Objetivo", "Meta"),
        "vendaTelevendas": _history_sum(tlv, "__VENDA", "venda", "Venda", "Vendas"),
        "dadosVendedores": vend,
        "dadosTelevendas": tlv,
        "regrasPremiacao": [
            row for row in payload.get("regrasPremiacao", [])
            if isinstance(row, dict)
            and str(row.get("competencia") or row.get("COMPETENCIA") or comp).strip() == comp
        ] if isinstance(payload.get("regrasPremiacao"), list) else [],
    }
    updated = dict(existing)
    updated["atualizacoes"] = _daily_history([entry, *items], "dataHoraISO")
    size = len(json.dumps(updated, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    await _edge_call(
        "CACHE_SET",
        {
            "modulo": "HISTORICO_MENSAL",
            "payload": updated,
            "atualizado_por": entry["usuario"],
            "nome": "Histórico Mensal após publicação das parciais",
            "tamanho": size,
            "versao": f"{BUILD}_HISTORY_PUBLICATION_V1",
        },
        timeout_seconds=65.0,
    )
    stored, _stored_row = await raw_cache_get(modulo="HISTORICO_MENSAL", settings=settings)
    verified = stored.get("atualizacoes")
    if (
        not isinstance(verified, list)
        or not verified
        or verified[0].get("idAtualizacao") != publication_id
        or _partial_signature(verified[0]) != _partial_signature(current_rows)
    ):
        raise RuntimeError("O PostgreSQL não confirmou a nova fotografia do histórico Mensal.")


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

    mensal_payload, mensal_row = mensal_result
    extras_payload, extras_row = extras_result
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
        "historico": _daily_history(
            publication.get("historico")
            if isinstance(publication.get("historico"), list) else [],
            "publicadoEm",
        ),
        "fontes": {
            "mensal": _source_meta(mensal_row),
            "extras": _source_meta(extras_row),
        },
        "extrasPublicacaoPendente": any(
            extras_payload.get(key) != (
                publication.get("extras", {}).get(key)
                if isinstance(publication.get("extras"), dict) else None
            )
            for key in ("campanhas", "vendasPorCampanha")
        ),
        "parciais": {
            "fonteAssinatura": _partial_signature(mensal_payload),
            "publicadaAssinatura": (
                _partial_signature(publication["mensal"])
                if isinstance(publication.get("mensal"), dict) else ""
            ),
        },
        "snapshotAtualizadoEm": str((publication_row or {}).get("atualizado_em") or ""),
    }


@router.get("/admin/home-publication/monthly-status")
async def home_publication_monthly_status(
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    """Consulta leve e autenticada: sem Extras, histórico ou cálculo legado.

    O front usa o carimbo persistido do MENSAL para identificar também
    cálculos concluídos sem alteração de vendas. Não inicia novo worker.
    """
    _authorized(session)
    (monthly, monthly_row), (publication, _publication_row) = await asyncio.gather(
        _source_snapshot("MENSAL"),
        _read_publication(),
    )
    publication = publication or {}
    published_monthly = publication.get("mensal")
    published_monthly = published_monthly if isinstance(published_monthly, dict) else {}
    published_sources = publication.get("fontes")
    published_sources = published_sources if isinstance(published_sources, dict) else {}
    published_source = published_sources.get("mensal")
    published_source = published_source if isinstance(published_source, dict) else {}
    source_ok = all(
        isinstance(monthly.get(key), list) and bool(monthly[key])
        for key in ("dadosVendedores", "dadosTelevendas")
    )
    return {
        "sucesso": True,
        "fonteValida": source_ok,
        "fonteAtualizadoEm": str(monthly_row.get("atualizado_em") or ""),
        "fontePublicadaEm": str(published_source.get("atualizadoEm") or ""),
        "fonteAssinatura": _partial_signature(monthly) if source_ok else "",
        "publicadaAssinatura": (
            _partial_signature(published_monthly)
            if all(isinstance(published_monthly.get(key), list) and published_monthly[key]
                   for key in ("dadosVendedores", "dadosTelevendas"))
            else ""
        ),
    }


_MONTHLY_PUBLISH_LOCK = asyncio.Lock()


@router.post("/admin/home-publication/publish")
async def home_publication_publish(
    body: HomePublishRequest,
    background_tasks: BackgroundTasks,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    async with _MONTHLY_PUBLISH_LOCK:
        return await _home_publication_publish_locked(body, background_tasks, session)


async def _home_publication_publish_locked(
    body: HomePublishRequest, background_tasks: BackgroundTasks, session: str | None,
):
    profile = _authorized(session)
    if body.notificarVendas and (not body.inserirHistorico or body.somenteExtras):
        raise HTTPException(
            status_code=422,
            detail="Para notificar Vendedores e Televendas, selecione salvar historico e publicar a base Mensal.",
        )
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

        if body.somenteExtras:
            if not isinstance(current.get("mensal"), dict):
                raise RuntimeError("A parcial Mensal ainda não foi publicada.")
            mensal_publicado = copy.deepcopy(current["mensal"])
            partials_changed = False
        else:
            mensal_publicado = copy.deepcopy(mensal_payload)
            try:
                mensal_publicado = await enrich_monthly_payload(mensal_publicado)
            except Exception:
                pass
            try:
                mensal_publicado = await enrich_herbamed_monthly_payload(mensal_publicado)
            except Exception:
                pass
            partials_changed = _partial_sales_changed(current, mensal_publicado)

        extras_publicado = copy.deepcopy(extras_payload)
        previous_sources = current.get("fontes") if isinstance(current.get("fontes"), dict) else {}
        monthly_source_meta = (
            previous_sources.get("mensal")
            if body.somenteExtras and isinstance(previous_sources.get("mensal"), dict)
            else _source_meta(mensal_row)
        )
        extras_old_payload = current.get("extras") if isinstance(current.get("extras"), dict) else {}
        extras_changed = any(
            extras_publicado.get(key) != extras_old_payload.get(key)
            for key in ("campanhas", "vendasPorCampanha")
        )

        old_times = current.get("displayTimes")
        old_times = old_times if isinstance(old_times, dict) else {}

        # O horário é consequência da publicação de novas parciais,
        # jamais da solicitação de atualização ou de uma opção independente.
        mensal_old = old_times.get("mensal") if isinstance(old_times.get("mensal"), dict) else {}
        extras_old = old_times.get("extras") if isinstance(old_times.get("extras"), dict) else {}
        mensal_iso = str(mensal_old.get("iso") or mensal_row.get("atualizado_em") or "")
        extras_iso = str(extras_old.get("iso") or extras_row.get("atualizado_em") or "")
        # Publicar a parcial Mensal não altera o horário próprio de Extras.
        display_times = {
            "mensal": {
                "iso": now_iso if partials_changed else mensal_iso,
                "display": now_display if partials_changed else str(
                    mensal_old.get("display") or _format_time(mensal_iso)
                ),
            },
            "extras": {
                "iso": now_iso if extras_changed else extras_iso,
                "display": now_display if extras_changed else str(
                    extras_old.get("display") or _format_time(extras_iso)
                ),
            },
        }

        history = current.get("historico")
        history = _daily_history(
            list(history) if isinstance(history, list) else [], "publicadoEm"
        )

        history_entry = {
            "id": publication_id,
            "publicadoEm": now_iso,
            "publicadoEmFormatado": now_display,
            "publicadoPor": username,
            "horarioHomeAlterado": partials_changed,
            "fonteMensal": monthly_source_meta,
            "fonteExtras": _source_meta(extras_row),
        }
        if body.inserirHistorico and partials_changed:
            # O histórico Mensal é a fonte da lista de três atualizações.
            # Ao publicar 22/09, preserva 21/09 e 18/09 sem reusar 17/09.
            await _ensure_monthly_publication_history(
                payload=mensal_publicado,
                profile=profile,
                publication_id=publication_id,
                now=now,
            )
            if not any(
                _history_date_recife(item.get("publicadoEm")) == now.date().isoformat()
                for item in history
            ):
                history = _daily_history([history_entry, *history], "publicadoEm")

        publication = {
            "schema": "HOME_PUBLICATION_V1",
            "publicationId": publication_id,
            "publicadoEm": now_iso,
            "publicadoPor": username,
            "atualizouHorario": partials_changed,
            "atualizouHorarioExtras": extras_changed,
            "inseriuHistorico": bool(body.inserirHistorico),
            "displayTimes": display_times,
            "fontes": {
                "mensal": monthly_source_meta,
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

        # Um retorno de sucesso do gateway não prova que os valores chegaram à HOME.
        confirmed, _confirmed_row = await _read_publication()
        if (
            not confirmed
            or confirmed.get("publicationId") != publication_id
            or confirmed.get("displayTimes") != display_times
            or any(
                _partial_numbers(confirmed.get("mensal") or {}, key)
                != _partial_numbers(mensal_publicado, key)
                for key in ("dadosVendedores", "dadosTelevendas")
            )
        ):
            raise RuntimeError(
                "O PostgreSQL não confirmou as parciais publicadas; "
                "o horário da HOME não pode ser confirmado."
            )

        # Somente depois da confirmacao dos numeros e do historico persistidos.
        # A notificacao e opt-in, limitada a VENDEDOR e TELEVENDAS; extras e
        # publicacoes sem mudanca nao criam avisos.
        notice_requested = bool(
            body.notificarVendas and body.inserirHistorico
            and partials_changed and not body.somenteExtras
        )
        notice_id = ""
        notice_error = ""
        if notice_requested:
            notice_id = "ONE-PUSH-" + uuid.UUID(publication_id).hex
            notice = {
                "id": notice_id, "tipo": "AVISO", "status": "ATIVO",
                "titulo": "Campanha Mensal atualizada",
                "mensagem": (
                    "Novos numeros de Vendedores e Televendas foram publicados "
                    "na HOME. Consulte sua parcial atualizada."
                ),
                "publico": {
                    "todos": False, "perfis": ["VENDEDOR", "TELEVENDAS"],
                    "setores": [], "usuarios": [],
                },
                "criadoEpoch": int(now.timestamp() * 1000),
                "criadoEm": now.strftime("%d/%m/%Y %H:%M"),
                "criadoPor": username, "publicarEm": now_iso, "expiraEm": "",
                "importante": False, "exibirUmaVez": False,
                "destino": {"modulo": "HOME", "tela": "INICIO", "fornecedor": ""},
                "pushStatus": "AGENDADO",
                "origem": "HOME_PUBLICATION_MENSAL",
                "publicationId": publication_id,
            }
            try:
                registered = await _edge_call(
                    "NOTIFICACAO_UPSERT", {"notificacao": notice},
                    timeout_seconds=20.0,
                )
                if str(registered.get("id") or "") != notice_id:
                    raise RuntimeError("O banco nao confirmou o aviso da Campanha Mensal.")
                background_tasks.add_task(deliver_notice, notice_id)
            except Exception:
                notice_error = (
                    "A campanha e o historico foram publicados, mas nao foi "
                    "possivel confirmar o envio do aviso automatico."
                )
                notice_id = ""
            await _audit(
                profile,
                action=("NOTIFICACAO_MENSAL_REGISTRADA" if notice_id
                        else "NOTIFICACAO_MENSAL_FALHOU"),
                identifier=publication_id,
                details={"notificacaoId": notice_id, "enviadaPara": [
                    "VENDEDOR", "TELEVENDAS"], "resultado": (
                    "AVISO_REGISTRADO" if notice_id else "AVISO_NAO_CONFIRMADO")},
            )

        await _audit(
            profile,
            action="PUBLICACAO_HOME_SUCESSO",
            identifier=publication_id,
            details={
                "atualizarHorario": partials_changed,
                "inserirHistorico": bool(body.inserirHistorico),
                "fonteMensal": monthly_source_meta,
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
            "atualizouHorario": partials_changed,
            "atualizouHorarioExtras": extras_changed,
            "inseriuHistorico": bool(body.inserirHistorico),
            "displayTimes": display_times,
            "historico": history,
            "notificacaoSolicitada": notice_requested,
            "notificacaoRegistrada": bool(notice_id),
            "notificacaoId": notice_id,
            "avisoNotificacao": notice_error,
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
