from __future__ import annotations

from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse

from . import main as main_module
from . import prod4_app
from .prod4_app import app, settings
from .security import decode_session_token
from .industries import (
    is_industry_profile,
    router as industries_router,
    scope_industry_bootstrap,
)
from .industries_stock_sync import start_stock_sync, stop_stock_sync, stock_sync_public_status


BUILD = "2.0.0-phase2i2-prod5.9.4-publicado"
ROOT = Path(__file__).resolve().parents[1]
PORTAL_FILE = ROOT / "frontend" / "portal-v2-homolog.html"
ROUTER_SCRIPT = ROOT / "frontend" / "industries-router.js"
ADMIN_SCRIPT = ROOT / "frontend" / "industries-admin.js"

# PROD4.4 já substituiu scope_mensal_dashboard. Guardamos essa versão e
# aplicamos um escopo adicional somente quando o perfil for INDÚSTRIA.
_ORIGINAL_SCOPE = main_module.scope_mensal_dashboard


def _scope_with_industry(payload: dict, profile: dict, competencia: str | None = None):
    if is_industry_profile(profile):
        return scope_industry_bootstrap(payload, profile, competencia=competencia)
    return _ORIGINAL_SCOPE(payload, profile, competencia=competencia)


main_module.scope_mensal_dashboard = _scope_with_industry
app.include_router(industries_router)
app.version = BUILD


@app.on_event("startup")
async def industries_stock_sync_startup():
    await start_stock_sync()


@app.on_event("shutdown")
async def industries_stock_sync_shutdown():
    await stop_stock_sync()


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
        f'<script src="/industries-router.js?v={BUILD}"></script>',
        f'<script src="/industries-admin.js?v={BUILD}"></script>',
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


def _profile_from_cookie(request: Request) -> dict | None:
    session = request.cookies.get(settings.cookie_name)
    if not session:
        return None
    try:
        return decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except Exception:
        return None


@app.middleware("http")
async def industries_route_guard(request: Request, call_next):
    # Idempotente: também garante o monitor do Drive em aplicações que usem
    # um lifespan próprio e não executem handlers legados de startup.
    await start_stock_sync()
    profile = _profile_from_cookie(request)
    if profile and is_industry_profile(profile):
        path = request.url.path
        if path in {"/", "/portal-v2-homolog.html"}:
            return RedirectResponse(url="/industrias", status_code=303)
        allowed = (
            path.startswith("/industrias")
            or path in {"/auth/me", "/auth/logout", "/health"}
        )
        if not allowed:
            return JSONResponse(
                status_code=403,
                content={"detail": "Este usuário possui acesso somente ao DISMEPE ONE INDÚSTRIAS."},
            )
    return await call_next(request)


# Substitui somente apresentação/health da camada anterior.
_remove_routes("/", "/portal-v2-homolog.html", "/health")


@app.get("/", include_in_schema=False)
async def industries_root(request: Request):
    profile = _profile_from_cookie(request)
    if profile and is_industry_profile(profile):
        return RedirectResponse(url="/industrias", status_code=303)
    return _portal_response()


@app.get("/portal-v2-homolog.html", include_in_schema=False)
async def industries_root_alias(request: Request):
    profile = _profile_from_cookie(request)
    if profile and is_industry_profile(profile):
        return RedirectResponse(url="/industrias", status_code=303)
    return _portal_response()


@app.get("/industries-router.js", include_in_schema=False)
async def industries_router_script():
    return FileResponse(
        ROUTER_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/industries-admin.js", include_in_schema=False)
async def industries_admin_script():
    return FileResponse(
        ADMIN_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/health")
async def industries_health(response: Response):
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
        "industriesPortal": True,
        "industriesStockDriveSync": stock_sync_public_status(),
    }
