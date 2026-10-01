from __future__ import annotations

import copy
import inspect
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Response
from fastapi.routing import APIRoute

from . import extras_reads
from .security import decode_session_token


METRIC = "RANKING_MANUAL"
FRONTEND_PATCH = Path(__file__).resolve().parents[1] / "frontend" / "extras-manual-ranking.js"


def _metric(campaign: dict[str, Any]) -> str:
    return str(campaign.get("metrica") or "").strip().upper()


def _rule(campaign: dict[str, Any]) -> dict[str, Any]:
    return campaign.get("regra") if isinstance(campaign.get("regra"), dict) else {}


def _money(value: Any) -> float:
    return round(max(0.0, extras_reads._num(value)), 2)


def _manual_rows(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _rule(campaign).get("rankingManual")
    if not isinstance(raw, list):
        raw = campaign.get("rankingManual")
    if not isinstance(raw, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            position = int(extras_reads._num(item.get("posicao") or item.get("position")))
        except (TypeError, ValueError):
            position = 0
        collaborator = str(
            item.get("colaborador")
            or item.get("vendedor")
            or item.get("usuario")
            or item.get("nome")
            or ""
        ).strip()
        prize = _money(item.get("premiacao") if "premiacao" in item else item.get("valor"))
        if position > 0 and collaborator:
            rows.append(
                {
                    "posicao": position,
                    "colaborador": collaborator,
                    "premiacao": prize,
                }
            )
    rows.sort(key=lambda row: (row["posicao"], extras_reads._flex(row["colaborador"])))
    return rows


def _validated_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    if _metric(campaign) != METRIC:
        return campaign

    rows = _manual_rows(campaign)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="Informe pelo menos uma posição no Ranking Manual.",
        )

    positions: set[int] = set()
    collaborators: set[str] = set()
    for row in rows:
        position = int(row["posicao"])
        collaborator_key = extras_reads._flex(row["colaborador"])
        if position in positions:
            raise HTTPException(
                status_code=400,
                detail=f"A posição {position}º está repetida no Ranking Manual.",
            )
        if collaborator_key in collaborators:
            raise HTTPException(
                status_code=400,
                detail=f"{row['colaborador']} aparece mais de uma vez no Ranking Manual.",
            )
        if row["premiacao"] <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Informe uma premiação maior que zero para o {position}º lugar.",
            )
        positions.add(position)
        collaborators.add(collaborator_key)

    expected = list(range(1, max(positions) + 1))
    if sorted(positions) != expected:
        raise HTTPException(
            status_code=400,
            detail="As posições do Ranking Manual devem ser sequenciais a partir do 1º lugar.",
        )

    normalized = copy.deepcopy(campaign)
    rule = dict(_rule(normalized))
    rule["rankingManual"] = rows
    rule["fonteResultado"] = "MANUAL"
    rule["premiacaoVisivelUsuarios"] = False
    normalized["regra"] = rule
    normalized["tipoPremiacao"] = "RANKING_MANUAL_DINHEIRO"
    normalized["aba"] = str(normalized.get("aba") or "").strip()
    return normalized


