from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import jwt
from fastapi import Cookie, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from . import main as main_module
from .main import app, settings
from .security import decode_session_token
from .legacy_bridge import get_state
from .history_reads import HistoryReadError
from .cache_reads import CacheReadError, cache_get as cache_read
from .monthly_retention import (
    MonthlyRetentionPurgeError,
    filter_dashboard_payload,
    purge_expired_monthly_history,
    retained_monthly_history_list,
)
from .update_center import UpdateCenterBridgeError, call_update_center_legacy


BUILD = "2.0.0-phase2i2-prod4.4"
ROOT = Path(__file__).resolve().parents[1]
PORTAL_FILE = ROOT / "frontend" / "portal-v2-homolog.html"
PATCH_FILE = ROOT / "frontend" / "update-center-prod4.js"
RETENTION_PATCH_FILE = ROOT / "frontend" / "monthly-retention-prod44.js"


_ORIGINAL_SCOPE_MENSAL_DASHBOARD = main_module.scope_mensal_dashboard
_ORIGINAL_HISTORY_LIST = main_module.history_list


def _scope_mensal_dashboard_prod44(
    payload: dict,
    profile: dict,
    competencia: str | None = None,
):
    result = _ORIGINAL_SCOPE_MENSAL_DASHBOARD(
        payload,
        profile,
        competencia=competencia,
    )
    return filter_dashboard_payload(result)


async def _history_list_prod44(
    *,
    kind: str,
    profile: dict,
    settings,
):
    if str(kind or "").strip().lower() != "mensal":
        return await _ORIGINAL_HISTORY_LIST(
            kind=kind,
            profile=profile,
            settings=settings,
        )

    try:
        return await retained_monthly_history_list(
            profile=profile,
            settings=settings,
        )
    except RuntimeError as exc:
        raise HistoryReadError(str(exc)) from exc


# PROD4.4 — troca somente a apresentação da fotografia mensal e a listagem
# do histórico mensal. Regras, cálculos, fechamento e gravações permanecem
# exatamente nos fluxos existentes.
main_module.scope_mensal_dashboard = _scope_mensal_dashboard_prod44
main_module.history_list = _history_list_prod44


def _remove_routes(*paths: str) -> None:
    wanted = set(paths)
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", None) not in wanted
    ]


def _portal_response() -> HTMLResponse:
    html = PORTAL_FILE.read_text(encoding="utf-8")
    tags = [
        f'<script src="/update-center-prod4.js?v={BUILD}"></script>',
        f'<script src="/monthly-retention-prod44.js?v={BUILD}"></script>',
    ]
    missing = [tag for tag in tags if tag not in html]
    if missing:
        marker = "</body>"
        pos = html.lower().rfind(marker)
        if pos < 0:
            raise RuntimeError("Fechamento </body> não encontrado no portal.")
        html = html[:pos] + "\n".join(missing) + "\n" + html[pos:]
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-DISMEPE-Build": BUILD,
        },
    )


def _allowed(profile: dict) -> bool:
    role = str(profile.get("tipo") or "").strip().upper()
    if role in {"ADMINISTRADOR", "ADMIN"}:
        return True
    perms = profile.get("permissoes") if isinstance(profile.get("permissoes"), dict) else {}
    return any(
        perms.get(key) is True
        for key in (
            "CENTRO_ATUALIZACOES",
            "MENSAL_BASE_ATUALIZADA",
            "EXTRAS_BASE_ATUALIZADA",
        )
    )


def _retention_delete_allowed(profile: dict) -> bool:
    role = str(profile.get("tipo") or "").strip().upper()
    if role in {"ADMINISTRADOR", "ADMIN"}:
        return True
    perms = profile.get("permissoes") if isinstance(profile.get("permissoes"), dict) else {}
    return (
        perms.get("HISTORICO_MENSAL_EXCLUIR") is True
        or perms.get("CADASTRO_CAMPANHAS_MENSAIS") is True
    )


def _time_value(item: dict) -> str:
    if not isinstance(item, dict):
        return ""

    for key in (
        "atualizadoEm",
        "atualizado_em",
        "horario",
        "dataHoraFormatado",
        "dataHoraISO",
        "dataHora",
        "timestamp",
        "updatedAt",
        "updated_at",
    ):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    nested = item.get("historico")
    if isinstance(nested, dict):
        return _time_value(nested)

    return ""


def _time_from_collection(items: list, module_name: str) -> str:
    target = str(module_name or "").strip().upper()

    for item in items or []:
        if not isinstance(item, dict):
            continue

        name = str(
            item.get("modulo")
            or item.get("nomeModulo")
            or item.get("label")
            or ""
        ).strip().upper()

        if name != target and target not in name:
            continue

        value = _time_value(item)
        if value:
            return value

    return ""


