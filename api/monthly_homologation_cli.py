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
    database = os.environ.get("DISMEPE_MONTHLY_READONLY_DATABASE_URL", "").strip()
    spreadsheet = os.environ.get("DISMEPE_MONTHLY_AUXILIARY_SHEET_ID", "").strip()
    if not database or not spreadsheet:
        raise SystemExit("Conexao de leitura SQL ou identificador da planilha nao configurado.")
    import psycopg
    try:
        with psycopg.connect(database, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("BEGIN READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute(
                    "SELECT payload, atualizado_em FROM public.dismepe_cache_operacional WHERE modulo = %s",
                    ("MENSAL",),
                )
                row = cur.fetchone()
                if not row or not isinstance(row[0], dict):
                    raise ValueError("Fotografia mensal ausente.")
                cur.execute(
                    "SELECT chave, valor FROM public.dismepe_config WHERE chave = ANY(%s)",
                    (["FATURAMENTO_GERAL_MANUAL", "POSITIVACAO_GERAL_MANUAL"],),
                )
                indicators = dict(cur.fetchall())
                cur.execute("ROLLBACK")
        result = run_readonly(row[0], row[1], indicators, spreadsheet)
    except Exception as exc:
        print(json.dumps({"sucesso": False, "etapa": "HOMOLOGACAO_INTERROMPIDA",
                          "tipoFalha": type(exc).__name__, "publicacaoAutorizada": False}))
        raise SystemExit(1) from None
    print(json.dumps({"sucesso": True, **result}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
