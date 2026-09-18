from __future__ import annotations

import copy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .cache_reads import CacheReadError, cache_get
from .config import Settings
from .security import normalizar


class HistoryReadError(Exception):
    pass


def _role(value: Any) -> str:
    return normalizar(value or "")


def _perms(profile: dict[str, Any]) -> dict[str, Any]:
    value = profile.get("permissoes")
    return value if isinstance(value, dict) else {}


def _is_admin(profile: dict[str, Any]) -> bool:
    return _role(profile.get("tipo")) in {"ADMINISTRADOR", "ADMIN"}


def _can_view(kind: str, profile: dict[str, Any]) -> bool:
    if _is_admin(profile):
        return True
    p = _perms(profile)
    if kind == "mensal":
        return (
            p.get("HISTORICO_MENSAL_VISUALIZAR") is True
            or p.get("CADASTRO_CAMPANHAS_MENSAIS") is True
        )
    return (
        p.get("HISTORICO_EXTRAS_VISUALIZAR") is True
        or p.get("CAMPANHAS_EXTRAS") is True
    )


def _can_delete(kind: str, profile: dict[str, Any]) -> bool:
    if _is_admin(profile):
        return True

    p = _perms(profile)

    if kind == "mensal":
        # Espelha o comportamento histórico:
        # gestão mensal ou gestão de Extras também era considerada gerência.
        return (
            p.get("HISTORICO_MENSAL_EXCLUIR") is True
            or p.get("CADASTRO_CAMPANHAS_MENSAIS") is True
            or any(
                p.get(k) is True
                for k in (
                    "CAMPANHAS_EXTRAS_CRIAR",
                    "CAMPANHAS_EXTRAS_EDITAR",
                    "CAMPANHAS_EXTRAS_ATIVAR_OCULTAR",
                    "CAMPANHAS_EXTRAS_EXCLUIR",
                    "CAMPANHAS_EXTRAS_OBSERVACAO",
                )
            )
        )

    return (
        p.get("HISTORICO_EXTRAS_EXCLUIR") is True
        or any(
            p.get(k) is True
            for k in (
                "CAMPANHAS_EXTRAS_CRIAR",
                "CAMPANHAS_EXTRAS_EDITAR",
                "CAMPANHAS_EXTRAS_ATIVAR_OCULTAR",
                "CAMPANHAS_EXTRAS_EXCLUIR",
                "CAMPANHAS_EXTRAS_OBSERVACAO",
            )
        )
    )


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date_key(item: dict[str, Any]) -> float:
    raw = str(
        item.get("dataHoraISO")
        or item.get("dataHoraFormatado")
        or ""
    ).strip()

    if not raw:
        return 0.0

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("America/Recife"))
        return dt.timestamp()
    except Exception:
        pass

    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(
                tzinfo=ZoneInfo("America/Recife")
            ).timestamp()
        except Exception:
            pass

    return 0.0


