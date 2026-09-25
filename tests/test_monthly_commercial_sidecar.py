"""Tests: isolated SQL commercial snapshots must not mutate legacy awards/history."""
import asyncio
import copy

from api import monthly_commercial_live as live
from api.cache_reads import CacheReadError
from api.monthly_commercial_overlay import overlay_commercial


def sample(sale=100, line=4):
    return {
        "__COMPETENCIA": "09/2026", "__CANAL": "VENDEDOR", "__COLABORADOR": "ANA",
        "__LAB": "LAB A", "__linha": line, "__aba": "CAMPANHA VEND",
        "__OBJETIVO": 100, "__VENDA": sale,
        "__TEM_FOCO": False, "__CODIGO_FOCO": "",
        "__OBJETIVO_FOCO": 0, "__VENDA_FOCO": 0,
    }


def snapshot():
    return {
        "competencias": [{
            "competencia": "09/2026", "status": "ATUAL",
            "linkDrive": "https://docs.google.com/spreadsheets/d/17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4/edit",
        }],
        "dadosVendedores": [dict(sample(), **{"Premiação": 55, "metricasDetalhes": [{"premio": 55}]})],
        "dadosTelevendas": [dict(sample(), **{
            "__CANAL": "TELEVENDAS", "__aba": "CAMPANHAS TLVS",
            "Premiação": 20,
        })],
        "regrasPremiacao": [{"laboratorio": "LAB A", "regra": "LEGADO"}],
    }


def test_overlay_only_commercial_and_maintains_awards():
    before = snapshot()
    base = copy.deepcopy(before)
    source = sample(sale=300)
    sidecar = {
        "competencia": "09/2026",
        "sheetId": "17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4",
        "baseAtualizadoEm": "2026-09-25T04:36:54Z",
        "temDivergenciaComercial": True,
        "dadosVendedores": [source],
        "dadosTelevendas": [dict(source, **{"__CANAL": "TELEVENDAS", "__aba": "CAMPANHAS TLVS"})],
    }
    result, row = overlay_commercial(
        base, {"atualizado_em": "2026-09-25T04:36:54Z"},
        sidecar, {"atualizado_em": "2026-09-25T08:00:00Z"},
    )
    assert result["dadosVendedores"][0]["Venda"] == 300
    assert result["dadosVendedores"][0]["Premiação"] == 55
    assert result["dadosVendedores"][0]["metricasDetalhes"] == [{"premio": 55}]
    assert result["regrasPremiacao"] == before["regrasPremiacao"]
    assert before["dadosVendedores"][0]["__VENDA"] == 100
    assert row["atualizado_em"] == "2026-09-25T08:00:00Z"
    assert result["financeiroPendente"] is True


def test_stale_sidecar_never_overrides_new_legacy_calculation():
    payload = snapshot()
    out, row = overlay_commercial(
        payload, {"atualizado_em": "revision-2"},
        {"competencia": "09/2026",
         "sheetId": "17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4",
         "baseAtualizadoEm": "revision-1",
         "dadosVendedores": [sample(sale=200)],
         "dadosTelevendas": [sample(sale=200)]},
        {"atualizado_em": "revision-3"},
    )
    assert out is payload
    assert row["atualizado_em"] == "revision-2"


def test_guard_prevents_closed_competence():
    data = snapshot()
    data["competencias"][0]["fechada"] = True
    try:
        live.current_source(data)
    except live.CommercialSyncError:
        pass
    else:
        raise AssertionError("competencia fechada must be rejected")


def test_separate_sql_write_only(monkeypatch):
    before = snapshot()
    events = []
    async def fake_get(*, modulo, settings):
        if modulo == "MENSAL_COMERCIAL":
            raise CacheReadError("sem fotografia comercial")
        assert modulo == "MENSAL"
        events.append("read")
        return copy.deepcopy(before), {"atualizado_em": "revision-1"}
    def fresh(sheet_id, comp):
        assert comp == "09/2026"
        changed = sample(sale=300)
        return {"dadosVendedores": [changed], "dadosTelevendas": [
            dict(changed, **{"__CANAL": "TELEVENDAS", "__aba": "CAMPANHAS TLVS"})]}
    async def fake_persist(*, modulo, payload, profile, version):
        assert modulo == "MENSAL_COMERCIAL"
        assert "regrasPremiacao" not in payload
        assert all("Premiação" not in r for r in payload["dadosVendedores"])
        events.append("write")
        return "25/09/2026 08:00", "2026-09-25T08:00:00Z"
    monkeypatch.setattr(live, "cache_get", fake_get)
    monkeypatch.setattr(live, "_read_sheets", fresh)
    monkeypatch.setenv("DISMEPE_MONTHLY_CURRENT_SHEET_ID", "17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4")
    result = asyncio.run(live.sync_commercial(settings=object(), profile={}, persist=fake_persist))
    assert result["resultado"] == "COMERCIAL_SQL_PUBLICADO"
    assert events == ["read", "read", "write"]
    assert before["dadosVendedores"][0]["Premiação"] == 55
