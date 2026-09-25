"""Servidor isolado de homologação mensal; nenhum endpoint dispara publicação.

Não recebe credenciais de produção, não expõe linhas de colaboradores,
não abre conexão SQL e não executa o worker legado por requisição HTTP.
"""
from __future__ import annotations

import asyncio
import logging
import os

from .monthly_homologation_sql_probe import probe_sql_readonly
from .monthly_google_probe import probe_google_sources
from .monthly_commercial_readonly import compare_live_commercial
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="DISMEPE ONE | Homologação mensal",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.on_event("startup")
async def _verify_sql_readonly() -> None:
    app.state.sql_readonly_validated = False
    app.state.google_readonly_validated = False
    app.state.commercial_readonly_validated = False
    if os.getenv("DISMEPE_MONTHLY_HOMOLOGATION") != "1":
        return
    try:
        app.state.sql_readonly_validated = await asyncio.to_thread(probe_sql_readonly)
        logging.getLogger("uvicorn.error").info(
            "MONTHLY_HOMOLOG_SQL_PROBE=%s",
            "OK" if app.state.sql_readonly_validated else "NOT_VALIDATED",
        )
    except Exception as exc:
        # Registra apenas o tipo da falha; nunca mensagem, hostname ou credenciais.
        logging.getLogger("uvicorn.error").warning(
            "MONTHLY_HOMOLOG_SQL_PROBE=NOT_VALIDATED error_type=%s",
            type(exc).__name__,
        )
        app.state.sql_readonly_validated = False

    if app.state.sql_readonly_validated:
        try:
            app.state.google_readonly_validated = await asyncio.to_thread(probe_google_sources)
            logging.getLogger("uvicorn.error").info(
                "MONTHLY_HOMOLOG_GOOGLE_PROBE=%s",
                "OK" if app.state.google_readonly_validated else "NOT_CONFIGURED",
            )
        except Exception as exc:
            logging.getLogger("uvicorn.error").warning(
                "MONTHLY_HOMOLOG_GOOGLE_PROBE=NOT_VALIDATED error_type=%s",
                type(exc).__name__,
            )

    if app.state.sql_readonly_validated and app.state.google_readonly_validated:
        try:
            commercial = await asyncio.to_thread(compare_live_commercial)
            app.state.commercial_readonly_validated = True
            logging.getLogger("uvicorn.error").info(
                "MONTHLY_HOMOLOG_COMERCIAL=OK competencia=%s vendedores=%s televendas=%s divergencias_vendedores=%s divergencias_televendas=%s",
                commercial["competencia"],
                commercial["vendedores"]["fonte"],
                commercial["televendas"]["fonte"],
                commercial["vendedores"]["numerosDivergentes"],
                commercial["televendas"]["numerosDivergentes"],
            )
        except Exception as exc:
            app.state.commercial_readonly_validated = False
            logging.getLogger("uvicorn.error").warning(
                "MONTHLY_HOMOLOG_COMERCIAL=NOT_VALIDATED error_type=%s",
                type(exc).__name__,
            )


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "ambiente": "HOMOLOGACAO_MENSAL",
        "modo": "SOMENTE_LEITURA",
        "publicacaoAutorizada": False,
    }


@app.get("/status", include_in_schema=False)
async def status() -> JSONResponse:
    enabled = os.getenv("DISMEPE_MONTHLY_HOMOLOGATION") == "1"
    return JSONResponse(
        status_code=200 if enabled else 503,
        content={
            "homologacaoAtiva": enabled,
            "calculoEmProdução": False,
            "publicacaoAutorizada": False,
            "sqlLeituraValidada": bool(getattr(app.state, "sql_readonly_validated", False)),
            "googleContaExclusivaConfirmada": bool(getattr(app.state, "google_readonly_validated", False)),
            "integracaoComFontes": "LEITURA_CONFIRMADA" if getattr(app.state, "google_readonly_validated", False) else "PENDENTE_DE_CREDENCIAIS_GOOGLE_EXCLUSIVAS",
            "leituraComercialValidada": bool(getattr(app.state, "commercial_readonly_validated", False)),
            "paridadeFinanceira": "NAO_VALIDADA",
        },
        headers={"Cache-Control": "no-store"},
    )
