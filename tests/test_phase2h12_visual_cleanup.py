from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "frontend" / "portal-v2-homolog.html"
MAIN = ROOT / "api" / "main.py"


def source():
    return PORTAL.read_text(encoding="utf-8")


def test_h12_version_and_badge():
    assert "2.0.0-phase2i2" in MAIN.read_text(encoding="utf-8")
    assert "HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA" in source()


def test_global_loading_surfaces_are_disabled():
    s = source()
    assert "#v68GlobalActivity, #v2GlobalLoading{display:none !important;}" in s
    assert "#v2GlobalLoading.v2-show{display:none !important}" in s
    assert "overlay?.classList.remove('v2-show');" in s


def test_passive_initial_loading_placeholders_removed():
    s = source()
    forbidden = [
        '>Carregando campanhas...</td>',
        '>Carregando histórico...</span>',
        '>Carregando...</p>',
        'Carregando opções do aviso...</div>',
        'Carregando avisos...</div>',
        '>Carregando módulos…</div>',
        'Conectando à Base de Clientes PED...',
        "status.textContent='Carregando resumo de ganhos...'",
        "status.textContent='Carregando dados...'",
        "status.textContent='Carregando Log de Alterações...'",
        "setStatus('Carregando regras e laboratórios...')",
    ]
    for item in forbidden:
        assert item not in s


def test_action_feedback_is_preserved():
    s = source()
    for item in ['Salvando...', 'Excluindo...', 'ATUALIZANDO...', 'ENVIANDO...', 'PROCESSANDO']:
        assert item in s
