"""Execucao mensal em modo sombra; nenhum endpoint publico ou escrita."""
from __future__ import annotations

import json
import os

from .monthly_render_shadow import _current_source, _read_current_source
from .monthly_manual_indicators import parse_manual_indicators


def run_readonly(snapshot, timestamp, indicators, spreadsheet_id):
    manual = parse_manual_indicators({"sucesso": True, "valores": indicators})
    source = _current_source(snapshot)
    audit = _read_current_source(source, snapshot, spreadsheet_id, manual)
    return {
        "modo": "SOMENTE_LEITURA",
        "competencia": source.competence,
        "snapshotAtualizadoEm": str(timestamp),
        "fonteModificadaEm": audit["modificadoEm"],
        "linhasFonte": audit["abas"],
        "auditoriaFonteVsFotografia": audit["auditoria"],
        "linhasCandidatas": audit["linhasCandidatas"],
        "fontesAuxiliares": audit["fontesAuxiliares"],
        "previaPremiacoesEspeciais": audit["previaEspeciais"],
        "paridadeFinanceiraCompleta": False,
        "publicacaoAutorizada": False,
    }


def main():
    if os.environ.get("DISMEPE_MONTHLY_HOMOLOGATION") != "1":
        raise SystemExit("Homologacao nao habilitada.")
    if os.environ.get("DISMEPE_MONTHLY_WRITE_ENABLED", "0") != "0":
        raise SystemExit("Execucao recusada: escrita habilitada.")
    raise SystemExit("Fonte SQL somente leitura ainda nao conectada ao executor.")


if __name__ == "__main__":
    main()
