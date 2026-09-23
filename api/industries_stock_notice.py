from __future__ import annotations

"""Aviso do Mapa agendado: publica uma vez por SHA após importação persistida."""
import asyncio
import hashlib
import logging

from .push_notifications import edge, deliver_notice

log = logging.getLogger("uvicorn.error")


async def notify_scheduled_stock_import(sha256: str) -> bool:
    digest = str(sha256 or "").strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("SHA do mapa inválido")
    notice_id = "ONE-PUSH-" + hashlib.sha256(("INDUSTRIAS_MAPA:" + digest).encode()).hexdigest()[:32]
    result = await edge("STOCK_IMPORTED_NOTICE", sha256=digest, id=notice_id)
    if result.get("criado") is not True:
        return False
    await deliver_notice(notice_id)
    return True


def notify_stock_worker(sha256: str) -> None:
    try:
        created = asyncio.run(notify_scheduled_stock_import(sha256))
        log.info("Mapa agendado: notificação %s", "publicada" if created else "já existente")
    except Exception as exc:
        # A notificação é secundária: uma falha não transforma o mapa já importado em erro.
        log.warning("Mapa importado, mas aviso automático indisponível (%s).", type(exc).__name__)
