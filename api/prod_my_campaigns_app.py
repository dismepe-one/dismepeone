from __future__ import annotations

import uuid

# Camada mínima sobre a aplicação oficial: preserva integralmente o PROD atual
# e apenas registra as rotas privadas de "Minhas campanhas".
from .prod597_app import app, settings  # noqa: F401
from .my_campaigns import router as my_campaigns_router
from . import home_publication as home_module


async def _install_supervisor_notice_once() -> None:
    if getattr(home_module._home_publication_publish_locked, "__dismepe_supervisor_notice__", False):
        return

    original = home_module._home_publication_publish_locked

    async def wrapped(body, background_tasks, session):
        previous, _previous_row = await home_module._read_publication()
        previous_monthly = (
            previous.get("mensal") if isinstance(previous, dict) and isinstance(previous.get("mensal"), dict)
            else {}
        )
        previous_signature = home_module._partial_signature(previous_monthly) if previous_monthly else ""

        result = await original(body, background_tasks, session)
        if not isinstance(result, dict) or result.get("sucesso") is not True:
            return result

        current, _current_row = await home_module._read_publication()
        current_monthly = (
            current.get("mensal") if isinstance(current, dict) and isinstance(current.get("mensal"), dict)
            else {}
        )
        current_signature = home_module._partial_signature(current_monthly) if current_monthly else ""
        changed = bool(current_signature and current_signature != previous_signature)
        if not changed or result.get("somenteMetricasEspeciais") is True:
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
            "criadoPor": str(result.get("publicadoPor") or "SISTEMA"),
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
            # O aviso não pode invalidar uma publicação mensal já confirmada.
            pass
        return result

    wrapped.__dismepe_supervisor_notice__ = True
    wrapped.__dismepe_original__ = original
    home_module._home_publication_publish_locked = wrapped


# O módulo é carregado uma única vez pelo processo do Uvicorn; a troca abaixo
# precisa ocorrer antes das próximas chamadas de publicação mensal.
import asyncio as _asyncio
try:
    _loop = _asyncio.get_running_loop()
except RuntimeError:
    _loop = None
if _loop and _loop.is_running():
    _loop.create_task(_install_supervisor_notice_once())
else:
    # Na importação normal do Uvicorn ainda não existe loop ativo.
    _original = home_module._home_publication_publish_locked
    if not getattr(_original, "__dismepe_supervisor_notice__", False):
        async def _wrapped(body, background_tasks, session):
            previous, _ = await home_module._read_publication()
            previous_monthly = previous.get("mensal") if isinstance(previous, dict) and isinstance(previous.get("mensal"), dict) else {}
            previous_signature = home_module._partial_signature(previous_monthly) if previous_monthly else ""
            result = await _original(body, background_tasks, session)
            if not isinstance(result, dict) or result.get("sucesso") is not True or result.get("somenteMetricasEspeciais") is True:
                return result
            current, _ = await home_module._read_publication()
            current_monthly = current.get("mensal") if isinstance(current, dict) and isinstance(current.get("mensal"), dict) else {}
            current_signature = home_module._partial_signature(current_monthly) if current_monthly else ""
            if not current_signature or current_signature == previous_signature:
                return result
            publication_id = str(result.get("publicationId") or "").strip()
            try:
                publication_uuid = uuid.UUID(publication_id)
            except (ValueError, TypeError, AttributeError):
                return result
            now = home_module._now_recife()
            notification_id = "ONE-PUSH-" + uuid.uuid5(publication_uuid, "FERNANDA_SUP_TELEVENDAS_PARCIAIS").hex
            notice = {
                "id": notification_id, "tipo": "AVISO", "status": "ATIVO",
                "titulo": "⚠️ Fernanda · Parciais atualizadas",
                "mensagem": "Fernanda, as parciais mensais de Televendas foram atualizadas. Confira Minhas Campanhas e o desempenho da equipe.",
                "publico": {"todos": False, "perfis": [], "setores": [], "usuarios": ["FERNANDA"]},
                "criadoEpoch": int(now.timestamp() * 1000), "criadoEm": now.strftime("%d/%m/%Y %H:%M"),
                "criadoPor": str(result.get("publicadoPor") or "SISTEMA"), "publicarEm": now.isoformat(), "expiraEm": "",
                "importante": False, "exibirUmaVez": False,
                "destino": {"modulo": "HOME", "tela": "INICIO", "fornecedor": ""},
                "pushStatus": "AGENDADO", "origem": "MINHAS_CAMPANHAS_PARCIAIS_MENSAIS", "publicationId": publication_id,
            }
            try:
                registered = await home_module._edge_call("NOTIFICACAO_UPSERT", {"notificacao": notice}, timeout_seconds=20.0)
                if str(registered.get("id") or "") == notification_id:
                    background_tasks.add_task(home_module.deliver_notice, notification_id)
            except Exception:
                pass
            return result
        _wrapped.__dismepe_supervisor_notice__ = True
        _wrapped.__dismepe_original__ = _original
        home_module._home_publication_publish_locked = _wrapped


app.include_router(my_campaigns_router)
