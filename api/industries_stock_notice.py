from __future__ import annotations

"""Aviso do Mapa agendado: publica uma vez por SHA após importação persistida."""
import asyncio
import hashlib
import logging

from .push_notifications import edge, deliver_notice
from .access_reads import admin_edge
from .config import get_settings
from datetime import datetime
from zoneinfo import ZoneInfo


log = logging.getLogger("uvicorn.error")


async def notify_scheduled_stock_import(sha256: str) -> bool:
    digest = str(sha256 or "").strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("SHA do mapa inválido")
    notice_id = "ONE-PUSH-" + hashlib.sha256(("INDUSTRIAS_MAPA:" + digest).encode()).hexdigest()[:32]
    result = await edge("STOCK_IMPORTED_NOTICE", sha256=digest, id=notice_id)
    if result.get("criado") is not True:
        return False
    # O aviso operacional permanece para a indústria. Danton recebe uma
    # segunda notificação exclusiva, sem duplicar o aviso dos representantes.
    admin_id = "ONE-PUSH-" + hashlib.sha256(
        ("DANTON_CIENCIA_MAPA:" + digest).encode()
    ).hexdigest()[:32]
    now = datetime.now(ZoneInfo("America/Recife"))
    admin_notice = {
        "id": admin_id, "tipo": "AVISO", "status": "ATIVO",
        "titulo": "⚠️ Danton · Mapa de estoque atualizado",
        "mensagem": "Danton, o mapa de estoque foi atualizado. Confira as informações da indústria.",
        "publico": {"todos": False, "perfis": [], "setores": [], "usuarios": ["DANTON"]},
        "criadoEpoch": int(now.timestamp() * 1000),
        "criadoEm": now.strftime("%d/%m/%Y %H:%M"),
        "criadoPor": "Atualização automática do Mapa",
        "publicarEm": now.isoformat(), "expiraEm": "",
        "importante": False, "exibirUmaVez": False,
        "destino": {"modulo": "HOME", "tela": "INICIO", "fornecedor": ""},
        "pushStatus": "AGENDADO", "origem": "MAPA_AUTO_CIENCIA_ADMIN",
        "sha256": digest,
    }
    try:
        saved = await admin_edge(
            action="NOTIFICACAO_UPSERT",
            data={"notificacao": admin_notice},
            settings=get_settings(),
        )
        if str(saved.get("id") or "") != admin_id:
            raise RuntimeError("Aviso exclusivo do administrador não confirmado.")
        await deliver_notice(admin_id)
    except Exception as exc:
        # Nunca reverter a importação do mapa, nem bloquear o aviso operacional.
        log.warning("Mapa importado: ciência administrativa indisponível (%s).", type(exc).__name__)
    await deliver_notice(notice_id)
    return True


def notify_stock_worker(sha256: str) -> None:
    try:
        created = asyncio.run(notify_scheduled_stock_import(sha256))
        log.info("Mapa agendado: notificação %s", "publicada" if created else "já existente")
    except Exception as exc:
        # A notificação é secundária: uma falha não transforma o mapa já importado em erro.
        log.warning("Mapa importado, mas aviso automático indisponível (%s).", type(exc).__name__)
