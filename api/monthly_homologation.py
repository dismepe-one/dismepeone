"""Servidor isolado de homologação mensal; nenhum endpoint dispara publicação.

Não recebe credenciais de produção, não expõe linhas de colaboradores,
não abre conexão SQL e não executa o worker legado por requisição HTTP.
"""
from __future__ import annotations

import asyncio
import os

from .monthly_homologation_sql_probe import probe_sql_readonly
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
    if os.getenv("DISMEPE_MONTHLY_HOMOLOGATION") != "1":
        return
    try:
        app.state.sql_readonly_validated = await asyncio.to_thread(probe_sql_readonly)
    except Exception:
        # Não registrar credenciais, mensagens SQL ou endereços no Render.
        app.state.sql_readonly_validated = False


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
            "googleContaExclusivaConfirmada": False,
            "integracaoComFontes": "PENDENTE_DE_CREDENCIAIS_GOOGLE_EXCLUSIVAS",
            "paridadeFinanceira": "NAO_VALIDADA",
        },
        headers={"Cache-Control": "no-store"},
    )
