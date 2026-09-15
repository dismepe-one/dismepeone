from pathlib import Path
import asyncio

import api.history_reads as history_reads

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"
HISTORY = ROOT / "api" / "history_reads.py"


def source():
    return HTML.read_text(encoding="utf-8")


def test_history_detail_has_fastapi_route():
    text = MAIN.read_text(encoding="utf-8")
    assert '@app.get("/data/history-get")' in text
    assert "history_get(" in text
    assert "history_id: str" in text


def test_selected_monthly_history_uses_direct_route_first():
    text = source()
    start = text.index("async function h39GetState")
    end = text.index("function h39ApplyState", start)
    block = text[start:end]
    assert "v2HistoryGetDirect(" in block
    assert "'mensal'" in block
    assert "'HIST39_OBTER'" in block
    assert "postApi({" not in block


def test_direct_detail_helper_keeps_legacy_only_as_fallback():
    text = source()
    start = text.index("async function v2HistoryGetDirect")
    end = text.index("(function(){", start)
    block = text[start:end]
    assert "/data/history-get?kind=" in block
    assert "history_id=" in block
    assert "credentials:'same-origin'" in block
    assert "cache:'no-store'" in block
    assert "fallback legado" in block
    assert "idAtualizacao:historyId" in block


def test_history_detail_auth_errors_do_not_fallback():
    text = source()
    start = text.index("async function v2HistoryGetDirect")
    end = text.index("(function(){", start)
    block = text[start:end]
    assert "Number(error?.status||0)===401" in block
    assert "Number(error?.status||0)===403" in block


def test_history_get_returns_selected_snapshot_and_scopes_individual(monkeypatch):
    payload = {
        "atualizacoes": [
            {
                "idAtualizacao": "hist-1",
                "competencia": "09/2026",
                "dataHoraISO": "2026-09-14T18:00:00-03:00",
                "dadosVendedores": [
                    {"__COLABORADOR": "DANTON", "__LAB": "LAB A", "__VENDA": 10},
                    {"__COLABORADOR": "OUTRO", "__LAB": "LAB B", "__VENDA": 20},
                ],
                "dadosTelevendas": [
                    {"__COLABORADOR": "DANTON", "__LAB": "LAB C", "__VENDA": 30},
                    {"__COLABORADOR": "OUTRO", "__LAB": "LAB D", "__VENDA": 40},
                ],
                "regrasPremiacao": [{"competencia": "09/2026", "regra": "x"}],
            }
        ]
    }

    async def fake_cache_get(*, modulo, settings):
        assert modulo == "HISTORICO_MENSAL"
        return payload, {"atualizado_em": "agora", "versao": "v1"}

    monkeypatch.setattr(history_reads, "cache_get", fake_cache_get)

    profile = {
        "usuario": "DANTON",
        "nome": "DANTON",
        "tipo": "VENDEDOR",
        "permissoes": {"HISTORICO_MENSAL_VISUALIZAR": True},
    }

    result = asyncio.run(
        history_reads.history_get(
            kind="mensal",
            history_id="hist-1",
            profile=profile,
            settings=object(),
        )
    )

    assert result["sucesso"] is True
    assert result["atualizacao"]["idAtualizacao"] == "hist-1"
    assert len(result["dadosVendedores"]) == 1
    assert result["dadosVendedores"][0]["__COLABORADOR"] == "DANTON"
    assert len(result["dadosTelevendas"]) == 1
    assert result["dadosTelevendas"][0]["__COLABORADOR"] == "DANTON"
    assert result["snapshotVersao"] == "v1"


def test_history_get_management_receives_full_selected_snapshot(monkeypatch):
    payload = {
        "atualizacoes": [
            {
                "idAtualizacao": "hist-2",
                "competencia": "09/2026",
                "payload": {
                    "dadosVendedores": [
                        {"__COLABORADOR": "A"},
                        {"__COLABORADOR": "B"},
                    ],
                    "dadosTelevendas": [{"__COLABORADOR": "C"}],
                    "regrasPremiacao": [],
                },
            }
        ]
    }

    async def fake_cache_get(*, modulo, settings):
        return payload, {"atualizado_em": "agora", "versao": "v2"}

    monkeypatch.setattr(history_reads, "cache_get", fake_cache_get)

    profile = {"usuario": "GESTOR", "tipo": "ADMINISTRADOR", "permissoes": {}}
    result = asyncio.run(
        history_reads.history_get(
            kind="mensal",
            history_id="hist-2",
            profile=profile,
            settings=object(),
        )
    )

    assert len(result["dadosVendedores"]) == 2
    assert len(result["dadosTelevendas"]) == 1


def test_h10_build_markers():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
