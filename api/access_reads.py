from __future__ import annotations

import copy
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .config import Settings
from .security import normalizar


class AccessReadError(Exception):
    pass


def _role(value: Any) -> str:
    return normalizar(value or "")


def _can_access(profile: dict[str, Any]) -> bool:
    if _role(profile.get("tipo")) == "ADMINISTRADOR":
        return True
    perms = profile.get("permissoes")
    return (
        isinstance(perms, dict)
        and perms.get("CONTROLE_DE_ACESSOS") is True
    )


async def admin_edge(
    *,
    action: str,
    data: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    endpoint = (
        settings.supabase_url.rstrip("/")
        + "/functions/v1/dismepe-admin"
    )

    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }

    payload = {
        "acao": str(action or "").strip().upper(),
        **(data or {}),
    }

    try:
        async with httpx.AsyncClient(
            timeout=max(8.0, settings.request_timeout_seconds)
        ) as client:
            response = await client.post(
                endpoint,
                json=payload,
                headers=headers,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise AccessReadError(
            "O histórico de acessos não respondeu dentro do tempo esperado."
        ) from exc

    try:
        result = response.json()
    except ValueError as exc:
        raise AccessReadError(
            f"Resposta inválida do histórico de acessos (HTTP {response.status_code})."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise AccessReadError(
            str(result.get("erro") or f"HTTP {response.status_code}")
        )

    if result.get("sucesso") is not True:
        raise AccessReadError(
            str(result.get("erro") or "Não foi possível consultar os acessos.")
        )

    return result


def _normalize_access(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    usuario = str(item.get("usuario") or "").strip()
    if not usuario:
        return None

    raw_date = item.get("data_hora") or item.get("data") or ""
    iso = None
    if raw_date:
        try:
            dt = datetime.fromisoformat(
                str(raw_date).replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("America/Recife"))
            iso = dt.astimezone(ZoneInfo("UTC")).isoformat()
        except Exception:
            iso = None

    return {
        "data": iso,
        "usuario": usuario,
        "setor": str(item.get("setor") or "").strip().upper(),
        "acao": str(item.get("acao") or "LOGIN").strip() or "LOGIN",
    }


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=ZoneInfo("UTC"))
        return d.astimezone(ZoneInfo("America/Recife"))
    except Exception:
        return None


def build_access_panel(
    accesses_raw: list[Any],
) -> dict[str, Any]:
    tz = ZoneInfo("America/Recife")
    now = datetime.now(tz)

    accesses = []
    for item in accesses_raw if isinstance(accesses_raw, list) else []:
        row = _normalize_access(item)
        if row:
            accesses.append(row)

    accesses.sort(
        key=lambda x: _dt(x.get("data")) or datetime.min.replace(tzinfo=tz),
        reverse=True,
    )

    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_7 = start_today - timedelta(days=6)
    start_30 = start_today - timedelta(days=29)

    users_today: set[str] = set()
    by_user: dict[str, dict[str, Any]] = {}
    sector_count: dict[str, int] = defaultdict(int)
    day_count: dict[str, int] = defaultdict(int)

    for item in accesses:
        if str(item.get("acao") or "").upper() != "LOGIN":
            continue

        d = _dt(item.get("data"))
        if not d:
            continue

        user_key = normalizar(item.get("usuario") or "")
        sector = str(item.get("setor") or "NÃO INFORMADO").strip() or "NÃO INFORMADO"

        if d >= start_today:
            users_today.add(user_key)

        sector_count[sector] += 1

        if d >= start_30:
            day_count[d.strftime("%Y-%m-%d")] += 1

        if user_key not in by_user:
            by_user[user_key] = {
                "usuario": item.get("usuario") or "",
                "setor": sector,
                "total": 0,
                "hoje": 0,
                "seteDias": 0,
                "ultimoLogin": item.get("data"),
            }

        u = by_user[user_key]
        u["total"] += 1
        if d >= start_today:
            u["hoje"] += 1
        if d >= start_7:
            u["seteDias"] += 1

        current_last = _dt(u.get("ultimoLogin"))
        if not current_last or d > current_last:
            u["ultimoLogin"] = item.get("data")

    detailed = []
    for u in by_user.values():
        last = _dt(u.get("ultimoLogin"))
        status = "INATIVO"
        if last:
            days = max(0, (now.date() - last.date()).days)
            if days <= 2:
                status = "ATIVO"
            elif days <= 7:
                status = "POUCO ATIVO"

        detailed.append({
            **u,
            "status": status,
        })

    detailed.sort(
        key=lambda x: _dt(x.get("ultimoLogin"))
        or datetime.min.replace(tzinfo=tz),
        reverse=True,
    )

    no_recent = sorted(
        [u for u in detailed if u.get("status") != "ATIVO"],
        key=lambda x: _dt(x.get("ultimoLogin"))
        or datetime.min.replace(tzinfo=tz),
    )

    ranking = sorted(
        copy.deepcopy(detailed),
        key=lambda x: int(x.get("total") or 0),
        reverse=True,
    )[:10]

    days_30 = []
    for offset in range(29, -1, -1):
        d = start_today - timedelta(days=offset)
        key = d.strftime("%Y-%m-%d")
        days_30.append({
            "data": key,
            "acessos": int(day_count.get(key, 0)),
        })

    total_today = 0
    total_7 = 0
    for item in accesses:
        if str(item.get("acao") or "").upper() != "LOGIN":
            continue
        d = _dt(item.get("data"))
        if not d:
            continue
        if d >= start_today:
            total_today += 1
        if d >= start_7:
            total_7 += 1

    users_simple = [
        {
            "usuario": u.get("usuario"),
            "setor": u.get("setor"),
            "ultimoLogin": u.get("ultimoLogin"),
            "totalLogins": u.get("total"),
        }
        for u in detailed
    ]

    return {
        "acessos": accesses,
        "usuarios": users_simple,
        "usuariosDetalhados": detailed,
        "semAcessoRecente": no_recent,
        "ranking": ranking,
        "acessosPorSetor": dict(sector_count),
        "acessosPorDia": days_30,
        "resumo": {
            "totalAcessos": len(accesses),
            "totalHoje": total_today,
            "total7Dias": total_7,
            "usuariosCadastrados": len(detailed),
            "usuariosHoje": len(users_today),
            "ultimoLogin": accesses[0] if accesses else None,
        },
    }


async def list_accesses(
    *,
    profile: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    if not _can_access(profile):
        raise PermissionError(
            "Você não possui permissão para visualizar os acessos."
        )

    result = await admin_edge(
        action="LOG_LIST",
        data={"limite": 10000},
        settings=settings,
    )

    panel = build_access_panel(
        result.get("acessos")
        if isinstance(result.get("acessos"), list)
        else []
    )

    return {
        "sucesso": True,
        "origem": "SUPABASE",
        "transporte": "FASTAPI_LOG_SQL",
        **panel,
    }


async def access_user(
    *,
    profile: dict[str, Any],
    usuario: str,
    settings: Settings,
) -> dict[str, Any]:
    if not _can_access(profile):
        raise PermissionError(
            "Você não possui permissão para visualizar os acessos."
        )

    login = str(usuario or "").strip()
    if not login:
        raise ValueError("Informe o usuário.")

    result = await admin_edge(
        action="LOG_USER",
        data={
            "usuario": login,
            "limite": 5000,
        },
        settings=settings,
    )

    accesses = []
    wanted = normalizar(login)

    for item in result.get("acessos") if isinstance(result.get("acessos"), list) else []:
        row = _normalize_access(item)
        if not row:
            continue
        if normalizar(row.get("usuario") or "") != wanted:
            continue
        accesses.append(row)

    accesses.sort(
        key=lambda x: _dt(x.get("data"))
        or datetime.min.replace(tzinfo=ZoneInfo("America/Recife")),
        reverse=True,
    )

    return {
        "sucesso": True,
        "usuario": login,
        "acessos": accesses,
        "origem": "SUPABASE",
        "transporte": "FASTAPI_LOG_SQL",
    }
