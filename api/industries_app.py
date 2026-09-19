from __future__ import annotations

from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse

from . import main as main_module
from . import prod4_app
from . import industries as industries_module
from .prod4_app import app, settings
from .security import decode_session_token
from .industries import (
    is_industry_profile,
    is_buyer_profile,
    router as industries_router,
    scope_industry_bootstrap,
)
from .industries_stock_sync import start_stock_sync, stop_stock_sync, stock_sync_public_status
from .industries_sales_sync import start_general_sales_sync, stop_general_sales_sync, general_sales_sync_public_status
from .monthly_business_days import (
    enrich_monthly_payload,
    router as monthly_business_days_router,
)
from .herbamed_auto_metrics import enrich_herbamed_monthly_payload


BUILD = "2.0.0-phase2i2-prod5.9.4-publicado"
ROOT = Path(__file__).resolve().parents[1]
PORTAL_FILE = ROOT / "frontend" / "portal-v2-homolog.html"
ROUTER_SCRIPT = ROOT / "frontend" / "industries-router.js"
ADMIN_SCRIPT = ROOT / "frontend" / "industries-admin.js"
BUSINESS_DAYS_SCRIPT = ROOT / "frontend" / "monthly-business-days-prod59822.js"
HERBAMED_AUTO_SCRIPT = ROOT / "frontend" / "herbamed-auto-metrics-prod59822.js"

# PROD4.4 já substituiu scope_mensal_dashboard. Guardamos essa versão e
# aplicamos um escopo adicional somente quando o perfil for INDÚSTRIA.
_ORIGINAL_SCOPE = main_module.scope_mensal_dashboard
_ORIGINAL_CACHE_GET = main_module.cache_get


def _scope_with_industry(payload: dict, profile: dict, competencia: str | None = None):
    if is_industry_profile(profile) or is_buyer_profile(profile):
        return scope_industry_bootstrap(payload, profile, competencia=competencia)
    return _ORIGINAL_SCOPE(payload, profile, competencia=competencia)


async def _cache_get_with_automatic_business_days(*, modulo: str, settings):
    payload, row = await _ORIGINAL_CACHE_GET(modulo=modulo, settings=settings)
    if str(modulo or "").strip().upper() == "MENSAL":
        payload = await enrich_monthly_payload(payload)
        payload = await enrich_herbamed_monthly_payload(payload)
    return payload, row


main_module.scope_mensal_dashboard = _scope_with_industry
main_module.cache_get = _cache_get_with_automatic_business_days
industries_module.cache_get = _cache_get_with_automatic_business_days
app.include_router(industries_router)
app.include_router(monthly_business_days_router)
app.version = BUILD


@app.on_event("startup")
async def industries_stock_sync_startup():
    await start_stock_sync()
    await start_general_sales_sync()


@app.on_event("shutdown")
async def industries_stock_sync_shutdown():
    await stop_general_sales_sync()
    await stop_stock_sync()


def _remove_routes(*paths: str) -> None:
    wanted = set(paths)
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", None) not in wanted
    ]


def _portal_response(*, authenticated: bool = False) -> HTMLResponse:
    html = PORTAL_FILE.read_text(encoding="utf-8")
    tags = [
        f'<script src="/update-center-prod4.js?v={BUILD}"></script>',
        f'<script src="/monthly-retention-prod44.js?v={BUILD}"></script>',
        f'<script src="/industries-router.js?v={BUILD}"></script>',
        f'<script src="/industries-admin.js?v={BUILD}"></script>',
        f'<script src="/monthly-business-days-prod59822.js?v={BUILD}"></script>',
        f'<script src="/herbamed-auto-metrics-prod59822.js?v={BUILD}"></script>',
        f'<script src="/positivacao-launcher.js?v={BUILD}"></script>',
    ]
    missing = [tag for tag in tags if tag not in html]
    if missing:
        marker = "</body>"
        pos = html.lower().rfind(marker)
        if pos < 0:
            raise RuntimeError("Fechamento </body> não encontrado no portal.")
        html = html[:pos] + "\n".join(missing) + "\n" + html[pos:]

    # PROD5.9.8.17: no F5, se o cookie 2.0 já foi validado pelo servidor,
    # não pintamos a tela de login enquanto a Home é restaurada.
    if authenticated:
        guard = '\n<style id="prod59817-f5-auth-guard">\nhtml.prod59817-auth-refresh.v84-session-check body:not(.v51-auth-ready) #loginOverlay,\nhtml.prod59817-auth-refresh body:not(.v51-auth-ready) #loginOverlay,\nhtml.prod59817-auth-refresh #loginOverlay{\n  display:none !important;\n  visibility:hidden !important;\n  opacity:0 !important;\n  pointer-events:none !important;\n}\n</style>\n<script id="prod59817-f5-auth-guard-script">\n(function(){\n  const root=document.documentElement;\n  root.classList.add(\'prod59817-auth-refresh\');\n\n  function installRelease(){\n    const body=document.body;\n    if(!body){\n      root.classList.remove(\'prod59817-auth-refresh\');\n      return;\n    }\n\n    let observer=null;\n    const release=function(){\n      if(!body.classList.contains(\'v51-auth-ready\'))return;\n      root.classList.remove(\'prod59817-auth-refresh\');\n      if(observer)observer.disconnect();\n    };\n\n    observer=new MutationObserver(release);\n    observer.observe(body,{attributes:true,attributeFilter:[\'class\']});\n    release();\n\n    setTimeout(function(){\n      root.classList.remove(\'prod59817-auth-refresh\');\n      if(observer)observer.disconnect();\n    },15000);\n  }\n\n  if(document.readyState===\'loading\'){\n    document.addEventListener(\'DOMContentLoaded\',installRelease,{once:true});\n  }else{\n    installRelease();\n  }\n})();\n</script>\n'
        head_end = html.lower().find("</head>")
        if head_end < 0:
            raise RuntimeError("Fechamento </head> não encontrado no portal.")
        html = html[:head_end] + guard + "\n" + html[head_end:]

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
    await start_general_sales_sync()
    profile = _profile_from_cookie(request)
    if profile and (is_industry_profile(profile) or is_buyer_profile(profile)):
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
    if profile and (is_industry_profile(profile) or is_buyer_profile(profile)):
        return RedirectResponse(url="/industrias", status_code=303)
    return _portal_response(authenticated=bool(profile))


@app.get("/portal-v2-homolog.html", include_in_schema=False)
async def industries_root_alias(request: Request):
    profile = _profile_from_cookie(request)
    if profile and (is_industry_profile(profile) or is_buyer_profile(profile)):
        return RedirectResponse(url="/industrias", status_code=303)
    return _portal_response(authenticated=bool(profile))


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


@app.get("/monthly-business-days-prod59822.js", include_in_schema=False)
async def monthly_business_days_script():
    return FileResponse(
        BUSINESS_DAYS_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/herbamed-auto-metrics-prod59822.js", include_in_schema=False)
async def herbamed_auto_metrics_script():
    return FileResponse(
        HERBAMED_AUTO_SCRIPT,
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
        "industriesGeneralSalesDriveSync": general_sales_sync_public_status(),
    }
