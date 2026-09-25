from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import httpx
import jwt
from fastapi import Cookie, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import main as main_module
from . import prod4_app as prod4
from .cache_reads import CacheReadError, cache_get
from .monthly_commercial_live import sync_commercial, CommercialSyncError
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
from .terms_responsibility import router as terms_responsibility_router
from .terms_storage_routes import router as terms_storage_router


BUILD = "2.0.0-phase2i2-prod5.9.7.3-legacy-cookie"
ROOT = Path(__file__).resolve().parents[1]
BASE_PATCH_FILE = ROOT / "frontend" / "update-center-prod4.js"
MONTHLY_PATCH_FILE = ROOT / "frontend" / "monthly-sync-prod597.js"
HOME_PUBLICATION_PATCH_FILE = ROOT / "frontend" / "home-publication-prod59823.js"
STOCK_SCHEDULE_PATCH_FILE = ROOT / "frontend" / "stock-schedule-prod59823.js"
SECURITY_PASSWORD_PATCH_FILE = ROOT / "frontend" / "security-password-prod600.js"
PASSWORD_CHANGE_REQUIRED = "SEGURANCA_TROCA_SENHA_OBRIGATORIA"

app.include_router(home_publication_router)
app.include_router(stock_schedule_router)
# Pilot of confidentiality agreement: endpoints only, no access guard until Drive verified.
app.include_router(terms_responsibility_router)
app.include_router(terms_storage_router)

# Aceite obrigatório limitado à conta JOSE. Todas as demais contas seguem sem
# alteração. O estado vem do registro confirmado no PostgreSQL, nunca do JS.
# Cache apenas de aceites positivos para evitar consultar o banco a cada asset.
_TERMS_JOSE_POSITIVE = {}

@app.middleware("http")
async def jose_confidentiality_term_guard(request: Request, call_next):
    session = request.cookies.get(settings.cookie_name)
    if not session:
        return await call_next(request)
    try:
        profile = decode_session_token(
            session, secret=settings.jwt_secret, issuer=settings.jwt_issuer,
        )
    except Exception:
        return await call_next(request)
    if str(profile.get("usuario") or profile.get("sub") or "").strip().upper() != "JOSE":
        return await call_next(request)

    # Uma exigência já existente de troca de senha tem precedência. Após
    # a troca, JOSE será direcionado ao termo antes de ver dados comerciais.
    perms = profile.get("permissoes")
    if isinstance(perms, dict) and perms.get(PASSWORD_CHANGE_REQUIRED) is True:
        return await call_next(request)

    path = request.url.path
    public_paths = {
        "/health", "/auth/login", "/auth/me", "/auth/logout",
        "/termo/assinar", "/termo/api/status", "/termo/api/assinar",
    }
    if path in public_paths:
        return await call_next(request)
    # Recursos estáticos não contêm dados comerciais; APIs e páginas
    # autenticadas continuam fechadas enquanto não houver aceite.
    static = request.method == "GET" and path.lower().endswith((
        ".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico",
        ".webp", ".woff", ".woff2", ".ttf", ".webmanifest",
    )) and not path.startswith(("/api/", "/admin/", "/data/"))
    if static:
        return await call_next(request)

    import time as _time
    from .terms_storage_routes import storage_call
    key = hashlib.sha256(session.encode("utf-8")).hexdigest()
    now = _time.monotonic()
    if _TERMS_JOSE_POSITIVE.get(key, 0) <= now:
        try:
            result = await storage_call("STATUS", "JOSE")
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": {"codigo": "TERMO_STATUS_INDISPONIVEL",
                                    "mensagem": "Não foi possível verificar o Termo. Tente novamente."}},
                headers={"Cache-Control": "no-store, private"},
            )
        if result.get("assinado") is True:
            if len(_TERMS_JOSE_POSITIVE) > 1024:
                _TERMS_JOSE_POSITIVE.clear()
            _TERMS_JOSE_POSITIVE[key] = now + 30
        else:
            if request.method == "GET" and (
                path in {"/", "/portal-v2-homolog.html"}
                or "text/html" in request.headers.get("accept", "").lower()
            ):
                return RedirectResponse(url="/termo/assinar", status_code=303,
                                        headers={"Cache-Control": "no-store, private"})
            return JSONResponse(
                status_code=428,
                content={"detail": {"codigo": "TERMO_RESPONSABILIDADE_OBRIGATORIO",
                                    "mensagem": "Assine o Termo de Responsabilidade antes de continuar.",
                                    "destino": "/termo/assinar"}},
                headers={"Cache-Control": "no-store, private"},
            )
    return await call_next(request)

LEGACY_COOKIE_PREFIX = "dismepe_legacy_"
LEGACY_COOKIE_MAX_AGE = 3 * 60 * 60


@app.middleware("http")
async def password_change_required_guard(request: Request, call_next):
    session = request.cookies.get(settings.cookie_name)
    if not session:
        return await call_next(request)

    path = request.url.path
    safe_exact = {"/", "/portal-v2-homolog.html", "/phase1-login.html", "/health", "/auth/login", "/auth/me", "/auth/logout", "/admin/security/change-required-password", "/update-center-prod4.js"}
    safe_static = request.method == "GET" and path.lower().endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".webp"))
    if path in safe_exact or safe_static:
        return await call_next(request)

    try:
        profile = decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except Exception:
        return await call_next(request)

    perms = profile.get("permissoes")
    if isinstance(perms, dict) and perms.get(PASSWORD_CHANGE_REQUIRED) is True:
        # Navegacao HTML: mostrar somente o formulario de troca, sem liberar APIs.
        # A resposta 428 continua obrigatoria para consultas e operacoes de dados.
        accepts_html = request.method == "GET" and "text/html" in request.headers.get("accept", "").lower()
        if accepts_html and not path.startswith(("/api/", "/admin/", "/auth/")):
            html = ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
                    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                    "<title>Troca obrigatória de senha | DISMEPE ONE</title></head>"
                    "<body style=\"font-family:system-ui,sans-serif;background:#f1f7f4;color:#143f34;padding:24px\">"
                    "<main><h1>DISMEPE ONE</h1><p>Troca obrigatória de senha. Aguarde o formulário.</p></main>"
                    "<script src=\"/industrias/security-required-password.js\"></script></body></html>")
            return HTMLResponse(content=html, headers={"Cache-Control": "no-store, private"})
        return JSONResponse(status_code=428, content={"detail": {"codigo": "TROCA_SENHA_OBRIGATORIA", "mensagem": "Troque sua senha antes de continuar."}}, headers={"Cache-Control": "no-store, private"})

    return await call_next(request)