def _monthly_public(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    ident = str(item.get("idAtualizacao") or "").strip()
    if not ident:
        return None

    return {
        "idAtualizacao": ident,
        "competencia": str(item.get("competencia") or ""),
        "origem": str(item.get("origem") or ""),
        "dataHoraISO": str(item.get("dataHoraISO") or ""),
        "dataHoraFormatado": str(item.get("dataHoraFormatado") or ""),
        "usuario": str(item.get("usuario") or ""),
        "registrosVendedores": _num(item.get("registrosVendedores")),
        "registrosTelevendas": _num(item.get("registrosTelevendas")),
        "objetivoVendedores": _num(item.get("objetivoVendedores")),
        "vendaVendedores": _num(item.get("vendaVendedores")),
        "objetivoTelevendas": _num(item.get("objetivoTelevendas")),
        "vendaTelevendas": _num(item.get("vendaTelevendas")),
    }


def _extras_public(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    ident = str(item.get("idAtualizacao") or "").strip()
    if not ident:
        return None

    resumo = item.get("resumo") if isinstance(item.get("resumo"), dict) else {}
    totais = item.get("totais") if isinstance(item.get("totais"), dict) else {}
    campanhas_raw = item.get("campanhas")
    registros_raw = item.get("registros")

    return {
        "idAtualizacao": ident,
        "competencia": str(item.get("competencia") or ""),
        "origem": str(item.get("origem") or "CAMPANHAS EXTRAS"),
        "dataHoraISO": str(item.get("dataHoraISO") or ""),
        "dataHoraFormatado": str(item.get("dataHoraFormatado") or ""),
        "usuario": str(item.get("usuario") or ""),
        "campanhas": _num(
            resumo.get("campanhas")
            if resumo.get("campanhas") is not None
            else (len(campanhas_raw) if isinstance(campanhas_raw, list) else 0)
        ),
        "registros": _num(
            resumo.get("registros")
            if resumo.get("registros") is not None
            else (len(registros_raw) if isinstance(registros_raw, list) else 0)
        ),
        "venda": _num(
            resumo.get("venda")
            if resumo.get("venda") is not None
            else totais.get("venda")
        ),
        "participantes": _num(
            resumo.get("participantes")
            if resumo.get("participantes") is not None
            else totais.get("participantes")
        ),
        "premiados": _num(
            resumo.get("premiados")
            if resumo.get("premiados") is not None
            else totais.get("premiados")
        ),
        "premiacao": _num(
            resumo.get("premiacao")
            if resumo.get("premiacao") is not None
            else totais.get("premiacao")
        ),
    }


def _profile_identity(profile: dict[str, Any]) -> str:
    return normalizar(
        profile.get("vendedor")
        or profile.get("nome")
        or profile.get("usuario")
        or ""
    )


def _row_collaborator(row: dict[str, Any], channel: str) -> str:
    if channel == "TELEVENDAS":
        return normalizar(
            row.get("__COLABORADOR")
            or row.get("colab")
            or row.get("Televendas")
            or row.get("televendas")
            or ""
        )
    return normalizar(
        row.get("__COLABORADOR")
        or row.get("colab")
        or row.get("Vendedor")
        or row.get("vendedor")
        or ""
    )


def _scope_monthly_rows(
    rows: Any,
    *,
    profile: dict[str, Any],
    channel: str,
) -> list[dict[str, Any]]:
    values = [
        copy.deepcopy(row)
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
    ]

    role = _role(profile.get("tipo"))
    if role not in {"VENDEDOR", "TELEVENDAS"}:
        return values

    identity = _profile_identity(profile)
    return [
        row
        for row in values
        if _row_collaborator(row, channel) == identity
    ]


def _monthly_detail(
    item: dict[str, Any],
    *,
    profile: dict[str, Any],
) -> dict[str, Any]:
    # O snapshot pode guardar os dados diretamente no item ou em payload.
    # Aceitamos apenas estruturas já existentes; não sintetizamos histórico.
    nested = item.get("payload")
    source = nested if isinstance(nested, dict) else item

    has_detail = any(
        key in source
        for key in ("dadosVendedores", "dadosTelevendas", "regrasPremiacao")
    )
    if not has_detail:
        raise HistoryReadError(
            "A fotografia histórica ainda não possui detalhes no snapshot PostgreSQL."
        )

    atualizacao = _monthly_public(item) or _monthly_public(source)
    if not atualizacao:
        raise HistoryReadError("Fotografia histórica inválida.")

    return {
        "sucesso": True,
        "banco": "SUPABASE",
        "origem": "FASTAPI_POSTGRESQL_DIRETO_V2",
        "atualizacao": atualizacao,
        "dadosVendedores": _scope_monthly_rows(
            source.get("dadosVendedores"),
            profile=profile,
            channel="VENDEDORES",
        ),
        "dadosTelevendas": _scope_monthly_rows(
            source.get("dadosTelevendas"),
            profile=profile,
            channel="TELEVENDAS",
        ),
        "regrasPremiacao": copy.deepcopy(
            source.get("regrasPremiacao")
            if isinstance(source.get("regrasPremiacao"), list)
            else []
        ),
    }


async def history_get(
    *,
    kind: str,
    history_id: str,
    profile: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    normalized = str(kind or "").strip().lower()
    if normalized not in {"mensal", "extras"}:
        raise ValueError("Histórico inválido.")

    ident = str(history_id or "").strip()
    if not ident:
        raise ValueError("Atualização histórica não informada.")

    if not _can_view(normalized, profile):
        raise PermissionError(
            "Você não possui permissão para visualizar este histórico."
        )

    modulo = (
        "HISTORICO_MENSAL"
        if normalized == "mensal"
        else "HISTORICO_EXTRAS"
    )

    try:
        payload, row = await cache_get(
            modulo=modulo,
            settings=settings,
        )
    except CacheReadError as exc:
        raise HistoryReadError(str(exc)) from exc

    raw = (
        payload.get("atualizacoes")
        if isinstance(payload.get("atualizacoes"), list)
        else []
    )

    selected = next(
        (
            item
            for item in raw
            if isinstance(item, dict)
            and str(item.get("idAtualizacao") or "").strip() == ident
        ),
        None,
    )
    if selected is None:
        raise LookupError("Atualização histórica não encontrada.")

    if normalized != "mensal":
        # A tela corrigida nesta fase é o histórico mensal. Mantemos Extras
        # no fluxo existente até haver um contrato de detalhe equivalente.
        raise HistoryReadError(
            "Detalhe direto do histórico de Extras ainda não está disponível."
        )

    result = _monthly_detail(selected, profile=profile)
    result["snapshotAtualizadoEm"] = str(row.get("atualizado_em") or "")
    result["snapshotVersao"] = str(row.get("versao") or "")
    return result


async def _monthly_history_metadata_fast(
    *,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # PROD5.9.8.23.21
    # Lista somente os metadados das 3 ultimas atualizacoes.
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

    try:
        async with httpx.AsyncClient(
            timeout=max(8.0, settings.request_timeout_seconds)
        ) as client:
            response = await client.post(
                endpoint,
                json={
                    "acao": "HISTORY_CACHE_LIST",
                    "modulo": "HISTORICO_MENSAL",
                },
                headers=headers,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HistoryReadError(
            "A lista leve do histórico não respondeu dentro do tempo esperado."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise HistoryReadError(
            f"A lista leve do histórico respondeu em formato inválido "
            f"(HTTP {response.status_code})."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise HistoryReadError(
            str(data.get("erro") or f"Histórico HTTP {response.status_code}.")
        )

    if data.get("sucesso") is not True:
        raise HistoryReadError(
            str(data.get("erro") or "Falha ao consultar a lista do histórico.")
        )

    if data.get("encontrado") is not True:
        return [], {
            "atualizado_em": "",
            "versao": "",
        }

    raw = (
        data.get("atualizacoes")
        if isinstance(data.get("atualizacoes"), list)
        else []
    )

    return (
        [
            copy.deepcopy(item)
            for item in raw
            if isinstance(item, dict)
        ][:3],
        {
            "atualizado_em": str(data.get("snapshotAtualizadoEm") or ""),
            "versao": str(data.get("snapshotVersao") or ""),
        },
    )


async def history_list(
    *,
    kind: str,
    profile: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    normalized = str(kind or "").strip().lower()
    if normalized not in {"mensal", "extras"}:
        raise ValueError("Histórico inválido.")

    if not _can_view(normalized, profile):
        raise PermissionError(
            "Você não possui permissão para visualizar este histórico."
        )

    modulo = (
        "HISTORICO_MENSAL"
        if normalized == "mensal"
        else "HISTORICO_EXTRAS"
    )

    if normalized == "mensal":
        raw: list[dict[str, Any]] = []
        row: dict[str, Any] = {}

        try:
            raw, row = await _monthly_history_metadata_fast(
                settings=settings,
            )
        except HistoryReadError:
            # A consulta completa abaixo continua sendo o fallback oficial.
            pass

        # PROD5.9.8.23.23:
        # Se uma resposta leve intermediaria vier com menos de 3 itens,
        # confirma o snapshot completo ja persistido no PostgreSQL.
        if len(raw) < 3:
            try:
                payload_full, row_full = await cache_get(
                    modulo=modulo,
                    settings=settings,
                )
            except CacheReadError as exc:
                if not raw:
                    raise HistoryReadError(str(exc)) from exc
            else:
                raw_full = (
                    payload_full.get("atualizacoes")
                    if isinstance(payload_full.get("atualizacoes"), list)
                    else []
                )
                if len(raw_full) > len(raw):
                    raw = raw_full
                    row = row_full

    else:
        try:
            payload, row = await cache_get(
                modulo=modulo,
                settings=settings,
            )
        except CacheReadError as exc:
            raise HistoryReadError(str(exc)) from exc

        raw = (
            payload.get("atualizacoes")
            if isinstance(payload.get("atualizacoes"), list)
            else []
        )

    mapper = _monthly_public if normalized == "mensal" else _extras_public

    items: list[dict[str, Any]] = []
    for item in raw:
        public = mapper(item)
        if public:
            items.append(public)

    items.sort(key=_date_key, reverse=True)
    items = items[:3]

    return {
        "sucesso": True,
        "configurado": True,
        "banco": "SUPABASE",
        "origem": "FASTAPI_POSTGRESQL_DIRETO_V2",
        "atualizacoes": items,
        "limiteHistorico": 3,
        "podeExcluir": _can_delete(normalized, profile),
        "snapshotAtualizadoEm": str(row.get("atualizado_em") or ""),
        "snapshotVersao": str(row.get("versao") or ""),
    }
