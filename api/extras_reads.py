from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .security import normalizar


def _num(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        if isinstance(value, str):
            text = value.strip().replace("R$", "").replace(" ", "")
            if "," in text and "." in text:
                text = text.replace(".", "").replace(",", ".")
            elif "," in text:
                text = text.replace(",", ".")
            value = text
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _round2(value: Any) -> float:
    return round(_num(value), 2)


def _role(value: Any) -> str:
    return normalizar(value or "")


def _flex(value: Any) -> str:
    text = normalizar(value or "")
    text = re.sub(
        r"\s*[\(\[]\s*(VENDEDOR(?:A)?|TELEVENDAS|TELEVENDEDOR(?:A)?)\s*[\)\]]\s*$",
        "",
        text,
    )
    text = re.sub(
        r"\s*[-–—|/]\s*(VENDEDOR(?:A)?|TELEVENDAS|TELEVENDEDOR(?:A)?)\s*$",
        "",
        text,
    )
    text = re.sub(r"^\s*\d+[\s._-]*", "", text)
    text = re.sub(
        r"\b(VENDEDOR(?:A)?|TELEVENDAS|TELEVENDEDOR(?:A)?)\b",
        " ",
        text,
    )
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _aliases(*values: Any) -> set[str]:
    out: set[str] = set()
    for value in values:
        raw = normalizar(value or "").strip()
        flex = _flex(value)
        if raw:
            out.add(raw)
        if flex:
            out.add(flex)
    return out


def _status_campaign(c: dict[str, Any]) -> str:
    if str(c.get("status") or "").upper() == "OCULTA":
        return "OCULTA"

    today = datetime.now(ZoneInfo("America/Recife")).strftime("%Y-%m-%d")
    ini = str(c.get("dataInicio") or "")[:10]
    fim = str(c.get("dataFim") or "")[:10]

    if ini and today < ini:
        return "AGENDADA"
    if fim and today > fim:
        return "ENCERRADA"
    return "ATIVA"


def _campaign_public(c: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(c)
    out["statusExibicao"] = _status_campaign(out)
    out["idCampanhaExibicao"] = str(out.get("id") or "")
    return out


def _list_aliases(values: Any) -> set[str]:
    result: set[str] = set()
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict):
            value = (
                value.get("usuario")
                or value.get("login")
                or value.get("nome")
                or value.get("vendedor")
                or ""
            )
        result |= _aliases(value)
    return result


def _management_extra(profile: dict[str, Any]) -> bool:
    if _role(profile.get("tipo")) == "ADMINISTRADOR":
        return True
    perms = profile.get("permissoes")
    if not isinstance(perms, dict):
        return False
    return any(
        perms.get(key) is True
        for key in (
            "CAMPANHAS_EXTRAS_CRIAR",
            "CAMPANHAS_EXTRAS_EDITAR",
            "CAMPANHAS_EXTRAS_ATIVAR_OCULTAR",
            "CAMPANHAS_EXTRAS_EXCLUIR",
            "CAMPANHAS_EXTRAS_OBSERVACAO",
        )
    )


def _can_view(profile: dict[str, Any]) -> bool:
    if _role(profile.get("tipo")) == "ADMINISTRADOR":
        return True
    perms = profile.get("permissoes")
    return isinstance(perms, dict) and perms.get("CAMPANHAS_EXTRAS_VISUALIZAR") is True


def _build_user_aliases(
    users_payload: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    by_alias: dict[str, dict[str, Any]] = {}
    aliases_by_user: dict[str, set[str]] = {}

    users = (
        users_payload.get("usuarios")
        if isinstance(users_payload, dict)
        and isinstance(users_payload.get("usuarios"), list)
        else []
    )

    for row in users:
        if not isinstance(row, dict):
            continue
        aliases = _aliases(
            row.get("usuario"),
            row.get("nome"),
            row.get("vendedor"),
        )
        if not aliases:
            continue
        canonical = normalizar(row.get("usuario") or row.get("vendedor") or row.get("nome") or "")
        aliases_by_user[canonical] = aliases
        for alias in aliases:
            by_alias[alias] = row

    return by_alias, aliases_by_user


def _identity_aliases(
    profile: dict[str, Any],
    by_alias: dict[str, dict[str, Any]],
) -> set[str]:
    aliases = _aliases(
        profile.get("usuario"),
        profile.get("nome"),
        profile.get("vendedor"),
    )
    matched = None
    for alias in list(aliases):
        if alias in by_alias:
            matched = by_alias[alias]
            break
    if matched:
        aliases |= _aliases(
            matched.get("usuario"),
            matched.get("nome"),
            matched.get("vendedor"),
        )
    return aliases


def _campaign_except(
    campaign: dict[str, Any],
    aliases: set[str],
) -> bool:
    return bool(
        aliases
        & (
            _list_aliases(campaign.get("vendedoresExceto"))
            | _list_aliases(campaign.get("televendasExceto"))
        )
    )


def _visible_campaign(
    campaign: dict[str, Any],
    profile: dict[str, Any],
    aliases: set[str],
) -> bool:
    if _status_campaign(campaign) == "OCULTA":
        return False
    if _campaign_except(campaign, aliases):
        return False

    role = _role(profile.get("tipo"))
    if role not in {"VENDEDOR", "TELEVENDAS"}:
        return _management_extra(profile)

    mode = str(
        campaign.get(
            "televendasModo" if role == "TELEVENDAS" else "vendedoresModo"
        )
        or "TODOS"
    ).upper()

    if mode == "OCULTO":
        return False
    if mode == "EXCETO":
        return not _campaign_except(campaign, aliases)
    return True


def _is_management_person(value: Any) -> bool:
    name = normalizar(value or "")
    return any(
        marker in name
        for marker in (
            "DIRETORIA",
            "DIRETOR ",
            "SUPERVISAO",
            "SUPERVISOR",
            "SUP VENDAS",
            "SUP TELEVENDAS",
            "GERENCIA",
            "GERENTE ",
        )
    )


def _collaborator_info(
    value: Any,
    by_alias: dict[str, dict[str, Any]],
) -> tuple[str, set[str]]:
    raw = str(value or "").strip()
    aliases = _aliases(raw)
    row = None

    for alias in aliases:
        if alias in by_alias:
            row = by_alias[alias]
            break

    if row:
        aliases |= _aliases(
            row.get("usuario"),
            row.get("nome"),
            row.get("vendedor"),
        )
        role = _role(row.get("perfil") or row.get("tipo"))
        if role == "TELEVENDAS":
            return "Televendas", aliases
        if role == "VENDEDOR":
            return "Vendedor", aliases

    upper = normalizar(raw)
    if "TELEVENDAS" in upper or "TELEVENDEDOR" in upper:
        return "Televendas", aliases
    if "VENDEDOR" in upper or "VENDEDORA" in upper:
        return "Vendedor", aliases

    return "Vendedor/Televendas", aliases


def _mode_allows(mode: Any, excluded: Any, aliases: set[str]) -> bool:
    mode = str(mode or "TODOS").upper()
    if mode == "OCULTO":
        return False
    if mode == "EXCETO" and aliases & _list_aliases(excluded):
        return False
    return True


def _collaborator_allowed(
    campaign: dict[str, Any],
    collaborator: Any,
    channel: str,
    aliases: set[str],
) -> bool:
    if not str(collaborator or "").strip() or _is_management_person(collaborator):
        return False

    # EXCETO soberano.
    if aliases & (
        _list_aliases(campaign.get("vendedoresExceto"))
        | _list_aliases(campaign.get("televendasExceto"))
    ):
        return False

    if channel == "Televendas":
        return _mode_allows(
            campaign.get("televendasModo"),
            campaign.get("televendasExceto"),
            aliases,
        )
    if channel == "Vendedor":
        return _mode_allows(
            campaign.get("vendedoresModo"),
            campaign.get("vendedoresExceto"),
            aliases,
        )

    return (
        _mode_allows(
            campaign.get("vendedoresModo"),
            campaign.get("vendedoresExceto"),
            aliases,
        )
        or _mode_allows(
            campaign.get("televendasModo"),
            campaign.get("televendasExceto"),
            aliases,
        )
    )


def _lab_base(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"\s*[-–—]?\s*PROD\.?\s*FOCO.*$",
        "",
        text,
        flags=re.I,
    )
    return normalizar(text).strip()


def _row_matches_campaign(campaign: dict[str, Any], row: dict[str, Any]) -> bool:
    camp = _lab_base(campaign.get("laboratorio"))
    line = _lab_base(row.get("laboratorio"))
    if not camp or not line:
        return True
    return camp == line


def _filtered_sales(campaign: dict[str, Any], sales: list[Any]) -> list[dict[str, Any]]:
    ini = str(campaign.get("dataInicio") or "0000-00-00")
    fim = str(campaign.get("dataFim") or "9999-99-99")
    out = []

    for row in sales:
        if not isinstance(row, dict):
            continue
        date = str(row.get("data") or "")
        if date and (date < ini or date > fim):
            continue
        if not _row_matches_campaign(campaign, row):
            continue
        out.append(row)

    return out


def _sum_lab(campaign: dict[str, Any], sales: list[dict[str, Any]]) -> dict[str, Any]:
    total = _round2(sum(_num(x.get("venda")) for x in sales))
    rule = campaign.get("regra") if isinstance(campaign.get("regra"), dict) else {}
    minimum = _num(rule.get("somaLabMinimo"))
    required = rule.get("exigeSomaLaboratorio") is True
    return {
        "exige": required,
        "total": total,
        "minimo": minimum,
        "ok": (not required) or total >= minimum,
        "fonte": "SNAPSHOT_EXTRAS_POSTGRESQL",
        "aba": str(campaign.get("aba") or ""),
        "registros": len(sales),
    }


def _ranking_config(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = max(
            1,
            int(
                _num(
                    item.get("inicio")
                    or item.get("de")
                    or item.get("posicaoInicio")
                    or item.get("posicao")
                    or 0
                )
            ),
        )
        end = max(
            start,
            int(
                _num(
                    item.get("fim")
                    or item.get("ate")
                    or item.get("posicaoFim")
                    or start
                )
            ),
        )
        gift = str(
            item.get("brinde")
            or item.get("premio")
            or item.get("nome")
            or ""
        ).strip()
        if gift:
            out.append({"inicio": start, "fim": end, "brinde": gift})
    out.sort(key=lambda x: (x["inicio"], x["fim"]))
    return out


def _ranking_prize(config: Any, position: int) -> str:
    for row in _ranking_config(config):
        if row["inicio"] <= position <= row["fim"]:
            return str(row["brinde"])
    return ""


def _calculate_prize(
    campaign: dict[str, Any],
    sale: float,
    focus_qty: float,
    sum_lab: float,
) -> dict[str, Any]:
    objective = _num(campaign.get("objetivo"))
    objective_focus = _num(campaign.get("objetivoProdutoFoco"))
    sale = _num(sale)
    focus_qty = _num(focus_qty)

    hit = (sale / objective * 100) if objective > 0 else 0
    hit_focus = (
        focus_qty / objective_focus * 100
        if objective_focus > 0
        else 0
    )

    rule = campaign.get("regra") if isinstance(campaign.get("regra"), dict) else {}
    metric = str(campaign.get("metrica") or "META_FATURAMENTO").upper()
    if metric == "COMBINADA":
        metric = "PRODUTO_FOCO"

    required_sum = rule.get("exigeSomaLaboratorio") is True
    sum_min = _num(rule.get("somaLabMinimo"))
    sum_ok = (not required_sum) or _num(sum_lab) >= sum_min

    prize = 0.0
    prize_text = ""

    if not sum_ok:
        return {
            "objetivo": objective,
            "venda": sale,
            "atingimento": hit,
            "quantidadeProdutoFoco": focus_qty,
            "objetivoProdutoFoco": objective_focus,
            "atingimentoProdutoFoco": hit_focus,
            "premiacao": 0,
            "premioTexto": "",
            "tipoPremio": "",
            "somaLaboratorio": _num(sum_lab),
            "somaLaboratorioMinimo": sum_min,
            "somaLaboratorioOK": False,
        }

    if metric == "PERCENTUAL_OBJETIVO":
        prize = (
            objective * (_num(rule.get("percentual")) / 100)
            if hit >= 100
            else 0
        )
    elif metric == "PERCENTUAL_VENDA":
        prize = (
            sale * (_num(rule.get("percentual")) / 100)
            if hit >= 100
            else 0
        )
    elif metric == "FAIXAS_FATURAMENTO":
        valid = []
        for band in rule.get("faixas") or []:
            if not isinstance(band, dict):
                continue
            minimum = _num(band.get("min"))
            amount = _num(band.get("premio"))
            if minimum > 0 and amount >= 0 and sale >= minimum:
                valid.append((minimum, amount))
        prize = max(valid, default=(0, 0), key=lambda x: x[0])[1]
    elif metric == "PRODUTO_FOCO":
        prize = (
            _num(rule.get("valor"))
            if objective > 0
            and sale >= objective
            and objective_focus > 0
            and focus_qty >= objective_focus
            else 0
        )
    elif metric == "BRINDE":
        if objective <= 0 or sale >= objective:
            prize_text = str(rule.get("premioTexto") or "").strip()
    elif metric != "RANKING_BRINDE":
        prize = _num(rule.get("valor")) if hit >= 100 else 0

    return {
        "objetivo": objective,
        "venda": sale,
        "atingimento": hit,
        "quantidadeProdutoFoco": focus_qty,
        "objetivoProdutoFoco": objective_focus,
        "atingimentoProdutoFoco": hit_focus,
        "premiacao": _round2(prize),
        "premioTexto": prize_text,
        "tipoPremio": "BRINDE" if prize_text else "",
        "somaLaboratorio": _num(sum_lab),
        "somaLaboratorioMinimo": sum_min,
        "somaLaboratorioOK": sum_ok,
    }


def _campaign_sales(payload: dict[str, Any], campaign_id: str) -> list[dict[str, Any]]:
    store = (
        payload.get("vendasPorCampanha")
        if isinstance(payload.get("vendasPorCampanha"), dict)
        else {}
    )
    hit = store.get(str(campaign_id))
    if isinstance(hit, list):
        return [x for x in hit if isinstance(x, dict)]
    if isinstance(hit, dict):
        if hit.get("erro"):
            raise ValueError(str(hit.get("erro")))
        rows = hit.get("registros")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _partial_for_campaign(
    campaign: dict[str, Any],
    extras_payload: dict[str, Any],
    by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sales = _filtered_sales(
        campaign,
        _campaign_sales(extras_payload, str(campaign.get("id") or "")),
    )
    sum_info = _sum_lab(campaign, sales)
    metric = str(campaign.get("metrica") or "").upper()
    if metric == "COMBINADA":
        metric = "PRODUTO_FOCO"

    focus_code = str(campaign.get("codigoProdutoFoco") or "").strip().upper()
    groups: dict[str, dict[str, Any]] = {}

    for row in sales:
        collaborator = str(row.get("colaborador") or "").strip()
        key = _flex(collaborator)
        if not key:
            continue

        channel, aliases = _collaborator_info(collaborator, by_alias)

        if not _collaborator_allowed(
            campaign,
            collaborator,
            channel,
            aliases,
        ):
            continue

        group = groups.setdefault(
            key,
            {
                "colaborador": collaborator,
                "setor": channel,
                "laboratorio": str(campaign.get("laboratorio") or ""),
                "venda": 0.0,
                "quantidadeProdutoFoco": 0.0,
                "observacoes": [],
            },
        )

        group["venda"] += _num(row.get("venda"))

        if (
            metric == "PRODUTO_FOCO"
            and str(row.get("codigoProduto") or "").strip().upper() == focus_code
        ):
            group["quantidadeProdutoFoco"] += _num(row.get("quantidade"))

        obs = str(row.get("observacao") or "").strip()
        if obs:
            group["observacoes"].append(obs)

    records: list[dict[str, Any]] = []
    diagnostics = None

    if metric == "RANKING_BRINDE":
        eligible = sorted(
            groups.values(),
            key=lambda x: (-_num(x.get("venda")), str(x.get("colaborador") or "")),
        )
        config = (
            campaign.get("regra", {}).get("rankingConfig")
            if isinstance(campaign.get("regra"), dict)
            else []
        )

        diagnostics = {
            "totalLinhasAgrupadas": len(groups),
            "elegiveis": len(eligible),
            "ignorados": [],
            "naoClassificados": [
                x["colaborador"]
                for x in eligible
                if x.get("setor") == "Vendedor/Televendas"
            ],
            "posicoesConfiguradas": len(_ranking_config(config)),
            "somaLiberada": sum_info["ok"],
            "ganhadoresPrevistos": sum(
                1
                for i, _ in enumerate(eligible, 1)
                if _ranking_prize(config, i)
            ),
        }

        for position, group in enumerate(eligible, 1):
            predicted = _ranking_prize(config, position)
            prize_text = predicted if sum_info["ok"] else ""
            records.append(
                {
                    **group,
                    "objetivo": 0,
                    "atingimento": 0,
                    "premiacao": 0,
                    "premioTexto": prize_text,
                    "premioPrevisto": predicted,
                    "tipoPremio": "RANKING_BRINDE",
                    "posicaoRanking": position,
                    "somaLaboratorio": sum_info["total"],
                    "somaLaboratorioMinimo": sum_info["minimo"],
                    "somaLaboratorioOK": sum_info["ok"],
                    "objetivoProdutoFoco": 0,
                    "atingimentoProdutoFoco": 0,
                    "codigoProdutoFoco": "",
                    "metrica": metric,
                    "status": "PREMIADO" if prize_text else "EM ANDAMENTO",
                    "statusExibicao": _status_campaign(campaign),
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
    else:
        for group in groups.values():
            calc = _calculate_prize(
                campaign,
                _num(group.get("venda")),
                _num(group.get("quantidadeProdutoFoco")),
                _num(sum_info.get("total")),
            )
            records.append(
                {
                    **group,
                    **calc,
                    "setor": group.get("setor"),
                    "status": (
                        "PREMIADO"
                        if _num(calc.get("premiacao")) > 0
                        or str(calc.get("premioTexto") or "").strip()
                        else "EM ANDAMENTO"
                    ),
                    "statusExibicao": _status_campaign(campaign),
                    "campanha": str(campaign.get("nome") or ""),
                    "campanhaId": str(campaign.get("id") or ""),
                    "metrica": metric,
                    "codigoProdutoFoco": str(
                        campaign.get("codigoProdutoFoco") or ""
                    ),
                    "periodoInicio": str(campaign.get("dataInicio") or ""),
                    "periodoFim": str(campaign.get("dataFim") or ""),
                    "periodo": (
                        str(campaign.get("dataInicio") or "")
                        + " → "
                        + str(campaign.get("dataFim") or "")
                    ),
                }
            )

        records.sort(
            key=lambda x: -_num(x.get("venda"))
        )

    totals = {
        "venda": _round2(sum(_num(x.get("venda")) for x in records)),
        "premiacao": _round2(sum(_num(x.get("premiacao")) for x in records)),
        "participantes": len(records),
        "premiados": sum(
            1
            for x in records
            if _num(x.get("premiacao")) > 0
            or str(x.get("premioTexto") or "").strip()
        ),
    }

    return {
        "sucesso": True,
        "campanha": _campaign_public(campaign),
        "registros": records,
        "totais": totals,
        "somaLaboratorio": sum_info,
        "diagnosticoRanking": diagnostics,
    }


def extras_api_response(
    *,
    extras_payload: dict[str, Any],
    users_payload: dict[str, Any],
    profile: dict[str, Any],
    campaign_id: str,
) -> dict[str, Any]:
    if not _can_view(profile):
        raise PermissionError(
            "Você não possui permissão para visualizar Campanhas Extras."
        )

    campaigns_all = (
        extras_payload.get("campanhas")
        if isinstance(extras_payload.get("campanhas"), list)
        else []
    )

    by_alias, _ = _build_user_aliases(users_payload)
    identity_aliases = _identity_aliases(profile, by_alias)

    visible = [
        _campaign_public(c)
        for c in campaigns_all
        if isinstance(c, dict)
        and _visible_campaign(c, profile, identity_aliases)
    ]

    if str(campaign_id or "").upper() == "LIST":
        access_total = _management_extra(profile)
        return {
            "sucesso": True,
            "campanhas": visible,
            "todas": visible if access_total else None,
            "quantidadeCampanhas": len(visible),
            "quantidadeRemovidasPorExceto": sum(
                1
                for c in campaigns_all
                if isinstance(c, dict)
                and _campaign_except(c, identity_aliases)
            ),
            "regraExcetoVersao": "V2_SQL",
            "versaoRegraExceto": "V2_SQL",
            "usuarioRegraExceto": str(profile.get("usuario") or ""),
            "transporte": "FASTAPI_EXTRAS_SNAPSHOT",
        }

    if str(campaign_id or "").upper() == "ALL":
        all_records = []
        total_sale = 0.0
        total_prize = 0.0
        participants = 0
        winners = 0

        for campaign in visible:
            partial = _partial_for_campaign(
                campaign,
                extras_payload,
                by_alias,
            )
            rows = partial["registros"]
            all_records.extend(rows)
            total_sale += _num(partial["totais"].get("venda"))
            total_prize += _num(partial["totais"].get("premiacao"))
            participants += int(partial["totais"].get("participantes") or 0)
            winners += int(partial["totais"].get("premiados") or 0)

        all_records.sort(
            key=lambda x: (
                -_num(x.get("premiacao")),
                int(x.get("posicaoRanking") or 999),
                -_num(x.get("venda")),
            )
        )

        return {
            "sucesso": True,
            "campanha": {
                "id": "ALL",
                "nome": "Todas as campanhas",
                "laboratorio": "Todos",
                "dataInicio": "",
                "dataFim": "",
                "statusExibicao": "ATIVA",
            },
            "registros": all_records,
            "totais": {
                "venda": _round2(total_sale),
                "premiacao": _round2(total_prize),
                "participantes": participants,
                "premiados": winners,
            },
            "transporte": "FASTAPI_EXTRAS_SNAPSHOT",
        }

    target = next(
        (
            c
            for c in visible
            if str(c.get("id") or "") == str(campaign_id or "")
        ),
        None,
    )

    if not target:
        raise PermissionError(
            "Campanha não disponível para este usuário."
        )

    partial = _partial_for_campaign(
        target,
        extras_payload,
        by_alias,
    )
    partial["transporte"] = "FASTAPI_EXTRAS_SNAPSHOT"
    return partial
