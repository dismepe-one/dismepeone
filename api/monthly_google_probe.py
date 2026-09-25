"""Read-only source access check for monthly homologation."""

from .monthly_google_reader import monthly_google_reader_info


def google_reader_configured():
    return monthly_google_reader_info() is not None



def probe_google_sources():
    import os
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    info = monthly_google_reader_info()
    if not info:
        return False
    service = build(
        "sheets", "v4",
        credentials=Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        ),
        cache_discovery=False,
    )
    sources = (
        ("DISMEPE_MONTHLY_CURRENT_SHEET_ID", {"CAMPANHA VEND", "CAMPANHAS TLVS"}),
        ("DISMEPE_MONTHLY_AUXILIARY_SHEET_ID", {"METRICA_GLOBO", "GLOBO_CLIENTES",
            "HERBAMED_REGRAS", "HERB_COM", "INTEGRAL_PRODUTOS",
            "INTEGRAL_FAIXAS", "INT_PONTOS"}),
    )
    for variable, required in sources:
        spreadsheet_id = os.getenv(variable, "").strip()
        if not spreadsheet_id:
            return False
        data = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId,sheets(properties(title))",
        ).execute(num_retries=1)
        found = {item["properties"]["title"] for item in data.get("sheets", [])}
        if not required.issubset(found):
            return False
    return True
