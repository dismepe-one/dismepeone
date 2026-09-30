from __future__ import annotations

import uuid
from datetime import datetime, timezone

# Camada mínima sobre a aplicação oficial: preserva integralmente o PROD atual
# e registra somente as integrações privadas de "Minhas Campanhas".
from . import prod597_app as prod597
from .prod597_app import app, settings  # noqa: F401
from .cache_reads import cache_get
from .my_campaigns import router as my_campaigns_router
from . import home_publication as home_module
from .extras_positivacao_ranking import install_extras_positivacao_ranking
from .extras_positivacao_schema_fix import install_extras_positivacao_schema_fix
from .extras_positivacao_client_match_fix import install_extras_positivacao_client_match_fix
from .extras_positivacao_partial_display import install_extras_positivacao_partial_display
from .pdf_branding import install_pdf_branding


TARGET_EXTRAS_CAMPAIGN = "CE-20260930-154538-472167"
STALE_EXTRAS_CUTOFF = datetime(2026, 9, 30, 20, 0, 0, tzinfo=timezone.utc)
_original_refresh_extras_snapshot = prod597._refresh_extras_snapshot


def _parse_snapshot_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def _refresh_extras_snapshot_with_natulab_migration(
    *,
    legacy_token: str,
    profile: dict,
    require_change: bool = False,
):
    force_once = False
    if require_change:
        try:
            previous, row = await cache_get(modulo="EXTRAS", settings=settings)
            sales = previous.get("vendasPorCampanha") if isinstance(previous, dict) else None
            has_target = isinstance(sales, dict) and TARGET_EXTRAS_CAMPAIGN in sales
            saved_at = _parse_snapshot_time(row.get("atualizado_em") if isinstance(row, dict) else "")
            force_once = bool(
                has_target
                and saved_at is not None
                and saved_at < STALE_EXTRAS_CUTOFF
            )
        except Exception:
            force_once = False

    # Migração pontual: a fotografia de 19:53Z foi criada antes das correções
    # de associação/visualização desta campanha. Ela precisa ser reconstruída
    # uma única vez mesmo quando os dados brutos do Google forem idênticos.
    return await _original_refresh_extras_snapshot(
        legacy_token=legacy_token,
        profile=profile,
        require_change=False if force_once else require_change,
    )


prod597._refresh_extras_snapshot = _refresh_extras_snapshot_with_natulab_migration


@app.on_event("startup")
async def _rebuild_stale_natulab_extras_snapshot_once() -> None:
    """Regrava apenas a fotografia EXTRAS anterior à correção da campanha NATULAB.

    A leitura de Campanhas Extras já usa configuração SQL + Google Drive com a
    conta de serviço; o token legado não participa dessa leitura. A condição de
    timestamp torna esta migração idempotente: após a primeira gravação nova,
    os próximos startups não fazem nada.
    """
    try:
        previous, row = await cache_get(modulo="EXTRAS", settings=settings)
        sales = previous.get("vendasPorCampanha") if isinstance(previous, dict) else None
        has_target = isinstance(sales, dict) and TARGET_EXTRAS_CAMPAIGN in sales
        saved_at = _parse_snapshot_time(
            row.get("atualizado_em") if isinstance(row, dict) else ""
        )
        if not (
            has_target
            and saved_at is not None
            and saved_at < STALE_EXTRAS_CUTOFF
        ):
            return

        await _refresh_extras_snapshot_with_natulab_migration(
            legacy_token="",
            profile={
                "usuario": "SISTEMA",
                "nome": "SISTEMA",
                "tipo": "ADMINISTRADOR",
            },
            require_change=False,
        )
    except Exception as exc:
        # Uma falha de sincronização nunca impede o portal de iniciar. A
        # fotografia anterior continua preservada e o erro fica nos logs.
        home_module.logger.exception(
            "Campanhas Extras: falha na migração pontual da fotografia NATULAB (%s)",
            type(exc).__name__,
        )


_original_monthly_publish = home_module._home_publication_publish_locked


async def _monthly_publish_with_supervisor_notice(body, background_tasks, session):
    previous, _ = await home_module._read_publication()
    previous_monthly = (
        previous.get("mensal")
        if isinstance(previous, dict) and isinstance(previous.get("mensal"), dict)
        else {}
    )
    previous_signature = (
        home_module._partial_signature(previous_monthly) if previous_monthly else ""
    )

    result = await _original_monthly_publish(body, background_tasks, session)
    if (
        not isinstance(result, dict)
        or result.get("sucesso") is not True
        or result.get("somenteMetricasEspeciais") is True
    ):
        return result

    current, _ = await home_module._read_publication()
    current_monthly = (
        current.get("mensal")
        if isinstance(current, dict) and isinstance(current.get("mensal"), dict)
        else {}
    )
    current_signature = (
        home_module._partial_signature(current_monthly) if current_monthly else ""
    )
    if not current_signature or current_signature == previous_signature:
        return result

    publication_id = str(result.get("publicationId") or "").strip()
    try:
        publication_uuid = uuid.UUID(publication_id)
    except (ValueError, TypeError, AttributeError):
        return result

    now = home_module._now_recife()
    notification_id = "ONE-PUSH-" + uuid.uuid5(
        publication_uuid,
        "FERNANDA_SUP_TELEVENDAS_PARCIAIS",
    ).hex
    notice = {
        "id": notification_id,
        "tipo": "AVISO",
        "status": "ATIVO",
        "titulo": "⚠️ Fernanda · Parciais atualizadas",
        "mensagem": (
            "Fernanda, as parciais mensais de Televendas foram atualizadas. "
            "Confira Minhas Campanhas e o desempenho da equipe."
        ),
        "publico": {
            "todos": False,
            "perfis": [],
            "setores": [],
            "usuarios": ["FERNANDA"],
        },
        "criadoEpoch": int(now.timestamp() * 1000),
        "criadoEm": now.strftime("%d/%m/%Y %H:%M"),
        "criadoPor": "SISTEMA",
        "publicarEm": now.isoformat(),
        "expiraEm": "",
        "importante": False,
        "exibirUmaVez": False,
        "destino": {"modulo": "HOME", "tela": "INICIO", "fornecedor": ""},
        "pushStatus": "AGENDADO",
        "origem": "MINHAS_CAMPANHAS_PARCIAIS_MENSAIS",
        "publicationId": publication_id,
    }
    try:
        registered = await home_module._edge_call(
            "NOTIFICACAO_UPSERT",
            {"notificacao": notice},
            timeout_seconds=20.0,
        )
        if str(registered.get("id") or "") == notification_id:
            background_tasks.add_task(home_module.deliver_notice, notification_id)
    except Exception:
        # A notificação não pode invalidar uma publicação mensal já confirmada.
        pass
    return result


_monthly_publish_with_supervisor_notice.__dismepe_supervisor_notice__ = True
home_module._home_publication_publish_locked = _monthly_publish_with_supervisor_notice

app.include_router(my_campaigns_router)
install_extras_positivacao_ranking(app)
install_extras_positivacao_schema_fix(app)
install_extras_positivacao_client_match_fix(app)
install_extras_positivacao_partial_display(app)
install_pdf_branding(app)
