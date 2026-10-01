from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from .cache_reads import CacheReadError, cache_get
from .security import decode_session_token


_INSTALLED = False


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    raw = str(value).replace("R$", "").replace(" ", "").strip()
    if not raw or raw.startswith("#"):
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        number = float(raw)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def _sector(field: str) -> str:
    return "Vendedor" if field == "dadosVendedores" else "Televendas"


def _base_lab(value: Any) -> str:
    label = _norm(value)
    label = re.sub(r"\s+PROD(?:UTO)?\s+FOCO.*$", "", label).strip()
    return label


def _is_focus(value: Any) -> bool:
    label = _norm(value)
    return "PROD FOCO" in label or "PRODUTO FOCO" in label


def _published_indexes(publication: dict[str, Any]):
    monthly = publication.get("mensal") if isinstance(publication, dict) else None
    if not isinstance(monthly, dict):
        return {}, {}

    base: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    focus: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for field in ("dadosVendedores", "dadosTelevendas"):
        rows = monthly.get(field)
        if not isinstance(rows, list):
            continue
        sector = _sector(field)
        for row in rows:
            if not isinstance(row, dict):
                continue
            person = _norm(row.get("__COLABORADOR") or row.get("colab") or row.get("colaborador"))
            lab_raw = row.get("__LAB") or row.get("lab") or row.get("laboratorio")
            lab = _base_lab(lab_raw)
            comp = str(row.get("__COMPETENCIA") or row.get("competencia") or "").strip()
            if not person or not lab or not comp:
                continue
            key = (sector, person, lab, comp)
            if _is_focus(lab_raw):
                focus[key] = row
            else:
                base[key] = row
    return base, focus


def _summary_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("setor") or "").strip(),
        _norm(item.get("colaborador")),
        _base_lab(item.get("laboratorio")),
        str(item.get("competencia") or item.get("periodo") or "").strip(),
    )


def _focus_status(focus_row: dict[str, Any] | None) -> tuple[float, float, bool]:
    if not isinstance(focus_row, dict):
        return 0.0, 0.0, False
    goal = _number(focus_row.get("__OBJETIVO") or focus_row.get("Objetivo") or focus_row.get("objetivo")) or 0.0
    actual = _number(focus_row.get("__VENDA") or focus_row.get("Venda") or focus_row.get("venda")) or 0.0
    return goal, actual, goal > 0 and actual >= goal


