from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Response
from fastapi.routing import APIRoute

from . import extras_reads

METRIC = "RANKING_POSITIVACAO_PRODUTOS"
MIN_PRODUCTS = 16
MIN_CUSTOMERS = 10
MIN_DISTINCT_PRODUCTS_PER_CUSTOMER = 2
MAX_PRIZE_POSITION = 5
FRONTEND_PATCH = Path(__file__).resolve().parents[1] / "frontend" / "extras-positivacao-ranking.js"


def _metric(campaign: dict[str, Any]) -> str:
    return str(campaign.get("metrica") or "").strip().upper()


def _normalize_product_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", text)


def _normalize_customer_code(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _rule(campaign: dict[str, Any]) -> dict[str, Any]:
    return campaign.get("regra") if isinstance(campaign.get("regra"), dict) else {}


def _product_codes(campaign: dict[str, Any]) -> list[str]:
    rule = _rule(campaign)
    raw = (
        rule.get("produtosSomados")
        or rule.get("codigosProdutos")
        or rule.get("produtos")
        or []
    )
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                raw = parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = re.split(r"[,;\n\r\t ]+", text)
        else:
            raw = re.split(r"[,;\n\r\t ]+", text)
    if not isinstance(raw, list):
        raw = []
    output: list[str] = []
    seen: set[str] = set()
    for value in raw:
        code = _normalize_product_code(value)
        if code and code not in seen:
            seen.add(code)
            output.append(code)
    return output


def _ranking_prizes(campaign: dict[str, Any]) -> dict[int, str]:
    config = _rule(campaign).get("rankingConfig") or []
    normalized = extras_reads._ranking_config(config)
    prizes: dict[int, str] = {}
    for position in range(1, MAX_PRIZE_POSITION + 1):
        prize = extras_reads._ranking_prize(normalized, position)
        if prize:
            prizes[position] = prize
    return prizes


def _validated_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    if _metric(campaign) != METRIC:
        return campaign

    normalized = dict(campaign)
    rule = dict(_rule(campaign))
    codes = _product_codes(campaign)
    if len(codes) != MIN_PRODUCTS:
        raise HTTPException(
            status_code=400,
            detail=f"Esta métrica exige exatamente {MIN_PRODUCTS} códigos de produtos diferentes.",
        )

    prizes = _ranking_prizes(campaign)
    missing = [position for position in range(1, MAX_PRIZE_POSITION + 1) if not prizes.get(position)]
    if missing:
        positions = ", ".join(f"{position}º" for position in missing)
        raise HTTPException(
            status_code=400,
            detail=f"Informe o brinde das cinco posições do ranking. Faltando: {positions}.",
        )

    # Estes dois valores são regras fixas desta métrica. Mesmo uma chamada direta
    # à API não pode reduzir o corte definido pela gestão.
    rule["produtosSomados"] = codes
    rule["minClientesPositivados"] = MIN_CUSTOMERS
    rule["minProdutosPorCliente"] = MIN_DISTINCT_PRODUCTS_PER_CUSTOMER
    normalized["regra"] = rule
    return normalized


def _customer_key(row: dict[str, Any]) -> str:
    code = _normalize_customer_code(
        row.get("codigoCliente")
        or row.get("codCliente")
        or row.get("clienteCodigo")
    )
    return code


def _custom_partial(
    campaign: dict[str, Any],
    extras_payload: dict[str, Any],
    by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sales = extras_reads._filtered_sales(
        campaign,
        extras_reads._campaign_sales(
            extras_payload,
            str(campaign.get("id") or ""),
        ),
    )
    sum_info = extras_reads._sum_lab(campaign, sales)
    codes = _product_codes(campaign)
    code_set = set(codes)
    rule = _rule(campaign)
    min_customers = max(
        MIN_CUSTOMERS,
        int(extras_reads._num(rule.get("minClientesPositivados")) or MIN_CUSTOMERS),
    )
    min_mix = max(
        MIN_DISTINCT_PRODUCTS_PER_CUSTOMER,
        int(extras_reads._num(rule.get("minProdutosPorCliente"))
            or MIN_DISTINCT_PRODUCTS_PER_CUSTOMER),
    )

    config_error = ""
    if len(codes) != MIN_PRODUCTS:
        config_error = (
            f"A campanha precisa ter exatamente {MIN_PRODUCTS} produtos diferentes "
            f"e possui {len(codes)}."
        )

    groups: dict[str, dict[str, Any]] = {}
    rows_without_customer = 0
    rows_target_products = 0

    for row in sales:
        collaborator = str(row.get("colaborador") or "").strip()
        group_key = extras_reads._flex(collaborator)
        if not group_key:
            continue

        channel, aliases = extras_reads._collaborator_info(collaborator, by_alias)
        if not extras_reads._collaborator_allowed(
            campaign,
            collaborator,
            channel,
            aliases,
        ):
            continue

        product = _normalize_product_code(row.get("codigoProduto"))
        if product not in code_set:
            continue
        rows_target_products += 1

        group = groups.setdefault(
            group_key,
            {
                "colaborador": collaborator,
                "setor": channel,
                "laboratorio": str(campaign.get("laboratorio") or ""),
                "venda": 0.0,
                "quantidadeProdutoFoco": 0.0,
                "quantidadeProdutosSomados": 0.0,
                "observacoes": [],
                "_clientes_produtos": {},
                "_linhas_sem_cliente": 0,
            },
        )

        group["venda"] += extras_reads._num(row.get("venda"))
        group["quantidadeProdutosSomados"] += extras_reads._num(row.get("quantidade"))

        customer = _customer_key(row)
        if not customer:
            rows_without_customer += 1
            group["_linhas_sem_cliente"] += 1
        else:
            products = group["_clientes_produtos"].setdefault(customer, {})
            products[product] = products.get(product, 0.0) + extras_reads._num(
                row.get("quantidade")
            )

        obs = str(row.get("observacao") or "").strip()
        if obs:
            group["observacoes"].append(obs)

    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for group in groups.values():
        customer_products: dict[str, dict[str, float]] = group.pop("_clientes_produtos")
        valid_customers = 0
        below_mix = 0
        customer_details: list[dict[str, Any]] = []

        for customer, products in customer_products.items():
            positive_products = sorted(
                product
                for product, qty in products.items()
                if extras_reads._num(qty) > 0
            )
            if len(positive_products) >= min_mix:
                valid_customers += 1
            elif positive_products:
                below_mix += 1
            customer_details.append(
                {
                    "codigoCliente": customer,
                    "produtosDistintos": len(positive_products),
                    "valido": len(positive_products) >= min_mix,
                }
            )

        group["clientesPositivadosValidos"] = valid_customers
        group["clientesComMixInsuficiente"] = below_mix
        group["minClientesPositivados"] = min_customers
        group["minProdutosPorCliente"] = min_mix
        group["quantidadeProdutosConfigurados"] = len(codes)
        group["produtosSomados"] = codes
        group["clientesAnalisados"] = len(customer_products)
        group["linhasSemCodigoCliente"] = int(group.pop("_linhas_sem_cliente", 0))
        group["elegivelRanking"] = (
            not config_error and valid_customers >= min_customers
        )
        # Não expor a lista inteira de clientes no payload público.
        # O diagnóstico agregado é suficiente para a interface.
        group["clientesDetalhadosInternos"] = customer_details

        if group["elegivelRanking"]:
            eligible.append(group)
        else:
            excluded.append(
                {
                    "colaborador": group["colaborador"],
                    "clientesPositivadosValidos": valid_customers,
                    "clientesComMixInsuficiente": below_mix,
                    "motivo": (
                        config_error
                        or f"Mínimo de {min_customers} clientes válidos não atingido."
                    ),
                }
            )

    eligible.sort(
        key=lambda row: (
            -int(row.get("clientesPositivadosValidos") or 0),
            -extras_reads._num(row.get("quantidadeProdutosSomados")),
            -extras_reads._num(row.get("venda")),
            extras_reads._flex(row.get("colaborador")),
        )
    )

    ranking_config = rule.get("rankingConfig") or []
    records: list[dict[str, Any]] = []
    for position, group in enumerate(eligible, 1):
        predicted = (
            extras_reads._ranking_prize(ranking_config, position)
            if position <= MAX_PRIZE_POSITION
            else ""
        )
        prize_text = predicted if sum_info.get("ok") else ""
        public_group = {
            key: value
            for key, value in group.items()
            if key != "clientesDetalhadosInternos"
        }
        records.append(
            {
                **public_group,
                "objetivo": min_customers,
                "atingimento": (
                    int(group.get("clientesPositivadosValidos") or 0)
                    / min_customers
                    * 100
                    if min_customers > 0
                    else 0
                ),
                "premiacao": 0,
                "premioTexto": prize_text,
                "premioPrevisto": predicted,
                "tipoPremio": METRIC,
                "posicaoRanking": position,
                "somaLaboratorio": sum_info.get("total", 0),
                "somaLaboratorioMinimo": sum_info.get("minimo", 0),
                "somaLaboratorioOK": bool(sum_info.get("ok")),
                "objetivoProdutoFoco": 0,
                "atingimentoProdutoFoco": 0,
                "codigoProdutoFoco": "",
                "metrica": METRIC,
                "status": (
                    "PREMIADO"
                    if prize_text
                    else "CLASSIFICADO"
                ),
                "statusExibicao": extras_reads._status_campaign(campaign),
                "campanha": str(campaign.get("nome") or ""),
                "campanhaId": str(campaign.get("id") or ""),
                "periodoInicio": str(campaign.get("dataInicio") or ""),
                "periodoFim": str(campaign.get("dataFim") or ""),
                "periodo": (
                    str(campaign.get("dataInicio") or "")
                    + " → "
                    + str(campaign.get("dataFim") or "")
                ),
            }
        )

    totals = {
        # Faturamento da métrica: somente os 16 produtos, incluindo pessoas
        # eliminadas pelo corte. O ranking, porém, só contém elegíveis.
        "venda": extras_reads._round2(
            sum(extras_reads._num(group.get("venda")) for group in groups.values())
        ),
        "premiacao": 0,
        "participantes": len(records),
        "premiados": sum(
            1 for row in records if str(row.get("premioTexto") or "").strip()
        ),
    }

    diagnostics = {
        "regraEntradaRanking": {
            "minClientesPositivados": min_customers,
            "minProdutosDistintosPorCliente": min_mix,
            "quantidadeProdutos": MIN_PRODUCTS,
        },
        "totalColaboradoresAnalisados": len(groups),
        "elegiveis": len(records),
        "excluidos": excluded,
        "linhasProdutosAlvo": rows_target_products,
        "linhasSemCodigoCliente": rows_without_customer,
        "posicoesPremiadas": MAX_PRIZE_POSITION,
        "somaLiberada": bool(sum_info.get("ok")),
        "erroConfiguracao": config_error,
    }

    return {
        "sucesso": True,
        "campanha": extras_reads._campaign_public(campaign),
        "registros": records,
        "totais": totals,
        "somaLaboratorio": sum_info,
        "diagnosticoRanking": diagnostics,
        "regraRankingPositivacao": diagnostics["regraEntradaRanking"],
    }


_ORIGINAL_PARTIAL = extras_reads._partial_for_campaign


def _partial_for_campaign(
    campaign: dict[str, Any],
    extras_payload: dict[str, Any],
    by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if _metric(campaign) != METRIC:
        return _ORIGINAL_PARTIAL(campaign, extras_payload, by_alias)
    return _custom_partial(campaign, extras_payload, by_alias)


def _header_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    replacements = str.maketrans(
        {"Á": "A", "À": "A", "Â": "A", "Ã": "A", "É": "E", "Ê": "E",
         "Í": "I", "Ó": "O", "Ô": "O", "Õ": "O", "Ú": "U", "Ç": "C"}
    )
    return re.sub(r"[^A-Z0-9]+", " ", text.translate(replacements)).strip()


def _header_index(headers: list[Any], aliases: tuple[str, ...]) -> int:
    normalized = [_header_key(value) for value in headers]
    for alias in aliases:
        key = _header_key(alias)
        if key in normalized:
            return normalized.index(key)
    return -1


def _sheet_client_fields(
    rows: list[list[Any]],
    normalized_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows:
        return normalized_rows

    headers = rows[0]
    collaborator_index = _header_index(
        headers,
        ("VENDEDOR/TELEVENDA", "VENDEDOR/TELEVENDAS", "COLABORADOR", "VENDEDOR", "TELEVENDAS"),
    )
    client_code_index = _header_index(
        headers,
        ("CÓD CLIENTE", "COD CLIENTE", "CÓD. CLIENTE", "COD. CLIENTE", "CODIGO CLIENTE", "CÓDIGO CLIENTE"),
    )
    client_name_index = _header_index(
        headers,
        ("CLIENTE", "NOME CLIENTE", "RAZAO SOCIAL", "RAZÃO SOCIAL"),
    )
    if collaborator_index < 0:
        return normalized_rows
    if client_code_index < 0:
        raise RuntimeError(
            "A nova métrica exige a coluna CÓD CLIENTE na aba da campanha."
        )

    source_rows = [
        row
        for row in rows[1:]
        if str(row[collaborator_index] if len(row) > collaborator_index else "").strip()
    ]
    if len(source_rows) != len(normalized_rows):
        raise RuntimeError(
            "Não foi possível associar os clientes às linhas da campanha com segurança."
        )

    output: list[dict[str, Any]] = []
    for base, source in zip(normalized_rows, source_rows):
        item = dict(base)
        item["codigoCliente"] = str(
            source[client_code_index]
            if len(source) > client_code_index and source[client_code_index] is not None
            else ""
        ).strip()
        item["cliente"] = str(
            source[client_name_index]
            if client_name_index >= 0
            and len(source) > client_name_index
            and source[client_name_index] is not None
            else ""
        ).strip()
        output.append(item)
    return output


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _route_for(app: Any, path: str, method: str) -> APIRoute | None:
    wanted = method.upper()
    for route in list(app.router.routes):
        if isinstance(route, APIRoute) and route.path == path and wanted in route.methods:
            return route
    return None


def _build_sheets_service():
    from .industries_stock_sync import _service_account_info

    info = _service_account_info()
    if not info:
        raise RuntimeError("Credencial Google da DISMEPE não está configurada.")
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError("Dependências do Google Sheets não estão instaladas.") from exc

    credentials = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _ensure_metric_sheet(campaign: dict[str, Any]) -> dict[str, Any]:
    from . import prod597_app as prod597

    spreadsheet_id = str(prod597.EXTRAS_SHEET_ID or "").strip()
    sheet_name = str(campaign.get("aba") or campaign.get("id") or "").strip()
    if not spreadsheet_id or not sheet_name:
        raise RuntimeError("Base ou aba da Campanha Extra não informada.")

    service = _build_sheets_service()
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title))",
    ).execute(num_retries=3)
    sheets = metadata.get("sheets") or []
    existing = next(
        (
            item
            for item in sheets
            if str((item.get("properties") or {}).get("title") or "") == sheet_name
        ),
        None,
    )

    if existing is None:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": sheet_name,
                                "gridProperties": {"rowCount": 1000, "columnCount": 10},
                            }
                        }
                    }
                ]
            },
        ).execute(num_retries=3)

    header_range = "'" + sheet_name.replace("'", "''") + "'!A1:J1"
    current = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=header_range,
    ).execute(num_retries=3)
    values = current.get("values") or [[]]
    headers = list(values[0] if values else [])
    while len(headers) < 10:
        headers.append("")

    expected = [
        "NOME DA CAMPANHA",
        "VENDEDOR/TELEVENDA",
        "FORNECEDOR",
        "DATA",
        "VENDA LÍQUIDA",
        "CÓD PROD",
        "TOTAL DE UNIDADE",
        "OBSERVAÇÃO",
        "CÓD CLIENTE",
        "CLIENTE",
    ]

    # As oito primeiras colunas são a estrutura oficial já existente. Em uma
    # aba nova podemos gravá-las; numa aba existente não sobrescrevemos dados
    # nem cabeçalhos desconhecidos.
    if not any(str(value or "").strip() for value in headers[:8]):
        headers[:8] = expected[:8]
    else:
        first = [_header_key(value) for value in headers[:8]]
        wanted = [_header_key(value) for value in expected[:8]]
        if first != wanted:
            raise RuntimeError(
                "A aba da campanha possui cabeçalho incompatível; nenhuma coluna foi alterada."
            )

    code_index = _header_index(headers, ("CÓD CLIENTE", "COD CLIENTE", "CODIGO CLIENTE"))
    if code_index < 0:
        if str(headers[8] or "").strip():
            raise RuntimeError(
                "A coluna I já está ocupada e não existe CÓD CLIENTE na aba."
            )
        headers[8] = "CÓD CLIENTE"

    name_index = _header_index(headers, ("CLIENTE", "NOME CLIENTE", "RAZAO SOCIAL"))
    if name_index < 0 and not str(headers[9] or "").strip():
        headers[9] = "CLIENTE"

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=header_range,
        valueInputOption="RAW",
        body={"values": [headers[:10]]},
    ).execute(num_retries=3)

    return {
        "aba": sheet_name,
        "colunaCliente": "CÓD CLIENTE",
        "colunaNomeCliente": "CLIENTE",
    }


