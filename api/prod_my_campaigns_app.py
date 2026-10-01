from __future__ import annotations

import uuid

# Camada mínima sobre a aplicação oficial: preserva integralmente o PROD atual
# e registra somente as integrações privadas de "Minhas Campanhas".
from .prod597_app import app, settings  # noqa: F401
from .my_campaigns import router as my_campaigns_router
from . import home_publication as home_module
from .extras_positivacao_ranking import install_extras_positivacao_ranking
from .extras_manual_ranking import install_extras_manual_ranking
from .extras_users_fallback import install_extras_users_fallback
from .extras_positivacao_schema_fix import install_extras_positivacao_schema_fix
from .extras_positivacao_client_match_fix import install_extras_positivacao_client_match_fix
from .extras_positivacao_partial_display import install_extras_positivacao_partial_display
from .monthly_competence_guard import install_monthly_competence_guard
from .pulsy_monthly_overlay import install_pulsy_monthly_overlay
from .pulsy_product_names_display import install_pulsy_product_names_display
from .resumo_latest_month_default import install_resumo_latest_month_default
from .commercial_intelligence import install_commercial_intelligence
from .commercial_intelligence_recent_entry import install_commercial_intelligence_recent_entry
from .commercial_intelligence_portfolio_insights import install_commercial_intelligence_portfolio_insights
from .commercial_intelligence_safe_loading import install_commercial_intelligence_safe_loading
from .commercial_intelligence_exports import install_commercial_intelligence_exports
from .commercial_intelligence_ui_patch import install_commercial_intelligence_ui_patch
from .commercial_intelligence_ui_v4 import install_commercial_intelligence_ui_v4
from .commercial_intelligence_ui_v5 import install_commercial_intelligence_ui_v5
from .commercial_intelligence_ui_v6 import install_commercial_intelligence_ui_v6
from .commercial_intelligence_ui_v7 import install_commercial_intelligence_ui_v7
from .industry_operational_sales_guard import install_industry_operational_sales_guard
from .industry_competence_fields import install_industry_competence_fields
from .industry_mes_ano_alias import install_industry_mes_ano_alias
from .industry_stock_month_rollover import install_industry_stock_month_rollover
from .positivacao_total_source import install_positivacao_total_source
from .resumo_monthly_overlay import install_resumo_monthly_overlay
from .resumo_objective_sync import install_resumo_objective_sync
from .pdf_branding import install_pdf_branding


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
install_monthly_competence_guard()
install_pulsy_monthly_overlay(app)
install_pulsy_product_names_display()
install_resumo_latest_month_default()
install_commercial_intelligence_recent_entry()
install_commercial_intelligence_portfolio_insights()
install_commercial_intelligence(app)
install_commercial_intelligence_safe_loading(app)
install_commercial_intelligence_exports(app)
install_commercial_intelligence_ui_patch()
install_commercial_intelligence_ui_v4()
install_commercial_intelligence_ui_v5()
install_commercial_intelligence_ui_v6()
install_commercial_intelligence_ui_v7()
install_industry_operational_sales_guard()
install_industry_competence_fields()
install_industry_mes_ano_alias()
install_industry_stock_month_rollover()
install_positivacao_total_source()
install_resumo_monthly_overlay(app)
install_resumo_objective_sync(app)
install_extras_positivacao_ranking(app)
install_extras_manual_ranking(app)
install_extras_users_fallback(app)
install_extras_positivacao_schema_fix(app)
install_extras_positivacao_client_match_fix(app)
install_extras_positivacao_partial_display(app)
install_pdf_branding(app)