@app.get("/industrias/security-required-password.js", include_in_schema=False)
async def prod_password_required_script():
    # Entregar somente o JavaScript ja existente do formulario de troca.
    return Response(content=SECURITY_PASSWORD_PATCH_FILE.read_text(encoding="utf-8"),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-store, private"})


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


UPDATE_CENTER_SQL_SYNC_VERSION = "PROD5.9.8.23.14_UPDATE_CENTER_SQL_SYNC_V1"


def _updated_modules(payload: dict) -> set[str]:
    rows = payload.get("acoes") if isinstance(payload.get("acoes"), list) else []
    names: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("atualizar") is False:
            continue
        name = str(item.get("modulo") or "").strip().upper()
        if name:
            names.add(name)
    return names


def _comp_value(value: Any) -> str:
    if isinstance(value, dict):
        value = (
            value.get("competencia")
            or value.get("COMPETENCIA")
            or value.get("competência")
            or value.get("Competencia")
            or value.get("Competência")
            or ""
        )
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) >= 7:
        text = text[:7]
    if len(text) == 7 and text[2] == "/":
        mm, yyyy = text[:2], text[3:]
        if mm.isdigit() and yyyy.isdigit():
            return f"{int(mm):02d}/{int(yyyy):04d}"
    if len(text) == 7 and text[4] == "-":
        yyyy, mm = text[:4], text[5:]
        if mm.isdigit() and yyyy.isdigit():
            return f"{int(mm):02d}/{int(yyyy):04d}"
    if len(text) == 7 and text[2] == "-":
        mm, yyyy = text[:2], text[3:]
        if mm.isdigit() and yyyy.isdigit():
            return f"{int(mm):02d}/{int(yyyy):04d}"
    return text


