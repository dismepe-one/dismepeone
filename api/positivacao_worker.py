"""Processo separado de importação da Positivação Geral (somente servidor)."""
from __future__ import annotations

import asyncio
import os

from . import positivacao_geral as pos


def main() -> None:
    pos._WORKER_PROCESS = True
    pos._WORKER_RUN_ID = os.getenv("DISMEPE_POS_WORKER_RUN", "")
    pos._SYNC_RESULT = "VERIFICANDO"
    pos._worker_progress()
    profile = {"usuario": os.getenv("DISMEPE_POS_WORKER_USER", "")}
    try:
        asyncio.run(pos._manual_check_and_refresh(profile))
    except BaseException:
        # Um worker falho nunca pode marcar a fotografia como publicada.
        pos._SYNC_RESULT = "ERRO"
        pos._SYNC_ERROR = "O processo externo foi interrompido; a base anterior foi preservada."
        pos._SYNC_LAST_FINISHED = pos._now()
        pos._worker_progress()
        raise


if __name__ == "__main__":
    main()
