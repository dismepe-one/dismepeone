from __future__ import annotations

from typing import Any

from . import extras_reads
from . import extras_positivacao_ranking as ranking


METRIC = ranking.METRIC


def _metric(campaign: dict[str, Any]) -> str:
    return str(campaign.get("metrica") or "").strip().upper()


def install_extras_positivacao_partial_display(app: Any) -> None:
    if getattr(app.state, "extras_positivacao_partial_display_installed", False):
        return
    app.state.extras_positivacao_partial_display_installed = True

    current_partial = extras_reads._partial_for_campaign

    def fixed_partial(
        campaign: dict[str, Any],
        extras_payload: dict[str, Any],
        by_alias: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        result = current_partial(campaign, extras_payload, by_alias)
        if _metric(campaign) != METRIC or not isinstance(result, dict):
            return result

        min_customers = int(
            extras_reads._num(
                (campaign.get("regra") or {}).get("minClientesPositivados")
                if isinstance(campaign.get("regra"), dict)
                else 10
            )
            or 10
        )
        min_customers = max(10, min_customers)

        records_raw = result.get("registros")
        records = [dict(row) for row in records_raw] if isinstance(records_raw, list) else []
        known: set[str] = set()

        # Para esta métrica, a coluna genérica REALIZADO deve representar
        # quantidade de clientes válidos, não faturamento em reais.
        for row in records:
            collaborator = str(row.get("colaborador") or "").strip()
            key = extras_reads._flex(collaborator)
            if key:
                known.add(key)
            valid = int(extras_reads._num(row.get("clientesPositivadosValidos")) or 0)
            financial = extras_reads._num(row.get("venda"))
            row["vendaLiquida"] = extras_reads._round2(financial)
            row["realizado"] = valid
            row["venda"] = valid
            row["objetivo"] = min_customers
            row["atingimento"] = valid / min_customers * 100 if min_customers else 0

        diagnostic = result.get("diagnosticoRanking")
        excluded = diagnostic.get("excluidos") if isinstance(diagnostic, dict) else []
        if not isinstance(excluded, list):
            excluded = []

        # Primeiro inclui quem vendeu produto-alvo, mas ainda não chegou ao corte.
        for item in excluded:
            if not isinstance(item, dict):
                continue
            collaborator = str(item.get("colaborador") or "").strip()
            key = extras_reads._flex(collaborator)
            if not key or key in known:
                continue
            channel, _aliases = extras_reads._collaborator_info(collaborator, by_alias)
            valid = int(extras_reads._num(item.get("clientesPositivadosValidos")) or 0)
            records.append(
                {
                    "colaborador": collaborator,
                    "setor": channel,
                    "laboratorio": str(campaign.get("laboratorio") or ""),
                    "venda": valid,
                    "vendaLiquida": 0,
                    "realizado": valid,
                    "objetivo": min_customers,
                    "atingimento": valid / min_customers * 100 if min_customers else 0,
                    "clientesPositivadosValidos": valid,
                    "clientesComMixInsuficiente": int(
                        extras_reads._num(item.get("clientesComMixInsuficiente")) or 0
                    ),
                    "elegivelRanking": False,
                    "premiacao": 0,
                    "premioTexto": "",
                    "premioPrevisto": "",
                    "tipoPremio": METRIC,
                    "posicaoRanking": 0,
                    "metrica": METRIC,
                    "status": "NÃO ATINGIU",
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
            known.add(key)

        # Também mostra Televendas presentes na base da campanha que ainda não
        # venderam nenhum dos 16 produtos-alvo. Assim a parcial não esconde quem
        # está com realizado zero.
        raw_sales = extras_reads._campaign_sales(
            extras_payload,
            str(campaign.get("id") or ""),
        )
        sales = extras_reads._filtered_sales(campaign, raw_sales)
        for sale in sales:
            if not isinstance(sale, dict):
                continue
            collaborator = str(sale.get("colaborador") or "").strip()
            key = extras_reads._flex(collaborator)
            if not key or key in known:
                continue
            channel, aliases = extras_reads._collaborator_info(collaborator, by_alias)
            if not extras_reads._collaborator_allowed(
                campaign,
                collaborator,
                channel,
                aliases,
            ):
                continue
            records.append(
                {
                    "colaborador": collaborator,
                    "setor": channel,
                    "laboratorio": str(campaign.get("laboratorio") or ""),
                    "venda": 0,
                    "vendaLiquida": 0,
                    "realizado": 0,
                    "objetivo": min_customers,
                    "atingimento": 0,
                    "clientesPositivadosValidos": 0,
                    "clientesComMixInsuficiente": 0,
                    "elegivelRanking": False,
                    "premiacao": 0,
                    "premioTexto": "",
                    "premioPrevisto": "",
                    "tipoPremio": METRIC,
                    "posicaoRanking": 0,
                    "metrica": METRIC,
                    "status": "NÃO ATINGIU",
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
            known.add(key)

        # Elegíveis permanecem primeiro e ordenados pela posição do ranking;
        # abaixo vêm os que não atingiram, do maior realizado para o menor.
        records.sort(
            key=lambda row: (
                0 if bool(row.get("elegivelRanking")) else 1,
                int(row.get("posicaoRanking") or 9999)
                if bool(row.get("elegivelRanking"))
                else -int(row.get("clientesPositivadosValidos") or 0),
                extras_reads._flex(row.get("colaborador")),
            )
        )

        output = dict(result)
        output["registros"] = records
        totals = dict(output.get("totais") or {})
        totals["participantes"] = len(records)
        totals["elegiveis"] = sum(1 for row in records if bool(row.get("elegivelRanking")))
        totals["naoAtingiram"] = sum(1 for row in records if not bool(row.get("elegivelRanking")))
        output["totais"] = totals
        return output

    extras_reads._partial_for_campaign = fixed_partial
