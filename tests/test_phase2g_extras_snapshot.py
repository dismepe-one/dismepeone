from pathlib import Path


def test_backend_reuses_extras_snapshot_and_list_skips_users():
    text = (
        Path(__file__).resolve().parents[1]
        / "api"
        / "main.py"
    ).read_text(encoding="utf-8")

    assert "_EXTRAS_SNAPSHOT_CACHE" in text
    assert "_EXTRAS_SNAPSHOT_TTL_SECONDS" in text
    assert 'if str(id or "LIST").upper() == "LIST":' in text
    assert 'users_payload = {"usuarios": []}' in text
    assert 'result["snapshotCache"]' in text