def _sync_normal_monthly(summary: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return summary
    records = summary.get("registros")
    if not isinstance(records, list):
        return summary

    base, focus = _published_indexes(publication)
    if not base:
        return summary

    out = copy.deepcopy(summary)
    changed = 0
    for item in out.get("registros") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tipoRegistro") or "").upper() == "CAMPANHA_EXTRA":
            continue
        current = base.get(_summary_key(item))
        if current is None:
            continue

        objective = _number(current.get("__OBJETIVO") or current.get("Objetivo") or current.get("objetivo"))
        sale = _number(current.get("__VENDA") or current.get("Venda") or current.get("venda"))
        if objective is None or sale is None:
            continue

        old_objective = _number(item.get("objetivo"))
        old_sale = _number(item.get("venda"))
        item["objetivo"] = round(objective, 4)
        item["venda"] = round(sale, 4)
        item["atingimento"] = round((sale / objective * 100.0) if objective > 0 else 0.0, 6)
        item["objetivoVendaOK"] = bool(objective > 0 and sale >= objective)

        # NATULAB usa a regra mensal normal de objetivo + produto foco. O resumo
        # antigo congelava objetivo/venda/foco no momento em que foi consolidado.
        # Reaplicamos apenas essa regra conhecida, usando a fotografia já
        # publicada nas Parciais, sem alterar a configuração da campanha.
        if _base_lab(item.get("laboratorio")) == "NATULAB":
            rule = item.get("regra") if isinstance(item.get("regra"), dict) else {}
            metric = _norm(rule.get("metrica") or item.get("metrica"))
            if metric == "OBJETIVO":
                focus_goal, focus_actual, focus_ok = _focus_status(focus.get(_summary_key(item)))
                requires_focus = rule.get("exigeFoco") is True or item.get("temFoco") is True
                if requires_focus:
                    item["temFoco"] = True
                    item["possuiLinhaFoco"] = focus_goal > 0
                    item["objetivoFoco"] = round(focus_goal, 4)
                    item["vendaFoco"] = round(focus_actual, 4)
                    item["focoOK"] = focus_ok
                    item["duploGatilhoFocoOK"] = bool(item["objetivoVendaOK"] and focus_ok)
                    item["motivoFoco"] = (
                        "Objetivo de venda + Produto Foco atingidos."
                        if item["duploGatilhoFocoOK"]
                        else "Objetivo de venda ou Produto Foco ainda não atingido."
                    )
                else:
                    item["focoOK"] = True
                    item["duploGatilhoFocoOK"] = bool(item["objetivoVendaOK"])

                minimum_objective = _number(rule.get("minAtingimento")) or 0.0
                maximum_objective = _number(rule.get("maxAtingimento"))
                objective_eligible = objective >= minimum_objective
                if maximum_objective is not None and maximum_objective > 0:
                    objective_eligible = objective_eligible and objective <= maximum_objective
                gates_ok = bool(
                    item["objetivoVendaOK"]
                    and (not requires_focus or item.get("focoOK") is True)
                    and item.get("somaLaboratorioOK", True) is not False
                    and objective_eligible
                )
                configured_prize = _number(rule.get("valor")) or 0.0
                item["premiacao"] = round(configured_prize if gates_ok else 0.0, 2)

        if old_objective != objective or old_sale != sale:
            changed += 1

    if changed:
        # Reutiliza o agregador já validado pelo overlay anterior.
        try:
            from .resumo_monthly_overlay import _rebuild_totals
            _rebuild_totals(out)
        except Exception:
            pass
        out["objetivosMensaisSincronizados"] = True
        out["linhasObjetivosSincronizadas"] = changed
    return out


def install_resumo_objective_sync(app) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import main as main_module
    from . import prod597_app as prod_module

    original_get = getattr(main_module, "resumo_ganhos_snapshot", None)
    if callable(original_get) and not getattr(original_get, "__dismepe_objective_sync__", False):
        async def wrapped_get(*args, **kwargs):
            result = await original_get(*args, **kwargs)
            try:
                publication, row = await cache_get(modulo="HOME_PUBLICATION", settings=main_module.settings)
                result = _sync_normal_monthly(result, publication)
                if isinstance(result, dict) and result.get("objetivosMensaisSincronizados"):
                    result["objetivosAtualizadosEm"] = str(row.get("atualizado_em") or "")
            except (CacheReadError, ValueError, TypeError):
                pass
            return result

        wrapped_get.__dismepe_objective_sync__ = True
        wrapped_get.__wrapped__ = original_get
        main_module.resumo_ganhos_snapshot = wrapped_get
        for route in getattr(app, "routes", []):
            if getattr(route, "path", "") == "/data/resumo-ganhos" and "GET" in (getattr(route, "methods", set()) or set()):
                route.endpoint = wrapped_get
                if getattr(route, "dependant", None) is not None:
                    route.dependant.call = wrapped_get

    original_post = getattr(prod_module, "atualizar_resumo_ganhos_manual", None)
    if callable(original_post) and not getattr(original_post, "__dismepe_objective_sync__", False):
        async def wrapped_post(session=None):
            # O fluxo oficial primeiro reconsolida Extras e demais campos.
            await original_post(session=session)
            if not session:
                return await original_post(session=session)

            persisted, _ = await cache_get(modulo="RESUMO_PREMIACOES", settings=prod_module.settings)
            publication, _ = await cache_get(modulo="HOME_PUBLICATION", settings=prod_module.settings)
            corrected = _sync_normal_monthly(persisted, publication)

            profile = decode_session_token(
                session,
                secret=prod_module.settings.jwt_secret,
                issuer=prod_module.settings.jwt_issuer,
            )
            display, iso = await prod_module._cache_set_snapshot(
                modulo="RESUMO_PREMIACOES",
                payload=corrected,
                profile=profile,
                version=prod_module.RESUMO_MANUAL_VERSION,
            )
            refreshed = await main_module.resumo_ganhos_snapshot(session=session)
            refreshed["atualizadoEm"] = iso
            refreshed["atualizadoEmFormatado"] = display
            refreshed["atualizacaoManual"] = True
            refreshed["snapshotVersao"] = prod_module.RESUMO_MANUAL_VERSION
            return refreshed

        wrapped_post.__dismepe_objective_sync__ = True
        wrapped_post.__wrapped__ = original_post
        prod_module.atualizar_resumo_ganhos_manual = wrapped_post
        for route in getattr(app, "routes", []):
            if getattr(route, "path", "") == "/admin/resumo-ganhos/atualizar" and "POST" in (getattr(route, "methods", set()) or set()):
                route.endpoint = wrapped_post
                if getattr(route, "dependant", None) is not None:
                    route.dependant.call = wrapped_post

    _INSTALLED = True
