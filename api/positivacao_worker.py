"""Processo separado de importação da Positivação Geral (somente servidor)."""
from __future__ import annotations

import asyncio
import os
import signal

from . import positivacao_geral as pos


def main() -> None:
    pos._WORKER_PROCESS = True
    pos._WORKER_RUN_ID = os.getenv("DISMEPE_POS_WORKER_RUN", "")
    def _limit_reached(signum, frame):
        # Encerramento forçado: asyncio.run() poderia esperar indefinidamente
        # uma thread de download mesmo após cancelar a coroutine.
        pos._SYNC_RESULT = "ERRO"
        pos._SYNC_ERROR = ("A atualização excedeu o limite de 240 segundos "
                           "e foi interrompida; a versão anterior foi preservada.")
        pos._SYNC_LAST_FINISHED = pos._now()
        pos._worker_progress()
        print(f"[POS_WORKER] tempo_limite etapa={pos._WORKER_STAGE} limite_s=240", flush=True)
        os._exit(124)

    signal.signal(signal.SIGALRM, _limit_reached)
    signal.alarm(pos._POS_WORKER_MAX_SECONDS)
    pos._worker_stage("INICIADO", "VERIFICANDO")
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
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
