from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt
from fastapi import Cookie, HTTPException, Request, Response
from fastapi.responses import JSONResponse

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
SECURITY_PASSWORD_PATCH_FILE = ROOT / "frontend" / "security-password-prod600.js"
PASSWORD_CHANGE_REQUIRED = "SEGURANCA_TROCA_SENHA_OBRIGATORIA"

app.include_router(home_publication_router)
app.include_router(stock_schedule_router)

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
        return JSONResponse(status_code=428, content={"detail": {"codigo": "TROCA_SENHA_OBRIGATORIA", "mensagem": "Troque sua senha antes de continuar."}}, headers={"Cache-Control": "no-store, private"})

    return await call_next(request)


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
        "versao": UPDATE_CENTER_SQL_SYNC_VERSION,
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

    _saved, row = await cache_get(modulo=modulo, settings=settings)
    raw = str(row.get("atualizado_em") or "").strip()
    if not raw:
        raise RuntimeError(f"Snapshot {modulo} foi gravado sem atualizado_em.")
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

    names = _requested_modules(payload) if action == "OPCACHE_ATUALIZAR" else set()
    updated_names = _updated_modules(payload) if action == "OPCACHE_ATUALIZAR" else set()

    before_status: dict[str, Any] = {}
    before_times: dict[str, str] = {}
    before_snapshot_times: dict[str, str] = {}
    if action == "OPCACHE_ATUALIZAR":
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

        if "MENSAL" in updated_names:
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
        result["mensalSync"] = "POSTGRESQL_ATUALIZADO_EM"
    return result


# Positivação Geral: módulo separado, exclusivo para administradores.
from .positivacao_geral import router as positivacao_geral_router
app.include_router(positivacao_geral_router)