def _time_from_result(result: dict, module_name: str) -> str:
    if not isinstance(result, dict):
        return ""

    target = str(module_name or "").strip().upper()

    if target == "MENSAL":
        direct = result.get("horarioMensal") or result.get("horarioMensalISO")
    elif target == "EXTRAS":
        direct = result.get("horarioExtras") or result.get("horarioExtrasISO")
    else:
        direct = None

    if direct is not None and str(direct).strip():
        return str(direct).strip()

    for key in ("resultados", "modulos"):
        items = result.get(key)
        if isinstance(items, list):
            value = _time_from_collection(items, target)
            if value:
                return value

    return ""


def _update_center_now() -> tuple[str, str]:
    now = datetime.now(ZoneInfo("America/Recife"))
    return now.strftime("%d/%m/%Y %H:%M:%S"), now.isoformat()


def _module_name(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("modulo")
        or item.get("nomeModulo")
        or item.get("label")
        or ""
    ).strip().upper()


def _match_requested_module(name: str, requested: set[str]) -> str:
    current = str(name or "").strip().upper()
    if not current:
        return ""
    for target in requested:
        normalized = str(target or "").strip().upper()
        if normalized and (
            current == normalized
            or normalized in current
            or current in normalized
        ):
            return normalized
    return ""


def _stamp_requested_modules(
    result: dict,
    requested_times: dict[str, str],
) -> None:
    if not isinstance(result, dict) or not requested_times:
        return

    requested = set(requested_times)
    for key in ("resultados", "modulos"):
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            target = _match_requested_module(_module_name(row), requested)
            if target:
                row["atualizadoEm"] = requested_times[target]


def _update_center_cache_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("America/Recife"))
        return parsed.strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError):
        return text


def _update_center_snapshot_modules(profile: dict) -> list[tuple[str, str]]:
    role = str(profile.get("tipo") or "").strip().upper()
    perms = profile.get("permissoes") if isinstance(profile.get("permissoes"), dict) else {}
    broad = role in {"ADMINISTRADOR", "ADMIN"} or perms.get("CENTRO_ATUALIZACOES") is True
    modules: list[tuple[str, str]] = []
    if broad or perms.get("MENSAL_BASE_ATUALIZADA") is True:
        modules.append(("MENSAL", "Campanhas Mensais"))
    if broad or perms.get("EXTRAS_BASE_ATUALIZADA") is True:
        modules.append(("EXTRAS", "Campanhas Extras"))
    return modules


async def _update_center_snapshot_status(profile: dict) -> dict:
    # STATUS é leitura idempotente. Se a ponte legada ainda estiver preparando
    # a sessão, a Central pode abrir usando os snapshots PostgreSQL já válidos.
    rows: list[dict] = []
    for module, label in _update_center_snapshot_modules(profile):
        try:
            _payload, cache_row = await cache_read(modulo=module, settings=settings)
            rows.append({
                "modulo": module,
                "label": label,
                "disponivel": True,
                "atualizadoEm": _update_center_cache_time(cache_row.get("atualizado_em")),
                "atualizado_por": str(cache_row.get("atualizado_por") or ""),
                "usuario": str(cache_row.get("atualizado_por") or ""),
                "nome": str(cache_row.get("nome") or ""),
            })
        except CacheReadError:
            rows.append({
                "modulo": module,
                "label": label,
                "disponivel": False,
                "atualizadoEm": "",
                "atualizado_por": "",
                "usuario": "",
                "nome": "",
            })

    return {
        "sucesso": True,
        "ok": True,
        "modulos": rows,
        "transporte": "FASTAPI_POSTGRES_STATUS_FALLBACK",
    }


async def _resolve_update_center_legacy_token(
    session_key: str,
    payload: dict,
) -> str:
    # PROD5.9.8.22 — o token que o próprio navegador já possui continua sendo
    # o fallback imediato; sem ele, aguardamos brevemente o mesmo login legado
    # em andamento. A escrita OPCACHE_ATUALIZAR nunca é repetida.
    state = await get_state(session_key)
    token = (
        str(state.get("token") or "").strip()
        if state.get("status") == "READY"
        else ""
    )
    if token:
        return token

    browser_token = str(payload.get("token") or "").strip()
    if browser_token:
        return browser_token

    for _ in range(12):
        if str(state.get("status") or "").upper() == "ERROR":
            break
        await asyncio.sleep(0.2)
        state = await get_state(session_key)
        if state.get("status") == "READY":
            token = str(state.get("token") or "").strip()
            if token:
                return token

    return ""