def _row_comp(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return _comp_value(
        row.get("__COMPETENCIA")
        or row.get("competencia")
        or row.get("COMPETENCIA")
        or row.get("Competencia")
        or row.get("Competência")
        or ""
    )


def _comp_order(comp: str) -> int:
    comp = _comp_value(comp)
    try:
        mm, yyyy = comp.split("/")
        return int(yyyy) * 100 + int(mm)
    except Exception:
        return 0


def _latest_comp(payload: dict) -> str:
    values: list[str] = []
    for key in ("competenciasAtivas", "competenciasSelecionadas", "competenciasDisponiveis", "competencias"):
        rows = payload.get(key)
        if isinstance(rows, list):
            for item in rows:
                comp = _comp_value(item)
                if comp:
                    values.append(comp)

    direct = _comp_value(payload.get("competenciaPrincipal"))
    if direct:
        values.append(direct)

    current = payload.get("campanhaMensalAtual")
    if isinstance(current, dict):
        comp = _comp_value(current.get("competencia"))
        if comp:
            values.append(comp)

    for key in ("dadosVendedores", "dadosTelevendas"):
        rows = payload.get(key)
        if isinstance(rows, list):
            for row in rows:
                comp = _row_comp(row)
                if comp:
                    values.append(comp)

    values = list(dict.fromkeys(values))
    values.sort(key=_comp_order, reverse=True)
    return values[0] if values else ""


def _list_from_legacy(payload: dict, *keys: str) -> list[dict]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _normalize_rows_comp(rows: list[dict], comp: str) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        if comp and not _row_comp(item):
            item["competencia"] = comp
            item["__COMPETENCIA"] = comp
        out.append(item)
    return out


def _merge_rows_by_comp(old_rows: Any, new_rows: list[dict], comps: set[str]) -> list[dict]:
    old_list = [row for row in old_rows if isinstance(row, dict)] if isinstance(old_rows, list) else []
    kept = [row for row in old_list if _row_comp(row) not in comps]
    return kept + new_rows


def _merge_competencias(old_items: Any, new_items: Any) -> list[Any]:
    old_list = list(old_items) if isinstance(old_items, list) else []
    new_list = list(new_items) if isinstance(new_items, list) else []
    if not new_list:
        return old_list

    replacements = {
        _comp_value(item): item
        for item in new_list
        if _comp_value(item)
    }
    out: list[Any] = []
    seen: set[str] = set()

    for item in old_list:
        comp = _comp_value(item)
        if comp and comp in replacements:
            out.append(replacements[comp])
            seen.add(comp)
        else:
            out.append(item)
            if comp:
                seen.add(comp)

    for item in new_list:
        comp = _comp_value(item)
        if not comp or comp not in seen:
            out.append(item)
            if comp:
                seen.add(comp)

    return out


async def _legacy_read(
    *,
    action: str,
    legacy_token: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-gateway"
    body: dict[str, Any] = {
        "acao": str(action or "").strip().upper(),
        "token": str(legacy_token or "").strip(),
    }
    if extra:
        body.update(extra)

    timeout_seconds = 125.0 if body["acao"] == "DADOS" else 65.0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
        ) as client:
            response = await client.post(
                endpoint,
                json=body,
                headers={
                    "Content-Type": "application/json;charset=utf-8",
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise RuntimeError(
            f"Leitura {body['acao']} do legado indisponivel."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Leitura {body['acao']} retornou resposta invalida (HTTP {response.status_code})."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Leitura {body['acao']} retornou payload invalido.")

    if response.status_code < 200 or response.status_code >= 300 or data.get("sucesso") is False:
        message = (
            data.get("erro")
            or data.get("error")
            or data.get("mensagem")
            or f"HTTP {response.status_code}"
        )
        raise RuntimeError(f"{body['acao']}: {message}")

    return data


async def _cache_set_snapshot(
    *,
    modulo: str,
    payload: dict[str, Any],
    profile: dict[str, Any],
    version: str | None = None,
) -> tuple[str, str]:
    endpoint = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = {
        "acao": "CACHE_SET",
        "modulo": modulo,
        "payload": payload,
        "atualizado_por": str(profile.get("usuario") or "").strip(),
        "nome": str(profile.get("nome") or profile.get("usuario") or "").strip(),
        "tamanho": len(serialized),
        "versao": version or UPDATE_CENTER_SQL_SYNC_VERSION,
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(65.0),
            follow_redirects=True,
        ) as client:
            response = await client.post(
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
        raise RuntimeError(f"Falha ao gravar snapshot {modulo} no PostgreSQL.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Snapshot {modulo} retornou resposta invalida (HTTP {response.status_code})."
        ) from exc

    if (
        response.status_code < 200
        or response.status_code >= 300
        or not isinstance(data, dict)
        or data.get("sucesso") is False
    ):
        message = (
            data.get("erro")
            if isinstance(data, dict)
            else ""
        ) or (
            data.get("error")
            if isinstance(data, dict)
            else ""
        ) or f"HTTP {response.status_code}"
        raise RuntimeError(f"Snapshot {modulo}: {message}")

    # O HTTP 200 do gateway não comprova a persistência da nova fotografia.
    # Confirme o payload real, não apenas a presença de um timestamp antigo.
    saved, row = await cache_get(modulo=modulo, settings=settings)
    raw = str(row.get("atualizado_em") or "").strip()
    if not raw or saved != payload:
        raise RuntimeError(
            f"Snapshot {modulo}: leitura do PostgreSQL não confirmou os dados enviados."
        )
    return main_module._format_snapshot_time(raw), raw


async def _refresh_monthly_snapshot(
    *,
    legacy_token: str,
    profile: dict[str, Any],
    require_change: bool = False,
) -> tuple[str, str]:
    current, _row = await cache_get(modulo="MENSAL", settings=settings)
    fresh = await _legacy_read(
        action="DADOS",
        legacy_token=legacy_token,
    )

    vend = _list_from_legacy(
        fresh,
        "dadosVendedores",
        "CAMPANHA VEND",
        "CAMPANHAS VND",
    )
    tlv = _list_from_legacy(
        fresh,
        "dadosTelevendas",
        "CAMPANHAS TLVS",
        "CAMPANHA TLVS",
    )

    if not vend and not tlv:
        raise RuntimeError(
            "DADOS retornou sem dadosVendedores/dadosTelevendas; snapshot anterior preservado."
        )

    comps: set[str] = set()
    for key in ("competenciasAtivas", "competenciasSelecionadas"):
        values = fresh.get(key)
        if isinstance(values, list):
            comps.update(_comp_value(x) for x in values if _comp_value(x))

    for value in (
        fresh.get("competenciaPrincipal"),
        (fresh.get("campanhaMensalAtual") or {}).get("competencia")
        if isinstance(fresh.get("campanhaMensalAtual"), dict)
        else "",
    ):
        comp = _comp_value(value)
        if comp:
            comps.add(comp)

    for row in vend + tlv:
        comp = _row_comp(row)
        if comp:
            comps.add(comp)

    if not comps:
        fallback = _latest_comp(current)
        if fallback:
            comps.add(fallback)

    if not comps:
        raise RuntimeError(
            "Nao foi possivel identificar a competencia atual; snapshot anterior preservado."
        )

    primary_comp = sorted(comps, key=_comp_order, reverse=True)[0]
    vend = _normalize_rows_comp(vend, primary_comp if len(comps) == 1 else "")
    tlv = _normalize_rows_comp(tlv, primary_comp if len(comps) == 1 else "")

    fresh_rules = _list_from_legacy(fresh, "regrasPremiacao")
    if fresh_rules and len(comps) == 1:
        normalized_rules: list[dict] = []
        for row in fresh_rules:
            item = dict(row)
            if not _row_comp(item):
                item["competencia"] = primary_comp
            normalized_rules.append(item)
        fresh_rules = normalized_rules

    merged = dict(current)
    merged["dadosVendedores"] = _merge_rows_by_comp(
        current.get("dadosVendedores"),
        vend,
        comps,
    )
    merged["dadosTelevendas"] = _merge_rows_by_comp(
        current.get("dadosTelevendas"),
        tlv,
        comps,
    )

    if fresh_rules:
        merged["regrasPremiacao"] = _merge_rows_by_comp(
            current.get("regrasPremiacao"),
            fresh_rules,
            comps,
        )

    new_competencias = (
        fresh.get("competenciasDisponiveis")
        if isinstance(fresh.get("competenciasDisponiveis"), list)
        else fresh.get("competencias")
    )
    merged["competencias"] = _merge_competencias(
        current.get("competencias"),
        new_competencias,
    )

    old_days = current.get("diasUteisPorCompetencia")
    old_days = dict(old_days) if isinstance(old_days, dict) else {}
    new_days = fresh.get("diasUteisPorCompetencia")
    if isinstance(new_days, dict):
        old_days.update(new_days)
    merged["diasUteisPorCompetencia"] = old_days

    for key in (
        "versaoCalculoVendedores",
        "versaoDadosSql",
    ):
        value = fresh.get(key)
        if value not in (None, ""):
            merged[key] = value

    # Sem confirmação de horário, só sincronizamos se os dados reais lidos
    # do legado diferirem da base persistida. Um novo horário isolado não prova
    # que a campanha foi atualizada.
    if require_change and not any(
        merged.get(key) != current.get(key)
        for key in (
            "dadosVendedores", "dadosTelevendas", "regrasPremiacao",
            "competencias", "diasUteisPorCompetencia",
            "versaoCalculoVendedores", "versaoDadosSql",
        )
    ):
        raise RuntimeError("DADOS legado não trouxe alteração verificável na base mensal")

    merged["geradoEmSql"] = datetime.now(timezone.utc).isoformat()

    return await _cache_set_snapshot(
        modulo="MENSAL",
        payload=merged,
        profile=profile,
    )


def _extra_observation(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(x).strip() for x in value if str(x).strip())
    return str(value or "").strip()


async def _refresh_extras_snapshot(
    *,
    legacy_token: str,
    profile: dict[str, Any],
    require_change: bool = False,
) -> tuple[str, str]:
    listing = await _legacy_read(
        action="LISTARCAMPANHASEXTRAS",
        legacy_token=legacy_token,
    )
    source = listing.get("todas")
    if not isinstance(source, list):
        source = listing.get("campanhas")
    if not isinstance(source, list):
        raise RuntimeError(
            "LISTARCAMPANHASEXTRAS retornou sem campanhas; snapshot anterior preservado."
        )

    campaigns = [dict(row) for row in source if isinstance(row, dict)]
    sales_by_campaign: dict[str, list[dict[str, Any]]] = {}

    for campaign in campaigns:
        campaign_id = str(campaign.get("id") or "").strip()
        if not campaign_id:
            continue

        partial = await _legacy_read(
            action="PARCIALCAMPANHAEXTRA",
            legacy_token=legacy_token,
            extra={
                "id": campaign_id,
                "campanhaId": campaign_id,
                "idCampanha": campaign_id,
            },
        )
        records = partial.get("registros")
        if not isinstance(records, list):
            raise RuntimeError(
                f"Campanha Extra {campaign_id} retornou sem registros; snapshot anterior preservado."
            )

        focus_code = str(campaign.get("codigoProdutoFoco") or "").strip()
        normalized: list[dict[str, Any]] = []
        for row in records:
            if not isinstance(row, dict):
                continue
            qty = row.get("quantidadeProdutoFoco")
            if qty in (None, ""):
                qty = row.get("quantidade")
            normalized.append({
                "colaborador": str(row.get("colaborador") or "").strip(),
                "laboratorio": str(
                    row.get("laboratorio")
                    or campaign.get("laboratorio")
                    or ""
                ).strip(),
                "data": "",
                "venda": row.get("venda") or 0,
                "codigoProduto": str(
                    row.get("codigoProduto")
                    or (focus_code if qty not in (None, "", 0, 0.0, "0") else "")
                ).strip(),
                "quantidade": qty or 0,
                "observacao": _extra_observation(
                    row.get("observacoes")
                    if row.get("observacoes") is not None
                    else row.get("observacao")
                ),
                "idCampanha": campaign_id,
                "campanhaNome": str(campaign.get("nome") or "").strip(),
            })

        sales_by_campaign[campaign_id] = normalized

    snapshot = {
        "campanhas": campaigns,
        "vendasPorCampanha": sales_by_campaign,
    }
    if require_change:
        previous, _row = await cache_get(modulo="EXTRAS", settings=settings)
        if all(snapshot.get(key) == previous.get(key) for key in ("campanhas", "vendasPorCampanha")):
            raise RuntimeError("LISTARCAMPANHASEXTRAS não trouxe alteração verificável na base extras")
    return await _cache_set_snapshot(
        modulo="EXTRAS",
        payload=snapshot,
        profile=profile,
    )


async def _persisted_cache_time(modulo: str) -> tuple[str, str]:
    try:
        _payload, row = await cache_get(modulo=modulo, settings=settings)
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

    # Uma unica linha temporal: logs existentes e avisos publicados compartilham
    # as mesmas colunas, filtros e ordenacao do LOG. Nao alteramos o banco.
    local_tz = ZoneInfo("America/Recife")

    def event_epoch(row: dict, *, notification: bool = False) -> int:
        value = row.get("criadoEpoch") if notification else row.get("epoch_ms")
        try:
            number = int(value)
            if number > 0:
                return number if number >= 100000000000 else number * 1000
        except (TypeError, ValueError, OverflowError):
            pass
        if not notification:
            raw = row.get("data_hora")
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
                    if parsed.tzinfo is not None:
                        return int(parsed.timestamp() * 1000)
                except ValueError:
                    pass
        # Jamais usar a hora da consulta como se fosse a hora do evento.
        return 0

    def event_display(epoch: int, original: str = "") -> str:
        if epoch > 0:
            try:
                return datetime.fromtimestamp(epoch / 1000, local_tz).strftime("%d/%m/%Y %H:%M:%S")
            except (ValueError, OverflowError, OSError):
                pass
        # O texto legado sem timestamp permanece explicito, sem inventar horario.
        return original.strip() if original.strip() else "Data/hora nao registrada"

    legacy = []
    for row in data.get("registros", []):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        epoch = event_epoch(item)
        item["epoch_ms"] = epoch
        item["dataHora"] = event_display(epoch, str(item.get("dataHora") or ""))
        legacy.append(item)

    notices = []
    aviso_notificacoes = ""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=True
        ) as client:
            notice_response = await client.post(
                endpoint,
                json={"acao": "NOTIFICACOES_ADMIN_LIST"},
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "x-dismepe-token": settings.edge_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                },
            )
        notice_data = notice_response.json()
        if (not 200 <= notice_response.status_code < 300
                or not isinstance(notice_data, dict)
                or notice_data.get("sucesso") is not True
                or not isinstance(notice_data.get("notificacoes"), list)):
            raise ValueError("Resposta invalida da consulta de notificacoes.")
        existing_ids = {str(item.get("identificador") or "") for item in legacy}
        for notice in notice_data["notificacoes"]:
            if not isinstance(notice, dict):
                continue
            notice_id = str(notice.get("id") or "")
            if not notice_id.startswith("ONE-PUSH-") or notice_id in existing_ids:
                continue
            epoch = event_epoch(notice, notification=True)
            public = notice.get("publico") if isinstance(notice.get("publico"), dict) else {}
            destination = notice.get("destino") if isinstance(notice.get("destino"), dict) else {}
            audience = (
                "Todos os usuarios" if public.get("todos") is True
                else ", ".join(str(x) for x in (public.get("usuarios") or [])
                               if isinstance(x, str))
                or ", ".join(str(x) for x in (public.get("perfis") or [])
                             if isinstance(x, str))
                or "Destinatarios nao informados"
            )
            target = " / ".join(str(destination.get(key)) for key in
                                ("modulo", "tela", "fornecedor") if destination.get(key))
            details = " | ".join(part for part in (
                str(notice.get("mensagem") or ""),
                "Destinatarios: " + audience,
                "Destino: " + target if target else "",
            ) if part)
            notices.append({
                "id": notice_id,
                "dataHora": event_display(epoch, str(notice.get("criadoEm") or "")),
                "epoch_ms": epoch,
                "usuario": str(notice.get("criadoPor") or ""),
                "nome": str(notice.get("criadoPor") or ""),
                "cargo": "",
                "modulo": "Notificacoes",
                "acao": "PUBLICOU AVISO",
                "entidade": str(notice.get("titulo") or "Notificacao"),
                "identificador": notice_id,
                "detalhes": details,
            })
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        # Falha na fonte adicional nao apaga o LOG tradicional.
        aviso_notificacoes = "Avisos indisponiveis nesta consulta; registros anteriores preservados."

    combined = legacy + notices
    combined.sort(key=lambda row: int(row.get("epoch_ms") or 0), reverse=True)
    today = datetime.now(local_tz).date()
    data["registros"] = combined
    data["resumo"] = {
        "total": len(combined),
        "hoje": sum(1 for row in combined if row.get("epoch_ms") and
                    datetime.fromtimestamp(row["epoch_ms"] / 1000, local_tz).date() == today),
        "usuarios": len({str(row.get("usuario") or "").strip()
                         for row in combined if str(row.get("usuario") or "").strip()}),
        "modulos": len({str(row.get("modulo") or "").strip()
                        for row in combined if str(row.get("modulo") or "").strip()}),
    }
    if aviso_notificacoes:
        data["avisoNotificacoes"] = aviso_notificacoes
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
        + "\n\n"
        + SECURITY_PASSWORD_PATCH_FILE.read_text(encoding="utf-8")
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


@app.post("/admin/home-publication/refresh-related")
async def prod59823_refresh_related(
    request: Request,
    session: str | None = Cookie(default=None, alias=settings.cookie_name),
):
    """Atualiza Extras/PEDS sem republicar MENSAL ou alterar horário da HOME."""
    if not session:
        raise HTTPException(status_code=401, detail="Sessão ausente.")
    try:
        profile = decode_session_token(
            session, secret=settings.jwt_secret, issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.") from exc
    if not prod4._allowed(profile):
        raise HTTPException(status_code=403, detail="Sem permissão para atualização.")
    body = await request.json()
    module = str(body.get("modulo") or "").strip().upper() if isinstance(body, dict) else ""
    if module not in {"EXTRAS", "CLIENTES_PED"}:
        raise HTTPException(status_code=400, detail="Módulo não permitido.")
    role = str(profile.get("tipo") or "").strip().upper()
    perms = profile.get("permissoes") if isinstance(profile.get("permissoes"), dict) else {}
    if module == "CLIENTES_PED" and role not in {"ADMINISTRADOR", "ADMIN"} and not (
        perms.get("CLIENTES_PED_ATUALIZAR") is True or perms.get("CENTRO_ATUALIZACOES") is True
    ):
        raise HTTPException(status_code=403, detail="Sem permissão para atualizar Clientes PEDS.")
    state_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
    token = await _legacy_token(
        session_key=state_key,
        payload=body,
        persisted_token=_legacy_cookie_value(request, session),
        wait_for_ready=True,
    )
    if not token:
        raise HTTPException(status_code=409, detail="Sessão de atualização não disponível. Reentre no sistema.")
    try:
        previous, previous_row = await cache_get(modulo=module, settings=settings)
        if module == "EXTRAS":
            # A leitura real compara valores e preserva o horário quando não mudou.
            listing = await _legacy_read(action="LISTARCAMPANHASEXTRAS", legacy_token=token)
            source = listing.get("todas")
            if not isinstance(source, list):
                source = listing.get("campanhas")
            if not isinstance(source, list):
                raise RuntimeError("A fonte de Campanhas Extras não retornou a lista.")
            campaigns = [dict(x) for x in source if isinstance(x, dict)]
            sales: dict[str, list[dict[str, Any]]] = {}
            for item in campaigns:
                campaign_id = str(item.get("id") or "").strip()
                if not campaign_id:
                    continue
                partial = await _legacy_read(
                    action="PARCIALCAMPANHAEXTRA",
                    legacy_token=token,
                    extra={"id": campaign_id, "campanhaId": campaign_id, "idCampanha": campaign_id},
                )
                records = partial.get("registros")
                if not isinstance(records, list):
                    raise RuntimeError(f"A parcial da campanha {campaign_id} não foi confirmada.")
                focus = str(item.get("codigoProdutoFoco") or "").strip()
                normalized = []
                for row in records:
                    if not isinstance(row, dict):
                        continue
                    qty = row.get("quantidadeProdutoFoco")
                    if qty in (None, ""):
                        qty = row.get("quantidade")
                    normalized.append({
                        "colaborador": str(row.get("colaborador") or "").strip(),
                        "laboratorio": str(row.get("laboratorio") or item.get("laboratorio") or "").strip(),
                        "data": "",
                        "venda": row.get("venda") or 0,
                        "codigoProduto": str(
                            row.get("codigoProduto") or (focus if qty not in (None, "", 0, 0.0, "0") else "")
                        ).strip(),
                        "quantidade": qty or 0,
                        "observacao": _extra_observation(
                            row.get("observacoes") if row.get("observacoes") is not None else row.get("observacao")
                        ),
                        "idCampanha": campaign_id,
                        "campanhaNome": str(item.get("nome") or "").strip(),
                    })
                sales[campaign_id] = normalized
            incoming = {"campanhas": campaigns, "vendasPorCampanha": sales}
            if all(incoming[key] == previous.get(key) for key in incoming):
                return {
                    "sucesso": True, "modulo": module, "resultado": "SEM_ALTERACAO",
                    "mensagem": "Campanhas Extras já estão atualizadas.",
                    "atualizadoEm": str(previous_row.get("atualizado_em") or ""),
                }
        else:
            # O cache CLIENTES_PED contém a base completa, não o escopo de um usuário.
            # Não substituir por DADOS, por uma lista vazia ou por visão individual.
            # Antes da leitura, solicitar a atualização da origem do mesmo modo
            # que a antiga Central fazia. Apenas uma escrita legada por clique.
            legacy_error = ""
            try:
                await call_update_center_legacy(
                    action="OPCACHE_ATUALIZAR",
                    payload={
                        "acao": "OPCACHE_ATUALIZAR",
                        "acoes": [{
                            "modulo": "CLIENTES_PED", "atualizar": True,
                            "notificar": False,
                            "observacao": "Atualização PEDS solicitada na HOME",
                        }],
                    },
                    legacy_token=token,
                )
            except UpdateCenterBridgeError as exc:
                legacy_error = str(exc)[:180]

            # O worker legado pode já ter confirmado a nova fotografia no SQL.
            verified, updated_row = await cache_get(modulo=module, settings=settings)
            compare_fields = (
                "clientes", "setores", "resumo", "vendasPorSetor",
                "setoresMeta", "metaFamilias", "metaEmpresa", "resumoSetor",
            )
            if (
                verified.get("snapshotCompleto") is True
                and verified.get("escopoAcesso") == "GESTAO"
                and isinstance(verified.get("clientes"), list)
                and verified["clientes"]
                and any(verified.get(field) != previous.get(field) for field in compare_fields)
            ):
                return {
                    "sucesso": True, "modulo": module, "resultado": "ATUALIZADA",
                    "mensagem": "Clientes PEDS atualizados e confirmados no PostgreSQL.",
                    "atualizadoEm": str(updated_row.get("atualizado_em") or ""),
                    "clientes": len(verified["clientes"]),
                }
            # Se o worker não persistiu a fotografia, buscar a fonte completa
            # diretamente e compará-la antes de gravar. Nunca aceitar DADOS
            # (parcial individual) como substituto da base de Clientes PEDS.
            try:
                source = await _legacy_read(action="CLIENTES_PED", legacy_token=token)
            except RuntimeError as exc:
                # A origem pode concluir a gravacao no worker depois da resposta
                # da Central. Reconsultar apenas o SQL: nunca repetir a escrita
                # legada nem confundir a fotografia antiga com uma nova.
                for _attempt in range(5):
                    await asyncio.sleep(2)
                    late_payload, late_row = await cache_get(
                        modulo=module, settings=settings,
                    )
                    late_valid = (
                        late_payload.get("snapshotCompleto") is True
                        and late_payload.get("escopoAcesso") == "GESTAO"
                        and isinstance(late_payload.get("clientes"), list)
                        and bool(late_payload["clientes"])
                        and isinstance(late_payload.get("setores"), list)
                        and isinstance(late_payload.get("resumo"), dict)
                        and isinstance(late_payload.get("vendasPorSetor"), dict)
                        and isinstance(late_payload.get("metaEmpresa"), dict)
                    )
                    late_new = (
                        str(late_row.get("atualizado_em") or "")
                        != str(previous_row.get("atualizado_em") or "")
                    )
                    if late_valid and late_new:
                        changed = any(
                            late_payload.get(field) != previous.get(field)
                            for field in compare_fields
                        )
                        return {
                            "sucesso": True,
                            "modulo": module,
                            "resultado": "ATUALIZADA" if changed else "SEM_ALTERACAO",
                            "mensagem": (
                                "Clientes PEDS atualizados e confirmados no PostgreSQL."
                                if changed else "Clientes PEDS já estão atualizados."
                            ),
                            "atualizadoEm": str(late_row.get("atualizado_em") or ""),
                            "clientes": len(late_payload["clientes"]),
                        }
                raise RuntimeError(
                    "A origem Clientes PEDS não retornou a fotografia completa "
                    "e o PostgreSQL não confirmou uma atualização."
                    + (" Falha na Central legada: " + legacy_error if legacy_error else "")
                ) from exc
            incoming = next(
                (candidate for candidate in (
                    source.get("dados"), source.get("payload"), source.get("resultado"), source
                ) if isinstance(candidate, dict) and isinstance(candidate.get("clientes"), list)),
                None,
            )
            if not isinstance(incoming, dict):
                raise RuntimeError("A fonte Clientes PEDS não retornou a fotografia completa.")
            rows = incoming.get("clientes")
            if (
                not isinstance(rows, list) or not rows
                or incoming.get("snapshotCompleto") is not True
                or incoming.get("escopoAcesso") != "GESTAO"
                or not isinstance(incoming.get("setores"), list)
                or not isinstance(incoming.get("resumo"), dict)
                or not isinstance(incoming.get("vendasPorSetor"), dict)
                or not isinstance(incoming.get("metaEmpresa"), dict)
            ):
                raise RuntimeError(
                    "A fonte Clientes PEDS não confirmou um snapshot completo. A base anterior foi preservada."
                )
            # Ignorar timestamps/versões transitórios se o conteúdo da base é igual.
            compare = ("clientes", "setores", "resumo", "vendasPorSetor",
                       "setoresMeta", "metaFamilias", "metaEmpresa", "resumoSetor")
            if all(incoming.get(key) == previous.get(key) for key in compare):
                return {
                    "sucesso": True, "modulo": module, "resultado": "SEM_ALTERACAO",
                    "mensagem": "Clientes PEDS já estão atualizados.",
                    "atualizadoEm": str(previous_row.get("atualizado_em") or ""),
                    "clientes": len(rows),
                }
        display, iso = await _cache_set_snapshot(
            modulo=module, payload=incoming, profile=profile,
            version=str(previous_row.get("versao") or UPDATE_CENTER_SQL_SYNC_VERSION),
        )
        return {
            "sucesso": True, "modulo": module, "resultado": "ATUALIZADA",
            "mensagem": f"{'Campanhas Extras' if module == 'EXTRAS' else 'Clientes PEDS'} atualizados no PostgreSQL.",
            "atualizadoEm": iso, "atualizadoEmFormatado": display,
            "clientes": len(incoming["clientes"]) if module == "CLIENTES_PED" else None,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{'Campanhas Extras' if module == 'EXTRAS' else 'Clientes PEDS'}: {str(exc)[:350]}",
        ) from exc


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
    names = _requested_modules(payload) if action == "OPCACHE_ATUALIZAR" else set()
    updated_names = _updated_modules(payload) if action == "OPCACHE_ATUALIZAR" else set()
    # O Apps Script apenas agenda um novo cálculo para o módulo MENSAL.
    # No caminho exclusivo não é necessário consultar STATUS antes e depois
    # de agendar; a publicação acompanhará o PostgreSQL diretamente.
    monthly_only = (
        action == "OPCACHE_ATUALIZAR"
        and names == {"MENSAL"}
        and updated_names == {"MENSAL"}
        and not any(
            item.get("notificar") is True
            for item in (payload.get("acoes") or [])
            if isinstance(item, dict)
        )
    )

    # Exclusivo comercial: publica em MENSAL_COMERCIAL, nunca regrava MENSAL
    # ou dispara calculo de premiacoes; os demais caminhos ficam inalterados.
    if monthly_only and os.getenv("DISMEPE_MONTHLY_COMMERCIAL_ENABLED", "0") == "1":
        try:
            commercial = await sync_commercial(
                settings=settings, profile=profile, persist=_cache_set_snapshot,
            )
        except CommercialSyncError as exc:
            # Falha de validacao conhecida: a gravacao foi interrompida, nao
            # existe worker legado pendente para justificar nova espera.
            # Exibir somente mensagens controladas pelo proprio sincronizador.
            raise HTTPException(
                status_code=422,
                detail="Campanhas Mensais: atualização comercial não confirmada. "
                       "Fotografia SQL anterior preservada. "
                       f"Motivo: {str(exc)}",
            ) from None
        except Exception as exc:
            # Nunca acionar o worker legado como fallback de uma falha Google/SQL.
            # Nao divulgar mensagens de excecoes externas (podem conter dados
            # da requisicao), mas registrar o tipo para diagnostico no Render.
            main_module.logger.exception("Campanhas Mensais: erro inesperado na sincronizacao comercial (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="Campanhas Mensais: falha técnica na sincronização comercial. "
                       "Fotografia SQL anterior preservada. "
                       f"Tipo de falha: {type(exc).__name__}.",
            ) from None
        if commercial["resultado"] == "SEM_ALTERACAO":
            return {
                "sucesso": True, "ok": True, "mensalSync": "SEM_ALTERACAO",
                "mensalSnapshotFonte": "POSTGRESQL",
                "mensagem": "Os números comerciais já estão atualizados no SQL.",
                "financeiro": commercial["financeiro"], "transporte": "FASTAPI_MENSAL_COMERCIAL",
            }
        return {
            "sucesso": True, "ok": True, "mensalSync": "COMERCIAL_SQL_PUBLICADO",
            "mensalSnapshotFonte": "POSTGRESQL_MENSAL_COMERCIAL",
            "horarioMensalISO": commercial["atualizadoEm"],
            "horarioMensal": main_module._format_snapshot_time(commercial["atualizadoEm"]),
            "mensagem": "Números comerciais atualizados no PostgreSQL; premiações legadas preservadas.",
            "financeiro": commercial["financeiro"], "transporte": "FASTAPI_MENSAL_COMERCIAL",
        }

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

    before_status: dict[str, Any] = {}
    before_times: dict[str, str] = {}
    before_snapshot_times: dict[str, str] = {}
    if action == "OPCACHE_ATUALIZAR":
        if not monthly_only:
            try:
                before_status = await call_update_center_legacy(
                    action="OPCACHE_STATUS",
                    payload={"acao": "OPCACHE_STATUS"},
                    legacy_token=legacy_token,
                )
            except UpdateCenterBridgeError:
                before_status = {}
        before_times = {
            name: prod4._time_from_result(before_status, name)
            for name in names
        }
        # Fonte independente: pode ter sido gravada pelo worker mesmo que
        # OPCACHE_STATUS ainda não informe a nova data.
        for name in updated_names & {"MENSAL", "EXTRAS"}:
            _display, snapshot_iso = await _persisted_cache_time(name)
            if snapshot_iso:
                before_snapshot_times[name] = snapshot_iso

    try:
        result = await call_update_center_legacy(
            action=action,
            payload=payload,
            legacy_token=legacy_token,
        )
    except UpdateCenterBridgeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if action == "OPCACHE_ATUALIZAR":
        # A resposta AGENDADO não prova a atualização. A HOME confere o SQL
        # antes de publicar; não ler DADOS ou emitir mais um STATUS remoto.
        if (monthly_only and result.get("processamentoAssincrono") is True
                and result.get("agendado") is True):
            result["mensalSync"] = "AGUARDANDO_WORKER"
            result["mensalSnapshotFonte"] = "POSTGRESQL_PENDENTE"
            result["mensalPublicacaoPendente"] = True
            result.pop("horarioMensal", None)
            result.pop("horarioMensalISO", None)
            result["transporte"] = "FASTAPI_UPDATE_CENTER_DIRECT"
            return result

        legacy_success = _successful(result)

        after_status: dict[str, Any] = {}
        try:
            after_status = await call_update_center_legacy(
                action="OPCACHE_STATUS",
                payload={"acao": "OPCACHE_STATUS"},
                legacy_token=legacy_token,
            )
        except UpdateCenterBridgeError:
            after_status = {}

        confirmed: set[str] = set()

        def _nested_updated(module_name: str) -> bool:
            rows = result.get("resultados")
            if not isinstance(rows, list):
                return False
            target = str(module_name or "").strip().upper()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                current = str(
                    row.get("modulo")
                    or row.get("nomeModulo")
                    or row.get("label")
                    or ""
                ).strip().upper()
                if not current:
                    continue
                if current == target or target in current or current in target:
                    if row.get("atualizado") is True or row.get("sucesso") is True:
                        return True
            return False

        for name in updated_names:
            before_time = before_times.get(name) or ""
            immediate_time = prod4._time_from_result(result, name)
            after_time = prod4._time_from_result(after_status, name)

            if legacy_success or _nested_updated(name):
                confirmed.add(name)
                continue

            if before_time and immediate_time and immediate_time != before_time:
                confirmed.add(name)
                continue

            if before_time and after_time and after_time != before_time:
                confirmed.add(name)

        # Uma leitura final do PostgreSQL, sem esperar seis STATUS legados.
        # Quando não houver nova data, uma diferença verificada nos dados reais
        # do legado poderá confirmar a atualização no bloco do módulo abaixo.
        persisted_confirmed: dict[str, tuple[str, str]] = {}
        for name in (updated_names & {"MENSAL", "EXTRAS"}) - confirmed:
            baseline = before_snapshot_times.get(name)
            if baseline:
                display, current_iso = await _persisted_cache_time(name)
                if current_iso and current_iso != baseline:
                    persisted_confirmed[name] = (display, current_iso)
                    confirmed.add(name)
        verified_by_data: set[str] = set()

        immediate_times = {
            name: (
                prod4._time_from_result(result, name)
                or prod4._time_from_result(after_status, name)
            )
            for name in names
        }

        completed_display, completed_iso = prod4._update_center_now()
        requested_times = {
            name: immediate_times.get(name) or completed_display
            for name in names
            if name not in {"MENSAL", "EXTRAS"}
        }
        sync_errors: list[str] = []

        # V217: OPCACHE_ATUALIZAR apenas agenda o worker do Apps Script.
        # DADOS já lê o snapshot SQL existente e pode retornar listas vazias
        # antes da conclusão do worker; nunca usá-lo como fonte independente
        # nem reenviar OPCACHE_ATUALIZAR para tentar concluir a publicação.
        monthly_worker_pending = (
            "MENSAL" in updated_names
            and result.get("processamentoAssincrono") is True
            and result.get("agendado") is True
        )
        if monthly_worker_pending:
            confirmed.discard("MENSAL")
            baseline = before_snapshot_times.get("MENSAL", "")
            try:
                monthly_payload, monthly_row = await cache_get(
                    modulo="MENSAL", settings=settings
                )
                current_iso = str(monthly_row.get("atualizado_em") or "").strip()
                saved_lists_valid = (
                    isinstance(monthly_payload.get("dadosVendedores"), list)
                    and isinstance(monthly_payload.get("dadosTelevendas"), list)
                    and bool(
                        monthly_payload["dadosVendedores"]
                        or monthly_payload["dadosTelevendas"]
                    )
                )
                if baseline and current_iso and current_iso != baseline and saved_lists_valid:
                    persisted_confirmed["MENSAL"] = (
                        main_module._format_snapshot_time(current_iso), current_iso
                    )
                    confirmed.add("MENSAL")
                    monthly_worker_pending = False
            except (CacheReadError, RuntimeError):
                pass

            if monthly_worker_pending:
                result["mensalSync"] = "AGUARDANDO_WORKER"
                result["mensalSnapshotFonte"] = "POSTGRESQL_PENDENTE"
                result["mensalPublicacaoPendente"] = True
                result["mensagem"] = (
                    "Campanhas Mensais: atualização agendada. "
                    "A gravação no PostgreSQL está em processamento; "
                    "a fotografia anterior foi preservada."
                )
                result.pop("horarioMensal", None)
                result.pop("horarioMensalISO", None)

        if "MENSAL" in updated_names and not monthly_worker_pending:
            if "MENSAL" not in confirmed:
                try:
                    display, iso = await _refresh_monthly_snapshot(
                        legacy_token=legacy_token,
                        profile=profile,
                        require_change=True,
                    )
                    persisted_confirmed["MENSAL"] = (display, iso)
                    verified_by_data.add("MENSAL")
                    confirmed.add("MENSAL")
                except Exception as exc:
                    sync_errors.append(
                        "Campanhas Mensais: não foi possível confirmar novos dados "
                        "nem sincronizar a base. O snapshot PostgreSQL anterior foi preservado. "
                        f"Detalhe: {str(exc)[:300]}"
                    )
                    result["mensalSync"] = "ERRO_LEGADO_NAO_CONFIRMADO"
            if "MENSAL" in confirmed:
                try:
                    persisted = persisted_confirmed.get("MENSAL")
                    baseline = before_snapshot_times.get("MENSAL")
                    if persisted is None and baseline:
                        display, current_iso = await _persisted_cache_time("MENSAL")
                        if current_iso and current_iso != baseline:
                            persisted = (display, current_iso)
                    if persisted is not None:
                        mensal_display, mensal_iso = persisted
                        result["mensalSnapshotFonte"] = (
                            "POSTGRESQL_REGRAVADO" if "MENSAL" in verified_by_data
                            else "POSTGRESQL_CONFIRMADO"
                        )
                        result["mensalSync"] = (
                            UPDATE_CENTER_SQL_SYNC_VERSION if "MENSAL" in verified_by_data
                            else "POSTGRESQL_ATUALIZADO_EM"
                        )
                    else:
                        mensal_display, mensal_iso = await _refresh_monthly_snapshot(
                            legacy_token=legacy_token,
                            profile=profile,
                            require_change=True,
                        )
                        result["mensalSnapshotFonte"] = "POSTGRESQL_REGRAVADO"
                        result["mensalSync"] = UPDATE_CENTER_SQL_SYNC_VERSION
                    requested_times["MENSAL"] = mensal_display
                    result["horarioMensal"] = mensal_display
                    result["horarioMensalISO"] = mensal_iso
                except Exception as exc:
                    sync_errors.append(
                        "Campanhas Mensais: a base legada foi atualizada, mas o "
                        "snapshot PostgreSQL nao foi regravado. A fotografia anterior "
                        f"foi preservada. Detalhe: {str(exc)[:350]}"
                    )
                    result.pop("horarioMensal", None)
                    result.pop("horarioMensalISO", None)
                    result["mensalSync"] = "ERRO_POSTGRESQL_PRESERVADO"

        if "EXTRAS" in updated_names:
            if "EXTRAS" not in confirmed:
                try:
                    display, iso = await _refresh_extras_snapshot(
                        legacy_token=legacy_token,
                        profile=profile,
                        require_change=True,
                    )
                    persisted_confirmed["EXTRAS"] = (display, iso)
                    verified_by_data.add("EXTRAS")
                    confirmed.add("EXTRAS")
                except Exception as exc:
                    sync_errors.append(
                        "Campanhas Extras: não foi possível confirmar novos dados "
                        "nem sincronizar a base. O snapshot PostgreSQL anterior foi preservado. "
                        f"Detalhe: {str(exc)[:300]}"
                    )
                    result["extrasSync"] = "ERRO_LEGADO_NAO_CONFIRMADO"
            if "EXTRAS" in confirmed:
                try:
                    persisted = persisted_confirmed.get("EXTRAS")
                    baseline = before_snapshot_times.get("EXTRAS")
                    if persisted is None and baseline:
                        display, current_iso = await _persisted_cache_time("EXTRAS")
                        if current_iso and current_iso != baseline:
                            persisted = (display, current_iso)
                    if persisted is not None:
                        extras_display, extras_iso = persisted
                        result["extrasSnapshotFonte"] = (
                            "POSTGRESQL_REGRAVADO" if "EXTRAS" in verified_by_data
                            else "POSTGRESQL_CONFIRMADO"
                        )
                        result["extrasSync"] = (
                            UPDATE_CENTER_SQL_SYNC_VERSION if "EXTRAS" in verified_by_data
                            else "POSTGRESQL_ATUALIZADO_EM"
                        )
                    else:
                        extras_display, extras_iso = await _refresh_extras_snapshot(
                            legacy_token=legacy_token,
                            profile=profile,
                        )
                        result["extrasSnapshotFonte"] = "POSTGRESQL_REGRAVADO"
                        result["extrasSync"] = UPDATE_CENTER_SQL_SYNC_VERSION
                    requested_times["EXTRAS"] = extras_display
                    result["horarioExtras"] = extras_display
                    result["horarioExtrasISO"] = extras_iso
                except Exception as exc:
                    sync_errors.append(
                        "Campanhas Extras: a base legada foi atualizada, mas o "
                        "snapshot PostgreSQL nao foi regravado. A fotografia anterior "
                        f"foi preservada. Detalhe: {str(exc)[:350]}"
                    )
                    result.pop("horarioExtras", None)
                    result.pop("horarioExtrasISO", None)
                    result["extrasSync"] = "ERRO_POSTGRESQL_PRESERVADO"

        modules = (
            after_status.get("modulos")
            if isinstance(after_status.get("modulos"), list)
            else []
        )
        if modules:
            result["modulos"] = modules

        prod4._stamp_requested_modules(result, requested_times)

        if "MENSAL" in requested_times:
            mensal_display, mensal_iso = await _persisted_cache_time("MENSAL")
            if mensal_display:
                result["horarioMensal"] = mensal_display
                result["horarioMensalISO"] = mensal_iso

        if "EXTRAS" in requested_times:
            extras_display, extras_iso = await _persisted_cache_time("EXTRAS")
            if extras_display:
                result["horarioExtras"] = extras_display
                result["horarioExtrasISO"] = extras_iso

        if sync_errors:
            existing = result.get("erros")
            if not isinstance(existing, list):
                existing = []
                result["erros"] = existing
            existing.extend(sync_errors)
            result["sucesso"] = False
            result["ok"] = False
            result["erro"] = sync_errors[0]
        else:
            result["sucesso"] = True
            result["ok"] = True
            result.pop("erro", None)
            result.pop("error", None)

    result["transporte"] = "FASTAPI_UPDATE_CENTER_DIRECT"
    if mensal_requested and not result.get("mensalSync"):
        result["mensalSync"] = "SEM_CONFIRMACAO_POSTGRESQL"
    return result


# Positivação Geral: módulo separado, exclusivo para administradores.
from .positivacao_geral import router as positivacao_geral_router
app.include_router(positivacao_geral_router)

# Central de Notificacoes: tela administrativa e API isoladas.
from .notifications_admin import router as notifications_admin_router
app.include_router(notifications_admin_router)

# Web Push: API de dispositivos, Web App Manifest, Service Worker e destino autenticado.
from .push_notifications import router as push_notifications_router
app.include_router(push_notifications_router)

