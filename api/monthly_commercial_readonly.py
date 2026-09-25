"""Verificacao de vendedores e televendas com credenciais exclusivas de homologacao."""
import os

from .monthly_commercial_compare import compare_rows
from .monthly_google_reader import monthly_google_reader_info
from .monthly_render_shadow import _current_source
from .monthly_source_normalization import candidate_from_sheets


def compare_live_commercial():
    if os.getenv("DISMEPE_MONTHLY_HOMOLOGATION") != "1" or os.getenv("DISMEPE_MONTHLY_WRITE_ENABLED", "0") != "0":
        raise ValueError("Homologacao em modo somente leitura obrigatoria")
    import psycopg
    database = os.environ["DISMEPE_MONTHLY_READONLY_DATABASE_URL"]
    with psycopg.connect(database, host=os.getenv("DISMEPE_MONTHLY_POOLER_HOST"),
                         user=os.getenv("DISMEPE_MONTHLY_POOLER_USER"), connect_timeout=8) as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '20s'")
            cur.execute("SELECT current_user, current_setting('transaction_read_only'), "
                        "has_table_privilege(current_user, 'dismepe_monthly_homolog.monthly_snapshot', 'SELECT')")
            role, read_only, has_view = cur.fetchone()
            if role != "dismepe_monthly_homolog_login" or read_only != "on" or not has_view:
                raise ValueError("Identidade SQL de leitura nao validada")
            cur.execute("SELECT payload FROM dismepe_monthly_homolog.monthly_snapshot")
            records = cur.fetchall()
            if len(records) != 1 or not isinstance(records[0][0], dict):
                raise ValueError("Snapshot SQL invalido")
            snapshot = records[0][0]
            cur.execute("ROLLBACK")
    source = _current_source(snapshot)
    if source.file_id != os.getenv("DISMEPE_MONTHLY_CURRENT_SHEET_ID", "").strip():
        raise ValueError("ID mensal nao corresponde a competencia atual")
    info = monthly_google_reader_info()
    if not info:
        raise ValueError("Conta Google nao configurada")
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    client = build("sheets", "v4", credentials=Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]),
        cache_discovery=False)
    tabs = ("CAMPANHA VEND", "CAMPANHAS TLVS")
    response = client.spreadsheets().values().batchGet(
        spreadsheetId=source.file_id,
        ranges=["'" + tab + "'!A1:AZ6000" for tab in tabs],
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute(num_retries=1)
    matrices = response.get("valueRanges") or []
    if len(matrices) != 2:
        raise ValueError("Abas mensais ausentes")
    candidate = candidate_from_sheets(
        matrices[0].get("values") or [], matrices[1].get("values") or [],
        source.competence)
    return {
        "competencia": source.competence,
        "vendedores": compare_rows(candidate["dadosVendedores"], snapshot["dadosVendedores"], source.competence),
        "televendas": compare_rows(candidate["dadosTelevendas"], snapshot["dadosTelevendas"], source.competence),
        "publicacaoAutorizada": False,
    }
