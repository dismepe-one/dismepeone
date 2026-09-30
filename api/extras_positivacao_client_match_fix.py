from __future__ import annotations

from typing import Any

from . import extras_reads
from . import extras_positivacao_ranking as ranking
from . import prod597_app as prod597


METRIC = ranking.METRIC

# Layout oficial informado para a base desta métrica:
# A campanha | B televenda | C fornecedor | D data | E venda líquida
# F cód.prod | G total unidade | H cód.cliente
COL_CAMPAIGN = 0
COL_COLLABORATOR = 1
COL_SUPPLIER = 2
COL_DATE = 3
COL_SALE = 4
COL_PRODUCT = 5
COL_QTY = 6
COL_CLIENT = 7


def _value(row: list[Any], index: int) -> Any:
    if index < 0 or len(row) <= index:
        return ""
    value = row[index]
    return "" if value is None else value


def _round_key(value: Any) -> float:
    return round(float(extras_reads._num(value)), 6)


def _base_key(row: dict[str, Any]) -> tuple[str, str, str, float, float]:
    return (
        extras_reads._flex(row.get("colaborador")),
        str(row.get("data") or "").strip(),
        ranking._normalize_product_code(row.get("codigoProduto")),
        _round_key(row.get("venda")),
        _round_key(row.get("quantidade")),
    )


def _source_key(row: list[Any]) -> tuple[str, str, str, float, float]:
    return (
        extras_reads._flex(_value(row, COL_COLLABORATOR)),
        prod597._extra_iso_date(_value(row, COL_DATE)),
        ranking._normalize_product_code(_value(row, COL_PRODUCT)),
        _round_key(_value(row, COL_SALE)),
        _round_key(_value(row, COL_QTY)),
    )


def _looks_like_official_layout(rows: list[list[Any]]) -> bool:
    if not rows or len(rows[0]) < 8:
        return False
    header = [ranking._header_key(_value(rows[0], i)) for i in range(8)]
    return (
        "CAMPANHA" in header[0]
        and ("TELEVENDA" in header[1] or "VENDEDOR" in header[1])
        and ("FORNECEDOR" in header[2] or "LABORATORIO" in header[2])
        and header[3] == "DATA"
        and "VENDA" in header[4]
        and "PROD" in header[5]
        and ("UNIDADE" in header[6] or "QUANTIDADE" in header[6])
        and "CLIENTE" in header[7]
    )


def _is_real_data_row(row: list[Any]) -> bool:
    collaborator = str(_value(row, COL_COLLABORATOR)).strip()
    raw_date = str(_value(row, COL_DATE)).strip()
    product = ranking._normalize_product_code(_value(row, COL_PRODUCT))
    client = ranking._normalize_customer_code(_value(row, COL_CLIENT))
    iso_date = prod597._extra_iso_date(raw_date)

    if not collaborator or not product or not client:
        return False
    if not iso_date or iso_date == raw_date and not raw_date[:4].isdigit():
        return False
    # Impede que a segunda linha de cabeçalho seja tratada como venda.
    if ranking._header_key(collaborator) in {
        "TELEVENDA",
        "TELEVENDAS",
        "VENDEDOR",
        "VENDEDOR TELEVENDA",
        "VENDEDOR TELEVENDAS",
    }:
        return False
    if ranking._header_key(str(_value(row, COL_CLIENT))) in {
        "COD CLIENTE",
        "CODIGO CLIENTE",
        "CLIENTE",
    }:
        return False
    return True


def install_extras_positivacao_client_match_fix(app: Any) -> None:
    if getattr(app.state, "extras_positivacao_client_match_fix_installed", False):
        return
    app.state.extras_positivacao_client_match_fix_installed = True

    original = ranking._sheet_client_fields

    def fixed_sheet_client_fields(
        rows: list[list[Any]],
        normalized_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rows or not normalized_rows:
            return original(rows, normalized_rows)

        # A correção é deliberadamente restrita ao layout oficial A:H.
        # Outras campanhas continuam usando exatamente o leitor anterior.
        if not _looks_like_official_layout(rows):
            return original(rows, normalized_rows)

        source_rows = [row for row in rows[1:] if _is_real_data_row(row)]
        if not source_rows:
            return [dict(item) for item in normalized_rows]

        # Usa a combinação dos campos comerciais para localizar a linha original.
        # H é sempre o código do cliente e nunca é inferido de outra coluna.
        buckets: dict[tuple[str, str, str, float, float], list[list[Any]]] = {}
        for source in source_rows:
            buckets.setdefault(_source_key(source), []).append(source)

        output: list[dict[str, Any]] = []
        matched = 0
        for base in normalized_rows:
            item = dict(base)
            matches = buckets.get(_base_key(base)) or []
            source = matches.pop(0) if matches else None
            if source is not None:
                item["codigoCliente"] = str(_value(source, COL_CLIENT)).strip()
                item["cliente"] = ""
                matched += 1
            else:
                # Não associa cliente por aproximação. Uma linha que não tenha
                # correspondência exata permanece sem cliente, sem bloquear a
                # atualização inteira nem contaminar a positivação.
                item["codigoCliente"] = ""
                item["cliente"] = ""
            output.append(item)

        # Segurança real: só rejeita a associação se nenhuma linha comercial
        # puder ser relacionada. Diferenças causadas por cabeçalhos/linhas
        # auxiliares não interrompem mais a campanha inteira.
        if normalized_rows and matched == 0:
            return original(rows, normalized_rows)

        return output

    ranking._sheet_client_fields = fixed_sheet_client_fields
