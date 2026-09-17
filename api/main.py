from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import time
import uuid

import jwt
from fastapi import BackgroundTasks, Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

from .config import get_settings
from .models import LoginRequest, LoginResponse, MeResponse, UserProfile
from .security import decode_session_token, issue_session_token
from .supabase_edge import InvalidCredentials, UpstreamUnavailable, login_via_edge
from .legacy_bridge import clear_state, get_state, mark_pending, run_legacy_login
from .cache_reads import CacheReadError, cache_get, scope_clientes_ped, scope_resumo_ganhos, scope_mensal_dashboard
from .extras_reads import extras_api_response
from .access_reads import AccessReadError, access_user, list_accesses
from .history_reads import HistoryReadError, history_get, history_list
from .monthly_rule_reads import monthly_rule_options
from .home_publication import home_publication_cache_get


settings = get_settings()
logger = logging.getLogger("uvicorn.error")

PORTAL_FILE = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "portal-v2-homolog.html"
)

PHASE1_LOGIN_FILE = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "login-v2.html"
)

TEMPOS_FILE = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "tempos-v2.html"
)


# FASE 2G — o login já lê EXTRAS em paralelo.
# Reutilizamos essa fotografia para abrir Campanhas Extras sem uma nova ida à rede.
_EXTRAS_SNAPSHOT_CACHE: dict[str, tuple[float, dict, dict]] = {}
_EXTRAS_SNAPSHOT_TTL_SECONDS = 120.0

# FASE 2F — cache curto do Controle de Acessos.
_ACCESS_RESULT_CACHE: dict[str, tuple[float, dict]] = {}
_ACCESS_RESULT_TTL_SECONDS = 60.0

# FASE 2E.1 — cache curto somente da leitura/calculadora de Campanhas Extras.
# O snapshot do PostgreSQL continua sendo a fonte de verdade.
_EXTRAS_RESULT_CACHE: dict[str, tuple[float, dict]] = {}
_EXTRAS_RESULT_TTL_SECONDS = 60.0

app = FastAPI(
    title=settings.app_name,
    version="2.0.0-phase2i2-prod3",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()

    response = await call_next(request)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    if request.url.path == "/data/bootstrap":
        logger.info(
            "[2H4 OBS] bootstrap_http request_id=%s status=%s elapsed_ms=%s competencia=%s",
            request_id,
            response.status_code,
            elapsed_ms,
            request.query_params.get("competencia") or "ATUAL",
        )
    return response


def _html_no_cache(file_path: Path) -> FileResponse:
    return FileResponse(
        file_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-DISMEPE-Build": "2.0.0-phase2i2-prod3",
        },
    )


@app.get("/", include_in_schema=False)
async def portal_page():
    return _html_no_cache(PORTAL_FILE)


@app.get("/portal-v2-homolog.html", include_in_schema=False)
async def portal_page_alias():
    return _html_no_cache(PORTAL_FILE)


@app.get("/phase1-login.html", include_in_schema=False)
async def phase1_login_page():
    return _html_no_cache(PHASE1_LOGIN_FILE)


@app.get("/tempos-2-0", include_in_schema=False)
async def tempos_page():
    return _html_no_cache(TEMPOS_FILE)