def install_extras_positivacao_ranking(app: Any) -> None:
    if getattr(app.state, "extras_positivacao_ranking_installed", False):
        return
    app.state.extras_positivacao_ranking_installed = True

    from . import prod597_app as prod597

    extras_reads._partial_for_campaign = _partial_for_campaign

    original_sheet_records = prod597._extra_sheet_records

    async def enhanced_sheet_records(
        campaign: dict[str, Any],
        workbook_cache: dict[str, bytes],
    ) -> list[dict[str, Any]]:
        normalized = await original_sheet_records(campaign, workbook_cache)
        if _metric(campaign) != METRIC:
            return normalized

        spreadsheet_id = prod597._extra_sheet_id(campaign)
        raw_xlsx = workbook_cache.get(spreadsheet_id)
        if raw_xlsx is None:
            return normalized
        sheet_name = str(campaign.get("aba") or campaign.get("id") or "").strip()
        rows = await __import__("asyncio").to_thread(
            prod597._read_sheet,
            raw_xlsx,
            sheet_name,
        )
        return _sheet_client_fields(rows, normalized)

    prod597._extra_sheet_records = enhanced_sheet_records

    save_route = _route_for(app, "/admin/campanhas-extras/save", "POST")
    if save_route is not None:
        original_save = save_route.endpoint

        async def save_extra_campaign_with_positivity(
            payload: dict,
            session: str | None = None,
        ):
            campaign = payload.get("campanha")
            if isinstance(campaign, dict) and _metric(campaign) == METRIC:
                campaign = _validated_campaign(campaign)
                payload = dict(payload)
                payload["campanha"] = campaign

            result = await _await_if_needed(
                original_save(payload=payload, session=session)
            )

            if isinstance(campaign, dict) and _metric(campaign) == METRIC:
                try:
                    base = await __import__("asyncio").to_thread(
                        _ensure_metric_sheet,
                        campaign,
                    )
                    if isinstance(result, dict):
                        result = dict(result)
                        result["basePositivacao"] = base
                except Exception as exc:
                    if isinstance(result, dict):
                        result = dict(result)
                        result["avisoBasePositivacao"] = (
                            "A campanha foi salva, mas não foi possível preparar "
                            "automaticamente as colunas CÓD CLIENTE/CLIENTE: "
                            + str(exc)
                        )
            return result

        # Mantém a posição original da rota no FastAPI para não alterar o
        # roteamento do portal. O objeto Dependants já resolve payload/session.
        save_route.endpoint = save_extra_campaign_with_positivity
        save_route.dependant.call = save_extra_campaign_with_positivity

    script_route = _route_for(app, "/update-center-prod4.js", "GET")
    if script_route is not None:
        original_script = script_route.endpoint

        async def update_center_with_positivity_metric():
            base_response = await _await_if_needed(original_script())
            base_content = getattr(base_response, "body", b"")
            if isinstance(base_content, bytes):
                base_text = base_content.decode("utf-8")
            else:
                base_text = str(base_content or "")
            patch = FRONTEND_PATCH.read_text(encoding="utf-8")
            headers = {
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-DISMEPE-Extras-Positivacao": "RANKING_POSITIVACAO_PRODUTOS_V1",
            }
            return Response(
                content=base_text + "\n\n" + patch,
                media_type="application/javascript",
                headers=headers,
            )

        script_route.endpoint = update_center_with_positivity_metric
        script_route.dependant.call = update_center_with_positivity_metric
