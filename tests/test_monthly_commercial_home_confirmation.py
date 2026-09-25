"""Regressao: HOME confirma MENSAL_COMERCIAL sem esperar escrita legada em MENSAL."""
import asyncio
from pathlib import Path

from api import home_publication
from api import monthly_commercial_overlay
from tests.test_monthly_commercial_sidecar import sample, snapshot


def test_home_monthly_status_uses_commercial_overlay(monkeypatch):
    base = snapshot()
    base_row = {"atualizado_em": "raw-financial-revision"}
    commercial_row = {"atualizado_em": "2026-09-25T06:21:36.387+00:00"}
    commercial = {
        "competencia": "09/2026",
        "sheetId": "17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4",
        "baseAtualizadoEm": base_row["atualizado_em"],
        "temDivergenciaComercial": True,
        "dadosVendedores": [sample(sale=250)],
        "dadosTelevendas": [dict(sample(sale=250), **{"__CANAL": "TELEVENDAS"})],
    }
    calls = []
    async def fake_get(*, modulo, settings):
        calls.append(modulo)
        if modulo == "MENSAL":
            return base, base_row
        if modulo == "MENSAL_COMERCIAL":
            return commercial, commercial_row
        raise AssertionError("Unrelated module accessed")
    monkeypatch.setattr(home_publication, "raw_cache_get", fake_get)
    monkeypatch.setattr(monthly_commercial_overlay, "cache_get", fake_get)
    monkeypatch.setenv("DISMEPE_MONTHLY_COMMERCIAL_ENABLED", "1")
    result, row = asyncio.run(home_publication._source_snapshot("MENSAL"))
    assert calls == ["MENSAL", "MENSAL_COMERCIAL", "MENSAL"]
    assert result["dadosVendedores"][0]["__VENDA"] == 250
    assert result["dadosVendedores"][0]["Premiação"] == 55
    assert result["regrasPremiacao"] == base["regrasPremiacao"]
    assert row["atualizado_em"] == commercial_row["atualizado_em"]


def test_other_modules_do_not_use_overlay(monkeypatch):
    calls = []
    async def fake_get(*, modulo, settings):
        calls.append(modulo)
        return {"campanhas": []}, {"atualizado_em": "original"}
    monkeypatch.setattr(home_publication, "raw_cache_get", fake_get)
    monkeypatch.setenv("DISMEPE_MONTHLY_COMMERCIAL_ENABLED", "1")
    payload, row = asyncio.run(home_publication._source_snapshot("EXTRAS"))
    assert calls == ["EXTRAS"]
    assert row["atualizado_em"] == "original"


def test_browser_stops_legacy_wait_after_confirmed_commercial_sql():
    js = (Path(__file__).resolve().parents[1] / "frontend" /
          "home-publication-prod59823.js").read_text(encoding="utf-8")
    assert "syncResult==='COMERCIAL_SQL_PUBLICADO'" in js
    assert "syncResult==='SEM_ALTERACAO'" in js
    assert js.index("syncResult==='COMERCIAL_SQL_PUBLICADO'") < js.index("waitForMonthlyPersistence(publishedSignature")
    assert "actual<expected" in js
