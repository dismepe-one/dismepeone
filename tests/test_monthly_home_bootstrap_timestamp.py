"""HOME must expose its published time, not the commercial import time."""
import asyncio
from pathlib import Path

from api import monthly_commercial_overlay as overlay


def test_published_home_never_calls_commercial_overlay(monkeypatch):
    published = {"dadosVendedores": [{"__VENDA": 150}], "financeiroPendente": False}
    row = {"versao": "PROD5.9.8.23_HOME_PUBLICATION",
           "atualizado_em": "2026-09-25T08:03:25-03:00"}
    async def no_sql(*, modulo, settings):
        raise AssertionError("published HOME must not query commercial sidecar")
    monkeypatch.setattr(overlay, "cache_get", no_sql)
    monkeypatch.setenv("DISMEPE_MONTHLY_COMMERCIAL_ENABLED", "1")
    data, returned_row = asyncio.run(overlay.monthly_commercial_overlay(
        payload=published, row=row, settings=object()))
    assert data is published
    assert returned_row is row
    assert returned_row["atualizado_em"] == "2026-09-25T08:03:25-03:00"


def test_both_bootstrap_paths_preserve_published_home_time():
    app = (Path(__file__).resolve().parents[1] / "api" / "main.py").read_text(encoding="utf-8")
    expected = "not str(mensal_row.get('versao') or '').endswith('_HOME_PUBLICATION')"
    # Both login bootstrap and authenticated bootstrap must have this guard.
    assert app.count(expected) == 2