@app.get("/health")
async def health(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["X-DISMEPE-Build"] = "2.0.0-phase2i2-prod3"
    missing = settings.validate_required_secrets()
    return {
        "ok": len(missing) == 0,
        "service": "dismepe-one-2-auth",
        "version": "2.0.0-phase2i2-prod3",
        "environment": settings.environment,
        "missingConfig": missing,
    }


@app.post("/auth/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    background_tasks: BackgroundTasks,
):
    missing = settings.validate_required_secrets()
    if missing:
        raise HTTPException(
            status_code=503,
            detail={
                "codigo": "AUTH_CONFIG_INCOMPLETE",
                "campos": missing,
            },
        )

    total_started = time.perf_counter()

    # FASE 2D
    # Autenticação e leitura das fotografias começam AO MESMO TEMPO.
    # O navegador recebe login + Home + Vendedores + Televendas + Visão Geral
    # em uma única resposta.
    auth_started = time.perf_counter()

    auth_task = asyncio.create_task(
        login_via_edge(
            usuario=payload.usuario,
            senha=payload.senha,
            settings=settings,
        )
    )
    mensal_task = asyncio.create_task(
        home_publication_cache_get(modulo="MENSAL", settings=settings)
    )
    extras_task = asyncio.create_task(
        home_publication_cache_get(modulo="EXTRAS", settings=settings)
    )

    try:
        profile_raw = await auth_task
    except InvalidCredentials as exc:
        mensal_task.cancel()
        extras_task.cancel()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except UpstreamUnavailable as exc:
        mensal_task.cancel()
        extras_task.cancel()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    auth_ms = int((time.perf_counter() - auth_started) * 1000)

    usuario_banco = str(
        profile_raw.get("usuario") or payload.usuario
    ).strip()

    profile = {
        "usuario": usuario_banco,
        "nome": str(profile_raw.get("nome") or "").strip(),
        "vendedor": str(
            profile_raw.get("vendedor")
            or profile_raw.get("nome")
            or ""
        ).strip(),
        "tipo": str(profile_raw.get("tipo") or "").strip(),
        "setor": str(profile_raw.get("setor") or "").strip(),
        "permissoes": (
            profile_raw.get("permissoes")
            if isinstance(profile_raw.get("permissoes"), dict)
            else {}
        ),
    }

    bootstrap_started = time.perf_counter()
    bootstrap = None

    try:
        mensal_payload, mensal_row = await mensal_task

        try:
            extras_payload_login, extras_row = await extras_task
            _EXTRAS_SNAPSHOT_CACHE["EXTRAS"] = (
                time.monotonic(),
                extras_payload_login,
                extras_row,
            )
        except Exception:
            extras_row = {}

        bootstrap = scope_mensal_dashboard(
            mensal_payload,
            profile,
        )

        bootstrap["horarioMensal"] = _format_snapshot_time(
            mensal_row.get("atualizado_em")
        )
        bootstrap["horarioMensalISO"] = str(
            mensal_row.get("atualizado_em") or ""
        )
        bootstrap["horarioExtras"] = _format_snapshot_time(
            extras_row.get("atualizado_em")
        )
        bootstrap["horarioExtrasISO"] = str(
            extras_row.get("atualizado_em") or ""
        )
        bootstrap["snapshotMensalVersao"] = str(
            mensal_row.get("versao") or ""
        )
        bootstrap["bootstrapMs"] = int(
            (time.perf_counter() - bootstrap_started) * 1000
        )
    except Exception as exc:
        # Login continua válido mesmo se a fotografia estiver temporariamente
        # indisponível. O frontend usa /data/bootstrap como fallback.
        try:
            extras_task.cancel()
        except Exception:
            pass
        bootstrap = None
        print(
            "[FASE2D] bootstrap no login indisponível:",
            str(exc),
        )

    bootstrap_ms = int(
        (time.perf_counter() - bootstrap_started) * 1000
    )

    token = issue_session_token(
        usuario=usuario_banco,
        profile=profile,
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        lifetime_seconds=settings.session_seconds,
    )

    session_key = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    await mark_pending(session_key)

    # Compatibilidade: roda fora da resposta do login.
    background_tasks.add_task(
        run_legacy_login,
        session_key=session_key,
        # A autenticação 2.0 continua usando o usuário normalizado do banco.
        # Somente a ponte legada recebe exatamente o login que foi digitado,
        # preservando o comportamento original do portal 1.x.
        usuario=payload.usuario,
        senha=payload.senha,
        settings=settings,
    )

    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.session_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )

    elapsed_ms = int(
        (time.perf_counter() - total_started) * 1000
    )

    return LoginResponse(
        sucesso=True,
        usuario=UserProfile(**profile),
        expiraEm=settings.session_seconds,
        banco="SUPABASE",
        elapsedMs=elapsed_ms,
        authMs=auth_ms,
        bootstrapMs=bootstrap_ms,
        bootstrap=bootstrap,
    )

