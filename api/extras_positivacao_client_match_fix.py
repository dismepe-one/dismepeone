from __future__ import annotations

from typing import Any

from . import extras_reads
from . import extras_positivacao_ranking as ranking
from . import prod597_app as prod597


METRIC = ranking.METRIC


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


def _source_key(
    row: list[Any],
    *,
    collaborator_index: int,
    date_index: int,
    product_index: int,
    sale_index: int,
    qty_index: int,
) -> tuple[str, str, str, float, float]:
    return (
        extras_reads._flex(_value(row, collaborator_index)),
        prod597._extra_iso_date(_value(row, date_index)),
        ranking._normalize_product_code(_value(row, product_index)),
        _round_key(_value(row, sale_index)),
        _round_key(_value(row, qty_index)),
    )


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

        headers = rows[0]
        collaborator_index = ranking._header_index(
            headers,
            ("VENDEDOR/TELEVENDA", "VENDEDOR/TELEVENDAS", "COLABORADOR", "VENDEDOR", "TELEVENDAS"),
        )
        client_code_index = ranking._header_index(
            headers,
            ("CÓD CLIENTE", "COD CLIENTE", "CÓD. CLIENTE", "COD. CLIENTE", "CODIGO CLIENTE", "CÓDIGO CLIENTE"),
        )
        client_name_index = ranking._header_index(
            headers,
            ("CLIENTE", "NOME CLIENTE", "RAZAO SOCIAL", "RAZÃO SOCIAL"),
        )

        if collaborator_index < 0 or client_code_index < 0:
            return original(rows, normalized_rows)

        source_rows = [
            row
            for row in rows[1:]
            if str(_value(row, collaborator_index)).strip()
        ]

        # Caminho original: se a fotografia está perfeitamente alinhada,
        # não muda absolutamente nada no comportamento já validado.
        if len(source_rows) == len(normalized_rows):
            return original(rows, normalized_rows)

        date_index = ranking._header_index(headers, ("DATA",))
        product_index = ranking._header_index(
            headers,
            ("CÓD PROD", "COD PROD", "CÓD. PRODUTO", "COD. PRODUTO", "CODIGO PRODUTO", "CÓDIGO PRODUTO"),
        )
        sale_index = ranking._header_index(
            headers,
            ("VENDA LÍQUIDA", "VENDA LIQUIDA", "VENDA", "VENDA LÍQUIDA (R$)", "VENDA LIQUIDA (R$)"),
        )
        qty_index = ranking._header_index(
            headers,
            ("TOTAL DE UNIDADE", "TOTAL UNIDADE", "UNIDADE", "QUANTIDADE", "QTD"),
        )

        if min(date_index, product_index, sale_index, qty_index) < 0:
            # Sem campos suficientes para uma associação determinística,
            # preserva a leitura normalizada sem inventar código de cliente.
            return [dict(item) for item in normalized_rows]

        buckets: dict[tuple[str, str, str, float, float], list[list[Any]]] = {}
        for source in source_rows:
            key = _source_key(
                source,
                collaborator_index=collaborator_index,
                date_index=date_index,
                product_index=product_index,
                sale_index=sale_index,
                qty_index=qty_index,
            )
            buckets.setdefault(key, []).append(source)

        output: list[dict[str, Any]] = []
        for base in normalized_rows:
            item = dict(base)
            matches = buckets.get(_base_key(base)) or []
            source = matches.pop(0) if matches else None
            if source is not None:
                item["codigoCliente"] = str(_value(source, client_code_index)).strip()
                item["cliente"] = (
                    str(_value(source, client_name_index)).strip()
                    if client_name_index >= 0
                    else ""
                )
            else:
                # Linha auxiliar ou não associável: mantém a venda, porém não
                # atribui cliente incorreto. Ela será naturalmente ignorada na
                # contagem de positivação até existir associação determinística.
                item.setdefault("codigoCliente", "")
                item.setdefault("cliente", "")
            output.append(item)

        return output

    ranking._sheet_client_fields = fixed_sheet_client_fields
