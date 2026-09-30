from __future__ import annotations

import asyncio
import re
from typing import Any

from . import extras_reads
from . import prod597_app as prod597
from . import extras_positivacao_ranking as ranking


METRIC = ranking.METRIC


def _metric(campaign: dict[str, Any]) -> str:
    return str(campaign.get("metrica") or "").strip().upper()


def _header_key(value: Any) -> str:
    return ranking._header_key(value)


def _alt_header(row: list[Any]) -> bool:
    if len(row) < 7:
        return False
    keys = [_header_key(value) for value in row]
    return (
        "CLIENTE" in keys[1]
        and any(marker in keys[2] for marker in ("VENDEDOR", "TELEVENDAS", "COLABORADOR"))
        and "FORNECEDOR" in keys[3]
        and "VENDA" in keys[4]
        and "DATA" in keys[5]
        and "UNIDADE" in keys[6]
    )


def _alt_header_index(rows: list[list[Any]]) -> int:
    for index, row in enumerate(rows[:5]):
        if _alt_header(row):
            return index
    return -1


def _alternate_sheet_records(
    campaign: dict[str, Any],
    rows: list[list[Any]],
) -> list[dict[str, Any]] | None:
    header_index = _alt_header_index(rows)
    if header_index < 0:
        return None

    campaign_id = str(campaign.get("id") or "").strip()
    campaign_name = str(campaign.get("nome") or "").strip()
    campaign_lab = str(campaign.get("laboratorio") or "").strip()
    output: list[dict[str, Any]] = []

    # Estrutura efetivamente gerada pelo legado para a métrica de positivação:
    # A campanha | B cód. cliente | C vendedor/televendas | D fornecedor |
    # E venda líquida | F data | G total unidade | H cód. produto.
    for row in rows[header_index + 1 :]:
        if _alt_header(row):
            continue
        customer = ranking._normalize_customer_code(
            row[1] if len(row) > 1 else ""
        )
        collaborator = str(
            row[2] if len(row) > 2 and row[2] is not None else ""
        ).strip()
        if not customer or not collaborator:
            continue

        lab = str(
            row[3]
            if len(row) > 3 and row[3] is not None
            else campaign_lab
        ).strip()
        product = ranking._normalize_product_code(
            row[7] if len(row) > 7 else ""
        )
        if not product:
            continue

        output.append(
            {
                "colaborador": collaborator,
                "laboratorio": lab or campaign_lab,
                "data": prod597._extra_iso_date(row[5] if len(row) > 5 else ""),
                "venda": prod597._extra_number(row[4] if len(row) > 4 else 0),
                "codigoProduto": product,
                "quantidade": prod597._extra_number(row[6] if len(row) > 6 else 0),
                "observacao": "",
                "codigoCliente": customer,
                "cliente": "",
                "idCampanha": campaign_id,
                "campanhaNome": campaign_name,
            }
        )

    return output


def _looks_like_date(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(
        re.fullmatch(r"\d{2}/\d{2}/\d{4}", text)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10])
    )


def _same_lab_after_legacy_date_conversion(campaign_lab: Any, value: Any) -> bool:
    campaign_key = _header_key(campaign_lab)
    value_key = _header_key(value)
    if not campaign_key or not value_key:
        return False
    return (
        campaign_key == value_key
        or campaign_key.startswith(value_key)
        or value_key.startswith(campaign_key)
    )


def _repair_cached_row(
    campaign: dict[str, Any],
    row: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    # Fotografia gravada antes deste fix ficou deslocada assim:
    # colaborador=cód cliente; laboratorio=colaborador; data=fornecedor;
    # codigoProduto=data; observacao=cód produto.
    campaign_lab = str(campaign.get("laboratorio") or "").strip()
    shifted = (
        _same_lab_after_legacy_date_conversion(campaign_lab, row.get("data"))
        and _looks_like_date(row.get("codigoProduto"))
        and bool(str(row.get("laboratorio") or "").strip())
        and bool(ranking._normalize_customer_code(row.get("colaborador")))
        and bool(ranking._normalize_product_code(row.get("observacao")))
    )
    if not shifted:
        return row, False

    fixed = dict(row)
    fixed["codigoCliente"] = ranking._normalize_customer_code(row.get("colaborador"))
    fixed["cliente"] = ""
    fixed["colaborador"] = str(row.get("laboratorio") or "").strip()
    fixed["laboratorio"] = campaign_lab
    fixed["data"] = prod597._extra_iso_date(row.get("codigoProduto"))
    fixed["codigoProduto"] = ranking._normalize_product_code(row.get("observacao"))
    fixed["observacao"] = ""
    return fixed, True


def _repair_cached_payload(
    campaign: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    store = payload.get("vendasPorCampanha")
    if not isinstance(store, dict):
        return payload, 0

    campaign_id = str(campaign.get("id") or "").strip()
    raw_rows = store.get(campaign_id)
    if not isinstance(raw_rows, list):
        return payload, 0

    repaired_rows: list[Any] = []
    repaired_count = 0
    for item in raw_rows:
        if not isinstance(item, dict):
            repaired_rows.append(item)
            continue
        fixed, changed = _repair_cached_row(campaign, item)
        repaired_rows.append(fixed)
        repaired_count += 1 if changed else 0

    if repaired_count <= 0:
        return payload, 0

    fixed_store = dict(store)
    fixed_store[campaign_id] = repaired_rows
    fixed_payload = dict(payload)
    fixed_payload["vendasPorCampanha"] = fixed_store
    return fixed_payload, repaired_count


def install_extras_positivacao_schema_fix(app: Any) -> None:
    if getattr(app.state, "extras_positivacao_schema_fix_installed", False):
        return
    app.state.extras_positivacao_schema_fix_installed = True

    current_sheet_records = prod597._extra_sheet_records

    async def fixed_sheet_records(
        campaign: dict[str, Any],
        workbook_cache: dict[str, bytes],
    ) -> list[dict[str, Any]]:
        if _metric(campaign) != METRIC:
            return await current_sheet_records(campaign, workbook_cache)

        previous_error: Exception | None = None
        try:
            current = await current_sheet_records(campaign, workbook_cache)
        except Exception as exc:  # mantém fallback somente para esta métrica
            current = []
            previous_error = exc

        spreadsheet_id = prod597._extra_sheet_id(campaign)
        raw_xlsx = workbook_cache.get(spreadsheet_id)
        if raw_xlsx is not None:
            sheet_name = str(campaign.get("aba") or campaign.get("id") or "").strip()
            rows = await asyncio.to_thread(prod597._read_sheet, raw_xlsx, sheet_name)
            alternate = _alternate_sheet_records(campaign, rows)
            if alternate is not None:
                return alternate

        if previous_error is not None:
            raise previous_error
        return current

    prod597._extra_sheet_records = fixed_sheet_records

    current_partial = extras_reads._partial_for_campaign

    def fixed_partial(
        campaign: dict[str, Any],
        extras_payload: dict[str, Any],
        by_alias: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if _metric(campaign) != METRIC:
            return current_partial(campaign, extras_payload, by_alias)

        repaired_payload, repaired_count = _repair_cached_payload(
            campaign,
            extras_payload,
        )
        result = ranking._custom_partial(campaign, repaired_payload, by_alias)
        if repaired_count and isinstance(result, dict):
            result = dict(result)
            diagnostic = result.get("diagnosticoRanking")
            if isinstance(diagnostic, dict):
                diagnostic = dict(diagnostic)
                diagnostic["linhasEstruturaCorrigida"] = repaired_count
                result["diagnosticoRanking"] = diagnostic
        return result

    extras_reads._partial_for_campaign = fixed_partial