@app.get("/auth/me", response_model=MeResponse)
async def me(
    response: Response,
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
):
    # FASE 2H.6 — a restauração de sessão não pode reutilizar 401 antigo.
    # Safari/WebKit pode coalescer/cachear GETs idênticos em janelas curtas.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    if not session:
        raise HTTPException(status_code=401, detail="Sessão ausente.")

    try:
        data = decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida.") from exc

    profile = UserProfile(
        usuario=str(data.get("usuario") or data.get("sub") or ""),
        nome=str(data.get("nome") or ""),
        vendedor=str(data.get("vendedor") or ""),
        tipo=str(data.get("tipo") or ""),
        setor=str(data.get("setor") or ""),
        permissoes=(
            data.get("permissoes")
            if isinstance(data.get("permissoes"), dict)
            else {}
        ),
    )

    return MeResponse(
        autenticado=True,
        usuario=profile,
    )



def _format_snapshot_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Recife")).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return text


@app.get("/data/bootstrap")
async def bootstrap_dashboard(
    request: Request,
    response: Response,
    competencia: str | None = None,
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

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

    started = time.perf_counter()

    mensal_task = asyncio.create_task(
        home_publication_cache_get(modulo="MENSAL", settings=settings)
    )
    extras_task = asyncio.create_task(
        home_publication_cache_get(modulo="EXTRAS", settings=settings)
    )

    try:
        mensal_payload, mensal_row = await mensal_task
        scoped = scope_mensal_dashboard(
            mensal_payload,
            profile,
            competencia=competencia,
        )
    except CacheReadError as exc:
        extras_task.cancel()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "[2H4 OBS] bootstrap_failed request_id=%s elapsed_ms=%s competencia=%s error=%s",
            getattr(request.state, "request_id", "-"),
            elapsed_ms,
            competencia or "ATUAL",
            str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    extras_row = {}
    try:
        extras_payload_bootstrap, extras_row = await extras_task
        _EXTRAS_SNAPSHOT_CACHE["EXTRAS"] = (
            time.monotonic(),
            extras_payload_bootstrap,
            extras_row,
        )
    except Exception:
        cached_extras = _EXTRAS_SNAPSHOT_CACHE.get("EXTRAS")
        extras_row = (
            cached_extras[2]
            if cached_extras and isinstance(cached_extras[2], dict)
            else {}
        )

    scoped["horarioMensal"] = _format_snapshot_time(
        mensal_row.get("atualizado_em")
    )
    scoped["horarioMensalISO"] = str(
        mensal_row.get("atualizado_em") or ""
    )
    scoped["horarioExtras"] = _format_snapshot_time(
        extras_row.get("atualizado_em")
    )
    scoped["horarioExtrasISO"] = str(
        extras_row.get("atualizado_em") or ""
    )

    scoped["snapshotMensalVersao"] = str(
        mensal_row.get("versao") or ""
    )
    scoped["bootstrapMs"] = int(
        (time.perf_counter() - started) * 1000
    )
    response.headers["X-DISMEPE-Bootstrap-Ms"] = str(scoped["bootstrapMs"])
    response.headers["X-DISMEPE-Bootstrap-Competencia"] = str(competencia or "ATUAL")
    logger.info(
        "[2H4 OBS] bootstrap_ok request_id=%s elapsed_ms=%s competencia=%s mensal_versao=%s",
        getattr(request.state, "request_id", "-"),
        scoped["bootstrapMs"],
        competencia or "ATUAL",
        scoped.get("snapshotMensalVersao") or "-",
    )
    return scoped



@app.get("/data/history-list")
async def history_list_snapshot(
    kind: str = "mensal",
    response: Response = None,
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    ),
):
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

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

    started = time.perf_counter()

    try:
        result = await history_list(
            kind=kind,
            profile=profile,
            settings=settings,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HistoryReadError as exc:
        # 503 permite que o frontend use o caminho legado somente como fallback.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result["elapsedMs"] = int(
        (time.perf_counter() - started) * 1000
    )
    return result


