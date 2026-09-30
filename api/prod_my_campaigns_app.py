from __future__ import annotations

import uuid

# Camada mínima sobre a aplicação oficial: preserva integralmente o PROD atual
# e registra somente as integrações privadas de "Minhas Campanhas".
from .prod597_app import app, settings  # noqa: F401
from .my_campaigns import router as my_campaigns_router
from . import home_publication as home_module
from .extras_positivacao_ranking import install_extras_positivacao_ranking


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