# Substitui somente as rotas de apresentação/health; o restante continua vindo
# integralmente do app PROD3 já homologado.
_remove_routes("/", "/portal-v2-homolog.html", "/health")
app.version = BUILD


@app.get("/", include_in_schema=False)
async def prod4_portal():
    return _portal_response()


@app.get("/portal-v2-homolog.html", include_in_schema=False)
async def prod4_portal_alias():
    return _portal_response()


@app.get("/update-center-prod4.js", include_in_schema=False)
async def prod4_update_center_script():
    return FileResponse(
        PATCH_FILE,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/monthly-retention-prod44.js", include_in_schema=False)
async def prod44_monthly_retention_script():
    return FileResponse(
        RETENTION_PATCH_FILE,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/health")
async def prod4_health(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["X-DISMEPE-Build"] = BUILD
    missing = settings.validate_required_secrets()
    return {
        "ok": len(missing) == 0,
        "service": "dismepe-one-2-auth",
        "version": BUILD,
        "environment": settings.environment,
        "missingConfig": missing,
        "monthlyHistoryRetention": 2,
    }


@app.post("/admin/monthly-retention")
async def prod44_monthly_retention(
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

    if not _retention_delete_allowed(profile):
        raise HTTPException(
            status_code=403,
            detail="Você não possui permissão para limpar o Histórico Mensal.",
        )

    session_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
    legacy_state = await get_state(session_key)
    legacy_token = (
        str(legacy_state.get("token") or "").strip()
        if legacy_state.get("status") == "READY"
        else ""
    )
    if not legacy_token:
        raise HTTPException(
            status_code=409,
            detail="A sessão de compatibilidade ainda não está pronta.",
        )

    try:
        result = await purge_expired_monthly_history(
            legacy_token=legacy_token,
        )
    except MonthlyRetentionPurgeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result["transporte"] = "FASTAPI_RETENCAO_MENSAL_DIRECT"
    return result


@app.post("/admin/update-center")
async def prod4_update_center(
    request: Request,
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

    if not _allowed(profile):
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

    session_key = hashlib.sha256(session.encode("utf-8")).hexdigest()
    legacy_token = await _resolve_update_center_legacy_token(session_key, payload)
    if not legacy_token:
        if action == "OPCACHE_STATUS":
            return await _update_center_snapshot_status(profile)
        raise HTTPException(
            status_code=409,
            detail=(
                "A sessão de compatibilidade ainda está sendo preparada. "
                "Aguarde alguns segundos e tente novamente."
            ),
        )

    try:
        result = await call_update_center_legacy(
            action=action,
            payload=payload,
            legacy_token=legacy_token,
        )
    except UpdateCenterBridgeError as exc:
        if action == "OPCACHE_STATUS":
            return await _update_center_snapshot_status(profile)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Confirma a atualização com uma leitura STATUS. Nunca repete a escrita.
    # O horário da própria resposta da atualização tem prioridade; o STATUS
    # entra como confirmação/fallback.
    if action == "OPCACHE_ATUALIZAR" and (
        result.get("sucesso") is True
        or result.get("ok") is True
        or result.get("success") is True
    ):
        requested = (
            payload.get("acoes")
            if isinstance(payload.get("acoes"), list)
            else []
        )
        names = {
            str(item.get("modulo") or "").strip().upper()
            for item in requested
            if isinstance(item, dict)
        }
        immediate_times = {
            name: _time_from_result(result, name)
            for name in names
        }

        completed_display, completed_iso = _update_center_now()
        requested_times = {
            name: immediate_times.get(name) or completed_display
            for name in names
        }

        status = {}
        try:
            status = await call_update_center_legacy(
                action="OPCACHE_STATUS",
                payload={"acao": "OPCACHE_STATUS"},
                legacy_token=legacy_token,
            )
            modules = (
                status.get("modulos")
                if isinstance(status.get("modulos"), list)
                else []
            )
            if modules:
                result["modulos"] = modules
        except UpdateCenterBridgeError:
            status = {}

        _stamp_requested_modules(result, requested_times)

        if "MENSAL" in names:
            result["horarioMensal"] = requested_times["MENSAL"]
            if not immediate_times.get("MENSAL"):
                result["horarioMensalISO"] = completed_iso

        if "EXTRAS" in names:
            result["horarioExtras"] = requested_times["EXTRAS"]
            if not immediate_times.get("EXTRAS"):
                result["horarioExtrasISO"] = completed_iso

    result["transporte"] = "FASTAPI_UPDATE_CENTER_DIRECT"
    return result