@app.get("/data/history-get")
async def history_get_snapshot(
    history_id: str,
    kind: str = "mensal",
    response: Response = None,
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    ),
):
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

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

    started = time.perf_counter()

    try:
        result = await history_get(
            kind=kind,
            history_id=history_id,
            profile=profile,
            settings=settings,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HistoryReadError as exc:
        # 503 mantém o caminho legado apenas como fallback de compatibilidade.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result["elapsedMs"] = int(
        (time.perf_counter() - started) * 1000
    )
    return result


@app.get("/data/access-log")
async def access_log_snapshot(
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
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

    started = time.perf_counter()
    cache_key = str(profile.get("usuario") or "") + "|ACCESS_LOG"

    cached = _ACCESS_RESULT_CACHE.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _ACCESS_RESULT_TTL_SECONDS:
        result = copy.deepcopy(cached[1])
        result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        result["memoryCache"] = True
        return result

    try:
        result = await list_accesses(
            profile=profile,
            settings=settings,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccessReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
    result["memoryCache"] = False

    _ACCESS_RESULT_CACHE[cache_key] = (
        time.monotonic(),
        copy.deepcopy(result),
    )
    return result


@app.get("/data/access-user")
async def access_user_snapshot(
    usuario: str,
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
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

    try:
        return await access_user(
            profile=profile,
            usuario=usuario,
            settings=settings,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AccessReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/data/campanhas-extras")
async def campanhas_extras_snapshot(
    id: str = "LIST",
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
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

    started = time.perf_counter()

    cache_key = (
        str(profile.get("usuario") or "")
        + "|"
        + str(profile.get("tipo") or "")
        + "|"
        + str(id or "LIST")
    )

    cached = _EXTRAS_RESULT_CACHE.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _EXTRAS_RESULT_TTL_SECONDS:
        result = copy.deepcopy(cached[1])
        result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        result["memoryCache"] = True
        result["snapshotCache"] = True
        return result

    snapshot_cached = _EXTRAS_SNAPSHOT_CACHE.get("EXTRAS")
    snapshot_hit = bool(
        snapshot_cached
        and (time.monotonic() - snapshot_cached[0]) < _EXTRAS_SNAPSHOT_TTL_SECONDS
    )

    if snapshot_hit:
        extras_payload = snapshot_cached[1]
        extras_row = snapshot_cached[2]
    else:
        try:
            extras_payload, extras_row = await cache_get(
                modulo="EXTRAS",
                settings=settings,
            )
            _EXTRAS_SNAPSHOT_CACHE["EXTRAS"] = (
                time.monotonic(),
                extras_payload,
                extras_row,
            )
        except CacheReadError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Para abrir a lista/overview não precisamos consultar USUARIOS.
    # O perfil autenticado já contém usuario/nome/vendedor para regras EXCETO.
    if str(id or "LIST").upper() == "LIST":
        users_payload = {"usuarios": []}
    else:
        try:
            users_payload, _ = await cache_get(
                modulo="USUARIOS",
                settings=settings,
            )
        except Exception:
            users_payload = {"usuarios": []}

    try:
        result = extras_api_response(
            extras_payload=extras_payload,
            users_payload=users_payload,
            profile=profile,
            campaign_id=id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result["atualizadoEm"] = str(
        extras_row.get("atualizado_em") or ""
    )
    result["snapshotVersao"] = str(
        extras_row.get("versao") or ""
    )
    result["elapsedMs"] = int(
        (time.perf_counter() - started) * 1000
    )
    result["memoryCache"] = False
    result["snapshotCache"] = bool(snapshot_hit)

    _EXTRAS_RESULT_CACHE[cache_key] = (
        time.monotonic(),
        copy.deepcopy(result),
    )

    return result


@app.get("/data/extras-users")
async def extras_users_snapshot(
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
):
    """Lista Vendedores/Televendas para administração de Campanhas Extras.

    Leitura direta do snapshot USUARIOS no PostgreSQL. Escritas continuam no
    fluxo legado/Apps Script; esta rota existe apenas para remover uma leitura
    administrativa do caminho antigo.
    """
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

    role = str(profile.get("tipo") or "").strip().upper()
    perms = profile.get("permissoes") if isinstance(profile.get("permissoes"), dict) else {}
    can_manage = role in {"ADMINISTRADOR", "ADMIN"} or any(
        perms.get(key) is True
        for key in (
            "CAMPANHAS_EXTRAS_CRIAR",
            "CAMPANHAS_EXTRAS_EDITAR",
            "CAMPANHAS_EXTRAS_ATIVAR_OCULTAR",
            "CAMPANHAS_EXTRAS_EXCLUIR",
            "CAMPANHAS_EXTRAS_OBSERVACAO",
        )
    )
    if not can_manage:
        raise HTTPException(
            status_code=403,
            detail="Você não possui permissão para administrar Campanhas Extras.",
        )

    try:
        payload, row = await cache_get(modulo="USUARIOS", settings=settings)
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    raw_users = payload.get("usuarios") if isinstance(payload.get("usuarios"), list) else []
    users = []
    for item in raw_users:
        if not isinstance(item, dict):
            continue
        tipo = str(item.get("tipo") or item.get("perfil") or "").strip().upper()
        if tipo not in {"VENDEDOR", "TELEVENDAS"}:
            continue
        users.append({
            "usuario": str(item.get("usuario") or ""),
            "nome": str(item.get("nome") or ""),
            "vendedor": str(item.get("vendedor") or item.get("nome") or ""),
            "tipo": tipo,
            "setor": str(item.get("setor") or ""),
        })

    users.sort(key=lambda u: (
        str(u.get("tipo") or ""),
        str(u.get("vendedor") or u.get("nome") or u.get("usuario") or "").upper(),
    ))

    return {
        "sucesso": True,
        "usuarios": users,
        "quantidade": len(users),
        "transporte": "FASTAPI_USUARIOS_SNAPSHOT",
        "atualizadoEm": str(row.get("atualizado_em") or ""),
        "snapshotVersao": str(row.get("versao") or ""),
    }


@app.get("/data/monthly-rule-options")
async def monthly_rule_options_snapshot(
    competencia: str = "",
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    ),
):
    """Leitura direta das opções de Regras/Métricas da Campanha Mensal.

    A fonte é o snapshot MENSAL no PostgreSQL. Esta rota não grava nada;
    cadastrar/editar/duplicar/excluir métricas continua no fluxo existente.
    """
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

    try:
        payload, row = await cache_get(modulo="MENSAL", settings=settings)
        return monthly_rule_options(
            payload=payload,
            profile=profile,
            competencia=competencia,
            snapshot_row=row,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/data/resumo-ganhos")
async def resumo_ganhos_snapshot(
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
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

    try:
        payload, row = await cache_get(
            modulo="RESUMO_PREMIACOES",
            settings=settings,
        )
        scoped = scope_resumo_ganhos(payload, profile)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    scoped["atualizadoEm"] = (
        scoped.get("atualizadoEm")
        or row.get("atualizado_em")
        or ""
    )
    scoped["snapshotVersao"] = str(row.get("versao") or "")
    return scoped


@app.get("/data/clientes-ped")
async def clientes_ped_snapshot(
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
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

    try:
        payload, row = await cache_get(
            modulo="CLIENTES_PED",
            settings=settings,
        )
        scoped = scope_clientes_ped(payload, profile)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CacheReadError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    scoped["atualizadoEm"] = (
        scoped.get("atualizadoEm")
        or row.get("atualizado_em")
        or ""
    )
    scoped["snapshotVersao"] = str(row.get("versao") or "")
    scoped["transporte"] = "FASTAPI_SUPABASE_CACHE_GET"
    return scoped


@app.get("/auth/legacy-status")
async def legacy_status(
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
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

    return {
        "status": state.get("status", "MISSING"),
        "token": state.get("token", "") if state.get("status") == "READY" else "",
        "error": state.get("error", "") if state.get("status") == "ERROR" else "",
    }


@app.post("/auth/logout")
async def logout(
    response: Response,
    session: str | None = Cookie(
        default=None,
        alias=settings.cookie_name,
    )
):
    if session:
        try:
            session_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
            await clear_state(session_key)
        except Exception:
            pass

    response.delete_cookie(
        key=settings.cookie_name,
        domain=settings.cookie_domain,
        path="/",
    )
    return {"sucesso": True}
