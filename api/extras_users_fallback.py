from __future__ import annotations

import inspect
from typing import Any

from fastapi import HTTPException
from fastapi.routing import APIRoute


def _route_for(app: Any, path: str, method: str) -> APIRoute | None:
    wanted = method.upper()
    for route in list(app.router.routes):
        if isinstance(route, APIRoute) and route.path == path and wanted in route.methods:
            return route
    return None


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _name_from_row(row: dict[str, Any]) -> str:
    return str(
        row.get("__COLABORADOR")
        or row.get("Colaborador")
        or row.get("colab")
        or row.get("Vendedor")
        or row.get("VENDEDOR")
        or row.get("Televendas")
        or row.get("TELEVENDA")
        or row.get("vendedor")
        or row.get("televendas")
        or ""
    ).strip()


def _monthly_users(payload: dict[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()

    sources = (
        ("dadosVendedores", "VENDEDOR"),
        ("dadosTelevendas", "TELEVENDAS"),
    )
    for key, user_type in sources:
        rows = payload.get(key) if isinstance(payload.get(key), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = _name_from_row(row)
            normalized = " ".join(name.upper().split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(
                {
                    "usuario": "",
                    "nome": name,
                    "vendedor": name,
                    "tipo": user_type,
                    "setor": user_type,
                }
            )

    output.sort(
        key=lambda item: (
            str(item.get("tipo") or ""),
            str(item.get("vendedor") or "").upper(),
        )
    )
    return output


def install_extras_users_fallback(app: Any) -> None:
    if getattr(app.state, "extras_users_fallback_installed", False):
        return
    app.state.extras_users_fallback_installed = True

    from . import main as main_module

    route = _route_for(app, "/data/extras-users", "GET")
    if route is None:
        return

    original = route.endpoint

    async def extras_users_with_monthly_fallback(session: str | None = None):
        try:
            result = await _await_if_needed(original(session=session))
            if (
                isinstance(result, dict)
                and isinstance(result.get("usuarios"), list)
                and result.get("usuarios")
            ):
                return result
        except HTTPException as exc:
            if exc.status_code != 503:
                raise

        # A rota original já validou autenticação/permissão antes de tentar
        # ler o snapshot USUARIOS. Em instalações onde esse snapshot não existe,
        # usamos a fonte mensal, que já contém Vendedores e Televendas ativos.
        try:
            payload, row = await main_module.cache_get(
                modulo="MENSAL",
                settings=main_module.settings,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Lista de colaboradores indisponível no momento.",
            ) from exc

        users = _monthly_users(payload if isinstance(payload, dict) else {})
        if not users:
            raise HTTPException(
                status_code=503,
                detail="Nenhum colaborador encontrado na base mensal.",
            )

        return {
            "sucesso": True,
            "usuarios": users,
            "quantidade": len(users),
            "transporte": "FASTAPI_MENSAL_COLABORADORES_FALLBACK",
            "atualizadoEm": str(row.get("atualizado_em") or ""),
            "snapshotVersao": str(row.get("versao") or ""),
        }

    route.endpoint = extras_users_with_monthly_fallback
    route.dependant.call = extras_users_with_monthly_fallback
    main_module.extras_users_snapshot = extras_users_with_monthly_fallback
