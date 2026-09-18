from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import jwt
from fastapi import Cookie, HTTPException, Request, Response

from . import main as main_module
from . import prod4_app as prod4
from .cache_reads import CacheReadError, cache_get
from .industries_app import app, settings
from .legacy_bridge import clear_state, get_state
from .security import decode_session_token
from .update_center import (
    APPS_SCRIPT_UPDATE_CENTER_URL,
    UpdateCenterBridgeError,
    call_update_center_legacy,
)
from .home_publication import router as home_publication_router
from .stock_schedule_admin import router as stock_schedule_router


BUILD = "2.0.0-phase2i2-prod5.9.7.3-legacy-cookie"
ROOT = Path(__file__).resolve().parents[1]
BASE_PATCH_FILE = ROOT / "frontend" / "update-center-prod4.js"
MONTHLY_PATCH_FILE = ROOT / "frontend" / "monthly-sync-prod597.js"
HOME_PUBLICATION_PATCH_FILE = ROOT / "frontend" / "home-publication-prod59823.js"
STOCK_SCHEDULE_PATCH_FILE = ROOT / "frontend" / "stock-schedule-prod59823.js"

app.include_router(home_publication_router)
app.include_router(stock_schedule_router)

LEGACY_COOKIE_PREFIX = "dismepe_legacy_"
LEGACY_COOKIE_MAX_AGE = 3 * 60 * 60


def _legacy_cookie_name(session: str) -> str:
    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:24]
    return f"{LEGACY_COOKIE_PREFIX}{digest}"


def _legacy_cookie_value(request: Request, session: str) -> str:
    return str(request.cookies.get(_legacy_cookie_name(session)) or "").strip()


def _store_legacy_cookie(response: Response, session: str, token: str) -> None:
    value = str(token or "").strip()
    if not value:
        return
    response.set_cookie(
        key=_legacy_cookie_name(session),
        value=value,
        max_age=LEGACY_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


def _delete_legacy_cookie(response: Response, session: str) -> None:
    response.delete_cookie(
        key=_legacy_cookie_name(session),
        domain=settings.cookie_domain,
        path="/",
    )


def _remove_routes(*paths: str) -> None:
    wanted = set(paths)
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", None) not in wanted
    ]


def _successful(result: dict) -> bool:
    return isinstance(result, dict) and (
        result.get("sucesso") is True
        or result.get("ok") is True
        or result.get("success") is True
    )


def _requested_modules(payload: dict) -> set[str]:
    rows = payload.get("acoes") if isinstance(payload.get("acoes"), list) else []
    names: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("modulo") or "").strip().upper()
        if name:
            names.add(name)
    return names


def _monthly_requested(payload: dict) -> bool:
    rows = payload.get("acoes") if isinstance(payload.get("acoes"), list) else []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("modulo") or "").strip().upper() != "MENSAL":
            continue
        # O formato atual envia atualizar=true. A ausência da chave continua
        # significando solicitação do módulo, preservando compatibilidade.
        return item.get("atualizar") is not False
    return False


async def _legacy_token(
    *,
    session_key: str,
    payload: dict,
    persisted_token: str,
    wait_for_ready: bool,
) -> str:
    state = await get_state(session_key)
    token = (
        str(state.get("token") or "").strip()
        if state.get("status") == "READY"
        else ""
    )
    if not token:
        token = str(persisted_token or "").strip()
    if not token:
        token = str(payload.get("token") or "").strip()

    # A Central chama OPCACHE_STATUS antes de atualizar qualquer módulo.
    # O login legado é iniciado em background; quando ainda não há token,
    # aguardamos também essa primeira consulta sair de PENDING.
    if token or not wait_for_ready:
        return token

    for _ in range(40):  # até 20s, sem repetir qualquer escrita
        await asyncio.sleep(0.5)
        state = await get_state(session_key)
        if state.get("status") == "READY":
            token = str(state.get("token") or "").strip()
            if token:
                return token
        if state.get("status") == "ERROR":
            break

    return ""