def _manual_partial(
    campaign: dict[str, Any],
    _extras_payload: dict[str, Any],
    by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = _manual_rows(campaign)
    records: list[dict[str, Any]] = []
    for row in rows:
        collaborator = row["colaborador"]
        channel, _aliases = extras_reads._collaborator_info(collaborator, by_alias)
        position = int(row["posicao"])
        prize = _money(row["premiacao"])
        records.append(
            {
                "colaborador": collaborator,
                "setor": channel,
                "laboratorio": str(campaign.get("laboratorio") or ""),
                "venda": 0.0,
                "objetivo": 0.0,
                "atingimento": 0.0,
                "premiacao": prize,
                "premioTexto": "",
                "tipoPremio": "VALOR_FIXO",
                "posicaoRanking": position,
                "metrica": METRIC,
                "status": "PREMIADO",
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
                "resultadoManual": True,
                "fonteResultado": "MANUAL",
            }
        )

    return {
        "sucesso": True,
        "campanha": extras_reads._campaign_public(campaign),
        "registros": records,
        "totais": {
            "venda": 0.0,
            "premiacao": round(sum(_money(row["premiacao"]) for row in rows), 2),
            "participantes": len(records),
            "premiados": len(records),
        },
        "somaLaboratorio": {
            "exige": False,
            "total": 0.0,
            "minimo": 0.0,
            "ok": True,
            "fonte": "RANKING_MANUAL_SQL",
            "registros": len(records),
        },
        "diagnosticoRanking": {
            "fonte": "MANUAL",
            "posicoes": len(records),
            "premiacaoVisivelUsuarios": False,
        },
    }


def _sanitize_campaign(campaign: Any) -> Any:
    if not isinstance(campaign, dict) or _metric(campaign) != METRIC:
        return campaign
    out = copy.deepcopy(campaign)
    rule = out.get("regra") if isinstance(out.get("regra"), dict) else {}
    rows = rule.get("rankingManual") if isinstance(rule.get("rankingManual"), list) else []
    public_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        position = int(extras_reads._num(row.get("posicao")) or 0)
        collaborator = str(row.get("colaborador") or "").strip()
        if position > 0 and collaborator:
            public_rows.append({"posicao": position, "colaborador": collaborator})
    clean_rule = dict(rule)
    clean_rule.pop("rankingManual", None)
    clean_rule.pop("rankingConfig", None)
    clean_rule["rankingPublico"] = public_rows
    clean_rule["premiacaoVisivelUsuarios"] = False
    out["regra"] = clean_rule
    out.pop("rankingManual", None)
    return out


def _sanitize_public_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    out = copy.deepcopy(result)

    campaigns = out.get("campanhas")
    if isinstance(campaigns, list):
        out["campanhas"] = [_sanitize_campaign(item) for item in campaigns]
    all_campaigns = out.get("todas")
    if isinstance(all_campaigns, list):
        out["todas"] = [_sanitize_campaign(item) for item in all_campaigns]
    if isinstance(out.get("campanha"), dict):
        out["campanha"] = _sanitize_campaign(out["campanha"])

    manual_prize_removed = 0.0
    records = out.get("registros")
    if isinstance(records, list):
        cleaned = []
        for item in records:
            if not isinstance(item, dict):
                cleaned.append(item)
                continue
            row = dict(item)
            if str(row.get("metrica") or "").strip().upper() == METRIC:
                manual_prize_removed += extras_reads._num(row.get("premiacao"))
                row["premiacao"] = 0.0
                row.pop("premioTexto", None)
                row.pop("premioPrevisto", None)
                row.pop("valorPremio", None)
                row["premiacaoOculta"] = True
            cleaned.append(row)
        out["registros"] = cleaned

    totals = out.get("totais")
    if isinstance(totals, dict) and manual_prize_removed:
        totals = dict(totals)
        totals["premiacao"] = max(
            0.0,
            round(extras_reads._num(totals.get("premiacao")) - manual_prize_removed, 2),
        )
        out["totais"] = totals
    return out


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _route_for(app: Any, path: str, method: str) -> APIRoute | None:
    wanted = method.upper()
    for route in list(app.router.routes):
        if isinstance(route, APIRoute) and route.path == path and wanted in route.methods:
            return route
    return None


def install_extras_manual_ranking(app: Any) -> None:
    if getattr(app.state, "extras_manual_ranking_installed", False):
        return
    app.state.extras_manual_ranking_installed = True

    from . import main as main_module
    from . import prod597_app as prod597

    previous_partial = extras_reads._partial_for_campaign

    def partial_for_campaign(
        campaign: dict[str, Any],
        extras_payload: dict[str, Any],
        by_alias: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if _metric(campaign) == METRIC:
            return _manual_partial(campaign, extras_payload, by_alias)
        return previous_partial(campaign, extras_payload, by_alias)

    extras_reads._partial_for_campaign = partial_for_campaign

    previous_sheet_records = prod597._extra_sheet_records

    async def sheet_records(
        campaign: dict[str, Any],
        workbook_cache: dict[str, bytes],
    ) -> list[dict[str, Any]]:
        if _metric(campaign) == METRIC:
            return []
        return await previous_sheet_records(campaign, workbook_cache)

    prod597._extra_sheet_records = sheet_records

    save_route = _route_for(app, "/admin/campanhas-extras/save", "POST")
    if save_route is not None:
        previous_save = save_route.endpoint

        async def save_manual_ranking(payload: dict, session: str | None = None):
            campaign = payload.get("campanha")
            if isinstance(campaign, dict) and _metric(campaign) == METRIC:
                campaign = _validated_campaign(campaign)
                payload = dict(payload)
                payload["campanha"] = campaign
            return await _await_if_needed(previous_save(payload=payload, session=session))

        save_route.endpoint = save_manual_ranking
        save_route.dependant.call = save_manual_ranking

    public_route = _route_for(app, "/data/campanhas-extras", "GET")
    if public_route is not None:
        previous_public = public_route.endpoint

        async def public_manual_ranking(
            id: str = "LIST",
            session: str | None = None,
        ):
            result = await _await_if_needed(previous_public(id=id, session=session))
            if not session:
                return result
            try:
                profile = decode_session_token(
                    session,
                    secret=main_module.settings.jwt_secret,
                    issuer=main_module.settings.jwt_issuer,
                )
            except Exception:
                return result
            if extras_reads._management_extra(profile):
                return result
            return _sanitize_public_result(result)

        public_route.endpoint = public_manual_ranking
        public_route.dependant.call = public_manual_ranking
        main_module.campanhas_extras_snapshot = public_manual_ranking

    script_route = _route_for(app, "/update-center-prod4.js", "GET")
    if script_route is not None:
        previous_script = script_route.endpoint

        async def update_center_with_manual_ranking():
            base_response = await _await_if_needed(previous_script())
            body = getattr(base_response, "body", b"")
            base_text = body.decode("utf-8") if isinstance(body, bytes) else str(body or "")
            patch = FRONTEND_PATCH.read_text(encoding="utf-8")
            return Response(
                content=base_text + "\n\n" + patch,
                media_type="application/javascript",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "X-DISMEPE-Extras-Manual-Ranking": "RANKING_MANUAL_V1",
                },
            )

        script_route.endpoint = update_center_with_manual_ranking
        script_route.dependant.call = update_center_with_manual_ranking
