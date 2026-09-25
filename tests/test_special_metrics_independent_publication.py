"""Only special positivity refresh: no sales recalculation, no history, no false success."""
import asyncio
import copy

import pytest
from fastapi import BackgroundTasks, HTTPException
from api import home_publication as hp
from tests.test_monthly_special_metrics import snapshot


def _fixture(monkeypatch, *, changed=False, fail=False):
    monthly = snapshot()
    extras = {"campanhas": [{"id": "unchanged"}], "vendasPorCampanha": []}
    original = {"mensal": copy.deepcopy(monthly), "extras": copy.deepcopy(extras),
                "historico": [{"id": "old", "publicadoEm": "2026-09-24T09:00:00-03:00"}],
                "fontes": {"mensal": {"atualizadoEm": "2026-09-25T11:16:15Z"},
                            "extras": {"atualizadoEm": "2026-09-24T09:00:00Z"}},
                "displayTimes": {"mensal": {"iso": "2026-09-25T08:16:20-03:00", "display": "25/09/2026 08:16:20"},
                                 "extras": {"iso": "2026-09-24T09:00:00-03:00", "display": "24/09/2026 09:00:00"}}}
    stored = copy.deepcopy(original)
    writes = []
    async def read_publication(*, cfg_settings=None):
        return copy.deepcopy(stored), {"atualizado_em": original["displayTimes"]["mensal"]["iso"]}
    async def source(module):
        if module == "MENSAL":
            return copy.deepcopy(monthly), {"atualizado_em": "2026-09-25T11:16:15Z"}
        if module == "EXTRAS":
            return copy.deepcopy(extras), {"atualizado_em": "2026-09-24T09:00:00Z"}
        raise AssertionError("Unexpected source " + module)
    async def enrich(data):
        if fail:
            raise RuntimeError("Google read was denied")
        if changed:
            data["dadosVendedores"][0]["metricasParcial"]["componentes"][0]["realizado"] = 9
        return data
    async def edge(action, data, **kwargs):
        assert action == "CACHE_SET" and data["modulo"] == hp.HOME_PUBLICATION_MODULE
        writes.append(copy.deepcopy(data))
        stored.clear()
        stored.update(copy.deepcopy(data["payload"]))
        return {"sucesso": True}
    async def audit(*args, **kwargs):
        return None
    async def forbidden_history(**kwargs):
        raise AssertionError("Must never write monthly history in metrics-only flow")
    monkeypatch.setattr(hp, "_authorized", lambda session: {"usuario": "ADMINISTRADOR", "tipo": "ADMIN"})
    monkeypatch.setattr(hp, "_source_snapshot", source)
    monkeypatch.setattr(hp, "_read_publication", read_publication)
    monkeypatch.setattr(hp, "enrich_special_metrics", enrich)
    monkeypatch.setattr(hp, "_edge_call", edge)
    monkeypatch.setattr(hp, "_audit", audit)
    monkeypatch.setattr(hp, "_ensure_monthly_publication_history", forbidden_history)
    return original, stored, writes


def run():
    return asyncio.run(hp._home_publication_publish_locked(
        hp.HomePublishRequest(somenteMetricasEspeciais=True, inserirHistorico=False),
        BackgroundTasks(), "mock-session"))


def test_no_changes_never_write_or_update_history(monkeypatch):
    old, stored, writes = _fixture(monkeypatch)
    result = run()
    assert result["sucesso"] and not result["metricasEspeciaisAtualizadas"]
    assert not result["atualizouHorario"]
    assert not writes and old == stored


def test_failed_auxiliary_read_fails_explicitly_without_writes(monkeypatch):
    old, stored, writes = _fixture(monkeypatch, fail=True)
    with pytest.raises(HTTPException) as error:
        run()
    assert error.value.status_code == 503
    assert "positivacoes especiais" in error.value.detail
    assert not writes and old == stored


def test_special_only_persists_metrics_but_not_sales_finance_or_history(monkeypatch):
    old, stored, writes = _fixture(monkeypatch, changed=True)
    result = run()
    assert result["metricasEspeciaisAtualizadas"] is True
    assert result["atualizouHorario"] is True
    assert result["inseriuHistorico"] is False
    assert result["notificacaoSolicitada"] is False
    assert len(writes) == 1
    assert stored["historico"] == old["historico"]
    assert stored["fontes"] == old["fontes"]
    assert stored["extras"] == old["extras"]
    for key in ("dadosVendedores", "dadosTelevendas"):
        for old_row, new_row in zip(old["mensal"][key], stored["mensal"][key]):
            assert old_row["__VENDA"] == new_row["__VENDA"]
            assert old_row["__OBJETIVO"] == new_row["__OBJETIVO"]
    assert stored["mensal"]["regrasPremiacao"] == old["mensal"]["regrasPremiacao"]


def test_client_invokes_independent_refresh_if_commercial_unchanged():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "frontend" /
          "home-publication-prod59823.js").read_text("utf-8")
    assert "somenteMetricasEspeciais:true,inserirHistorico:false,notificarVendas:false" in js
    assert "if(state.novosNumeros){" not in js