async def _persisted_monthly_time() -> tuple[str, str]:
    try:
        _payload, row = await cache_get(modulo="MENSAL", settings=settings)
    except (CacheReadError, RuntimeError):
        return "", ""

    raw = str(row.get("atualizado_em") or "").strip()
    if not raw:
        return "", ""
    return main_module._format_snapshot_time(raw), raw


# A aplicação final já foi montada por industries_app. Substituímos somente a
# rota da Central e o arquivo JS que a acompanha; todo o restante permanece
# exatamente como PROD5.9.6/Indústrias.
_remove_routes("/admin/update-center", "/update-center-prod4.js", "/auth/legacy-status", "/auth/logout")


@app.get("/auth/legacy-status")
async def prod597_legacy_status(
    request: Request,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    if not session:
        raise HTTPException(status_code=401, detail="Sessão 2.0 ausente.")

    try:
        decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessão 2.0 expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão 2.0 inválida.") from exc

    session_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
    state = await get_state(session_key)

    state_status = str(state.get("status") or "MISSING").strip().upper()
    state_token = (
        str(state.get("token") or "").strip()
        if state_status == "READY"
        else ""
    )

    if state_token:
        _store_legacy_cookie(response, session, state_token)
        return {
            "status": "READY",
            "token": state_token,
            "error": "",
            "fonte": "MEMORIA_E_COOKIE_HTTPONLY",
        }

    if state_status == "MISSING":
        persisted = _legacy_cookie_value(request, session)
        if persisted:
            return {
                "status": "READY",
                "token": persisted,
                "error": "",
                "fonte": "COOKIE_HTTPONLY",
            }

    return {
        "status": state_status or "MISSING",
        "token": "",
        "error": (
            str(state.get("error") or "")
            if state_status == "ERROR"
            else ""
        ),
    }


@app.post("/auth/logout")
async def prod597_logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    if session:
        try:
            session_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
            await clear_state(session_key)
        except Exception:
            pass
        _delete_legacy_cookie(response, session)

    response.delete_cookie(
        key=settings.cookie_name,
        domain=settings.cookie_domain,
        path="/",
    )
    return {"sucesso": True}


@app.get("/data/audit-log")
async def prod5989_audit_log(
    request: Request,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    if not session:
        raise HTTPException(status_code=401, detail="Sessao 2.0 ausente.")

    try:
        profile = decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessao 2.0 expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessao 2.0 invalida.") from exc

    role = str(profile.get("tipo") or "").strip().upper()
    perms = profile.get("permissoes")
    perms = perms if isinstance(perms, dict) else {}
    if role not in {"ADMINISTRADOR", "ADMIN"} and perms.get("LOG_ALTERACOES_VISUALIZAR") is not True:
        raise HTTPException(
            status_code=403,
            detail="Voce nao possui permissao para visualizar o Log de Alteracoes.",
        )

    endpoint = (
        settings.supabase_url.rstrip("/")
        + "/functions/v1/dismepe-admin"
    )
    body = {
        "acao": "LOG_ALTERACOES_LIST",
        "limite": 300,
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        ) as client:
            upstream = await client.post(
                endpoint,
                json=body,
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "x-dismepe-token": settings.edge_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(
            status_code=504,
            detail="O Log de Alteracoes nao respondeu em ate 20 segundos.",
        ) from exc

    try:
        data = upstream.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "O servidor do Log de Alteracoes respondeu em formato invalido "
                f"(HTTP {upstream.status_code})."
            ),
        ) from exc

    if upstream.status_code < 200 or upstream.status_code >= 300:
        message = (
            data.get("erro")
            or data.get("error")
            or data.get("mensagem")
            or f"HTTP {upstream.status_code}"
        )
        raise HTTPException(status_code=502, detail=str(message))

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail="Resposta invalida do Log de Alteracoes.",
        )

    if data.get("sucesso") is False:
        message = (
            data.get("erro")
            or data.get("error")
            or data.get("mensagem")
            or "Nao foi possivel carregar o Log de Alteracoes."
        )
        raise HTTPException(status_code=502, detail=str(message))

    data["transporte"] = "FASTAPI_AUDIT_SQL_DIRECT"
    data["limiteAplicado"] = 300
    return data


