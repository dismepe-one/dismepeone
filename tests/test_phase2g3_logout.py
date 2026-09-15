from pathlib import Path


def source():
    return (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "portal-v2-homolog.html"
    ).read_text(encoding="utf-8")


def test_logout_removes_v67_class_that_hides_login():
    text = source()
    start = text.index("function logout()")
    end = text.index("function getActiveDataset()", start)
    block = text[start:end]

    assert "'v67-local-session'" in block
    assert "removeAttribute('data-v68-screen')" in block
    assert "loginOverlay.classList.remove('hidden')" in block


def test_logout_shows_ui_before_network_request():
    text = source()
    marker = "const oldLogout=window.logout;"
    start = text.rindex(marker)
    end = text.index("console.log('[DISMEPE ONE 2.0]", start)
    block = text[start:end]

    old_call = block.index("oldLogout.apply")
    api_call = block.index("v2ShellApi('/auth/logout'")
    assert old_call < api_call
    assert "await v2ShellApi('/auth/logout'" not in block


def test_logged_out_state_forces_login_visible():
    text = source()
    assert 'id="v2g3-logout-login-guard"' in text
    assert "body:not(.v51-auth-ready) #loginOverlay" in text
    assert "display:flex !important" in text
    assert "visibility:visible !important" in text
