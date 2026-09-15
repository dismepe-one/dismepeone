from __future__ import annotations

import hashlib
from pathlib import Path

import jwt
from fastapi import Cookie, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from .main import app, settings
from .security import decode_session_token
from .legacy_bridge import get_state
from .update_center import UpdateCenterBridgeError, call_update_center_legacy


BUILD = "2.0.0-phase2i2-prod4.2"
ROOT = Path(__file__).resolve().parents[1]
PORTAL_FILE = ROOT / "frontend" / "portal-v2-homolog.html"
PATCH_FILE = ROOT / "frontend" / "update-center-prod4.js"


def _remove_routes(*paths: str) -> None:
    wanted = set(paths)
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", None) not in wanted
    ]


def _portal_response() -> HTMLResponse:
    html = PORTAL_FILE.read_text(encoding="utf-8")
    tag = f'<script src="/update-center-prod4.js?v={BUILD}"></script>'
    if tag not in html:
        marker = "</body>"
        pos = html.lower().rfind(marker)
        if pos < 0:
            raise RuntimeError("Fechamento </body> não encontrado no portal.")
        html = html[:pos] + tag + "\n" + html[pos:]
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


def _time_from_status(modules: list, module_name: str) -> str:
    target = str(module_name or "").strip().upper()
    for item in modules or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("modulo") or "").strip().upper() != target:
            continue
        return str(item.get("atualizadoEm") or item.get("atualizado_em") or "").strip()
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
    }


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
    legacy_state = await get_state(session_key)
    legacy_token = (
        str(legacy_state.get("token") or "").strip()
        if legacy_state.get("status") == "READY"
        else ""
    )
    if not legacy_token:
        legacy_token = str(payload.get("token") or "").strip()

    try:
        result = await call_update_center_legacy(
            action=action,
            payload=payload,
            legacy_token=legacy_token,
        )
    except UpdateCenterBridgeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Confirma a atualização com uma leitura STATUS. Nunca repete a escrita.
    if action == "OPCACHE_ATUALIZAR" and (
        result.get("sucesso") is True
        or result.get("ok") is True
        or result.get("success") is True
    ):
        try:
            status = await call_update_center_legacy(
                action="OPCACHE_STATUS",
                payload={"acao": "OPCACHE_STATUS"},
                legacy_token=legacy_token,
            )
            modules = status.get("modulos") if isinstance(status.get("modulos"), list) else []
            if modules:
                result["modulos"] = modules
            requested = payload.get("acoes") if isinstance(payload.get("acoes"), list) else []
            names = {
                str(item.get("modulo") or "").strip().upper()
                for item in requested if isinstance(item, dict)
            }
            if "MENSAL" in names:
                value = _time_from_status(modules, "MENSAL")
                if value:
                    result["horarioMensal"] = value
            if "EXTRAS" in names:
                value = _time_from_status(modules, "EXTRAS")
                if value:
                    result["horarioExtras"] = value
        except UpdateCenterBridgeError:
            pass

    result["transporte"] = "FASTAPI_UPDATE_CENTER_DIRECT"
    return result
