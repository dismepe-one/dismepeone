from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from .cache_reads import CacheReadError, cache_get
from .config import get_settings


settings = get_settings()
_INSTALLED = False


def _matches(item: dict[str, Any], view: str) -> bool:
    if view == "critical":
        return bool(item.get("critico"))
    if view == "rupture":
        return bool(item.get("riscoRuptura"))
    if view == "low":
        return bool(item.get("baixo"))
    if view == "high":
        return bool(item.get("alta"))
    if view == "dde":
        return float(item.get("estoque") or 0) > 0
    if view == "noTurn":
        return bool(item.get("semGiro"))
    return False


def install_commercial_intelligence_safe_loading(app: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .commercial_intelligence_promotions import install_commercial_intelligence_promotions
    from .commercial_intelligence_complement import (
        install_commercial_intelligence_complement,
        merge_complement_for_session,
    )

    install_commercial_intelligence_promotions(app)
    install_commercial_intelligence_complement(app)

    @app.middleware("http")
    async def commercial_intelligence_safe_loading(request: Request, call_next):
        path = request.url.path

        if path in {
            "/data/inteligencia-comercial/export.xlsx",
            "/data/inteligencia-comercial/export.pdf",
        }:
            tab = str(request.query_params.get("aba") or "overview").strip()
            if tab == "overview":
                return JSONResponse(
                    {
                        "detail": (
                            "Na Visão geral a exportação de produtos é bloqueada para proteger o desempenho. "
                            "Selecione uma visão específica antes de exportar."
                        )
                    },
                    status_code=400,
                    headers={"Cache-Control": "no-store"},
                )
            return await call_next(request)

        if path != "/data/inteligencia-comercial":
            return await call_next(request)

        from . import commercial_intelligence as ci

        session = request.cookies.get(settings.cookie_name)
        try:
            ci._profile(session)
        except Exception as exc:
            status = int(getattr(exc, "status_code", 401) or 401)
            detail = getattr(exc, "detail", "Sessão inválida.")
            return JSONResponse({"detail": detail}, status_code=status)

        view = str(request.query_params.get("visao") or "overview").strip()
        allowed = {"overview", "critical", "rupture", "low", "high", "dde", "noTurn", "suppliers"}
        if view not in allowed:
            view = "overview"

        try:
            payload, row = await cache_get(modulo="MAPA_ESTOQUE", settings=settings)
            payload, complement_meta = await merge_complement_for_session(payload, session)
        except CacheReadError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)
        except Exception as exc:
            status = int(getattr(exc, "status_code", 503) or 503)
            detail = getattr(exc, "detail", "Falha ao aplicar o mapa complementar.")
            return JSONResponse({"detail": detail}, status_code=status)

        result = ci._analyze(payload, row)
        result["complementoTemporario"] = complement_meta
        products = [item for item in (result.get("produtos") or []) if isinstance(item, dict)]
        total_base = int((result.get("resumo") or {}).get("produtos") or len(products))
        curves = sorted({
            str(item.get("curva") or "").strip()
            for item in products
            if str(item.get("curva") or "").strip()
        })

        if view == "suppliers":
            result["produtos"] = []
            result["listagemProdutos"] = False
            result["visao"] = view
            result["totalProdutosBase"] = total_base
            result["curvasDisponiveis"] = curves
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        if view == "overview":
            result["produtos"] = products
            result["listagemProdutos"] = True
            result["visao"] = view
            result["totalProdutosBase"] = total_base
            result["totalProdutosVisao"] = len(products)
            result["curvasDisponiveis"] = curves
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        filtered = [item for item in products if _matches(item, view)]
        result["produtos"] = filtered
        result["listagemProdutos"] = True
        result["visao"] = view
        result["totalProdutosBase"] = total_base
        result["totalProdutosVisao"] = len(filtered)
        result["curvasDisponiveis"] = curves
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
