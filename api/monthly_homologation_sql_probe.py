"""Verificação privada e somente leitura do acesso SQL da homologação.

Nenhum resultado comercial, senha, hostname ou token sai desta rotina.
"""
from __future__ import annotations

import os


def probe_sql_readonly() -> bool:
    url = os.getenv("DISMEPE_MONTHLY_READONLY_DATABASE_URL", "").strip()
    if os.getenv("DISMEPE_MONTHLY_WRITE_ENABLED", "0") != "0" or not url:
        return False
    import psycopg
    with psycopg.connect(url, connect_timeout=6) as connection:
        with connection.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute(
                "SELECT current_user, current_setting('transaction_read_only'), "
                "has_table_privilege(current_user, 'public.dismepe_cache_operacional', 'SELECT'), "
                "has_table_privilege(current_user, 'public.dismepe_config', 'SELECT'), "
                "has_table_privilege(current_user, 'dismepe_monthly_homolog.monthly_snapshot', 'SELECT')"
            )
            role, read_only, base_cache, base_config, view = cur.fetchone()
            if role != "dismepe_monthly_homolog_login" or read_only != "on" or base_cache or base_config or not view:
                return False
            cur.execute("SELECT count(*) FROM dismepe_monthly_homolog.monthly_snapshot")
            snapshot_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM dismepe_monthly_homolog.manual_indicators")
            indicators_count = cur.fetchone()[0]
            cur.execute("ROLLBACK")
    return snapshot_count == 1 and indicators_count == 2