@app.get("/update-center-prod4.js", include_in_schema=False)
async def prod597_update_center_script():
    content = (
        BASE_PATCH_FILE.read_text(encoding="utf-8")
        + "\n\n"
        + MONTHLY_PATCH_FILE.read_text(encoding="utf-8")
        + "\n\n"
        + HOME_PUBLICATION_PATCH_FILE.read_text(encoding="utf-8")
        + "\n\n"
        + STOCK_SCHEDULE_PATCH_FILE.read_text(encoding="utf-8")
    )
    return Response(
        content=content,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-DISMEPE-Mensal-Fix": BUILD,
        },
    )


@app.post("/admin/update-center")
async def prod597_update_center(
    request: Request,
    response: Response,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    if not session:
        raise HTTPException(status_code=401, detail="Sessão 2.0 ausente.")

    try:
        profile = decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessão 2.0 expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão 2.0 inválida.") from exc

    if not prod4._allowed(profile):
        raise HTTPException(
            status_code=403,
            detail="Você não possui permissão para usar o Centro de Atualizações.",
        )

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Requisição inválida.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Requisição inválida.")

    action = str(payload.get("acao") or payload.get("action") or "").strip().upper()
    if action not in {"OPCACHE_STATUS", "OPCACHE_ATUALIZAR"}:
        raise HTTPException(status_code=400, detail="Ação inválida para o Centro de Atualizações.")

    mensal_requested = action == "OPCACHE_ATUALIZAR" and _monthly_requested(payload)
    session_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
    legacy_token = await _legacy_token(
        session_key=session_key,
        payload=payload,
        persisted_token=_legacy_cookie_value(request, session),
        wait_for_ready=True,
    )

    if legacy_token:
        _store_legacy_cookie(response, session, legacy_token)

    if not legacy_token:
        raise HTTPException(
            status_code=409,
            detail="A sessão de compatibilidade ainda está sendo preparada. Aguarde alguns segundos e tente novamente.",
        )

    try:
        result = await call_update_center_legacy(
            action=action,
            payload=payload,
            legacy_token=legacy_token,
        )
    except UpdateCenterBridgeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if action == "OPCACHE_ATUALIZAR" and _successful(result):
        names = _requested_modules(payload)
        immediate_times = {
            name: prod4._time_from_result(result, name)
            for name in names
        }

        # Mantém literalmente o comportamento PROD5.9.6 para todos os módulos
        # que não sejam MENSAL (inclusive EXTRAS).
        completed_display, completed_iso = prod4._update_center_now()
        requested_times = {
            name: immediate_times.get(name) or completed_display
            for name in names
            if name != "MENSAL"
        }

        try:
            status = await call_update_center_legacy(
                action="OPCACHE_STATUS",
                payload={"acao": "OPCACHE_STATUS"},
                legacy_token=legacy_token,
            )
            modules = status.get("modulos") if isinstance(status.get("modulos"), list) else []
            if modules:
                result["modulos"] = modules
        except UpdateCenterBridgeError:
            pass

        # MENSAL: a única fonte de verdade de conclusão passa a ser o
        # atualizado_em realmente persistido no PostgreSQL. Nunca usamos o
        # horário do clique nem um fallback visual para este módulo.
        if "MENSAL" in names:
            mensal_display, mensal_iso = await _persisted_monthly_time()
            if mensal_display:
                requested_times["MENSAL"] = mensal_display
                result["horarioMensal"] = mensal_display
                result["horarioMensalISO"] = mensal_iso
                result["mensalSnapshotFonte"] = "POSTGRESQL"
            else:
                result.pop("horarioMensal", None)
                result.pop("horarioMensalISO", None)

        prod4._stamp_requested_modules(result, requested_times)

        if "EXTRAS" in names:
            result["horarioExtras"] = requested_times["EXTRAS"]
            if not immediate_times.get("EXTRAS"):
                result["horarioExtrasISO"] = completed_iso

    result["transporte"] = "FASTAPI_UPDATE_CENTER_DIRECT"
    if mensal_requested:
        result["mensalSync"] = "POSTGRESQL_ATUALIZADO_EM"
    return result
