from pathlib import Path


def html():
    return (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")


def test_create_user_card_does_not_show_global_overlay():
    text = html()
    assert "const modalOnly=" in text
    assert "/openCreateUserModal\\s*\\(/" in text
    assert "if(modalOnly)" in text


def test_strict_permissions_are_applied_during_v2_login():
    text = html()
    assert text.count("window.v21013ApplyStrictPermissions?.()") >= 3
    assert "homeNavigationMs" in text


def test_generic_overlay_has_failsafe_release():
    text = html()
    listener = text.index("const target=ev.target.closest?.(navSelector)")
    nearby = text[listener:listener + 2500]
    assert "v2GlobalLoadingReleaseAfterPaint" in nearby
