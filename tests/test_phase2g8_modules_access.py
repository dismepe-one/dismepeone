from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/"frontend"/"portal-v2-homolog.html"
MAIN=ROOT/"api"/"main.py"

def source():
    return HTML.read_text(encoding="utf-8")

def test_f5_hold_is_released_after_auth_me_restore():
    text=source()
    assert "document.documentElement.classList.remove('v67-local-session');" in text
    assert "document.documentElement.removeAttribute('data-v68-screen');" in text

def test_exclusive_router_covers_all_main_modules():
    text=source()
    assert 'id="v2g8-exclusive-module-router"' in text
    for module in [
        "homeModule","channelDashboard","managerOverview","premiacaoModule",
        "resumoPremiacoesModule","campanhasExtrasModule",
        "monthlyCampaignManagerModule","clientesPEDModule","accessLogModule"
    ]:
        assert f"'{module}'" in text

def test_exclusive_router_uses_inline_important_hide():
    text=source()
    assert "style.setProperty('display','none','important')" in text
    assert "v2ActivateExclusiveModule" in text

def test_navigation_routes_are_wrapped_exclusively():
    text=source()
    for name in [
        "openHome","switchChannel","switchOverview","openPremiacao",
        "openResumoPremiacoes","openCampanhasExtras",
        "openMonthlyCampaignManager","openClientesPED","openAccessLog"
    ]:
        assert f"{name}:" in text

def test_access_returned_to_direct_phase2f_flow():
    text=source()
    start=text.index("window.openAccessLog=async function()")
    end=text.index("window.closeAccessLog=function()",start)
    block=text[start:end]
    assert "window.loadAccessLog" in block
    assert "force:true" in block
    assert "v2PrimeAccessLog" not in text
    assert "v2g7-access-visible-autoload" not in text

def test_access_load_is_one_direct_fetch_and_render():
    text=source()
    start=text.index("window.loadAccessLog=function(options)")
    end=text.index("window.restoreViewState=function()",start)
    block=text[start:end]
    assert "if(accessLoadPromise) return accessLoadPromise;" in block
    assert block.count("window.v2FetchAccessLog()") == 1
    assert block.count("renderAccessSnapshot(r);") == 1

def test_router_guarantees_access_load_if_legacy_route_only_shows_module():
    text=source()
    assert "activeModule==='accessLogModule'" in text
    assert "source:'exclusive-router'" in text

def test_g8_build():
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
