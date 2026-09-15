from api.security import auth_email, normalizar, senha_interna


def test_normalizar_equivale_apps_script():
    assert normalizar("  Cláudia João  ") == "CLAUDIA JOAO"
    assert normalizar("Eletrônico") == "ELETRONICO"


def test_senha_interna_formato_estavel():
    value = senha_interna("teste", "1234", "pepper-de-teste")
    assert value.startswith("D1!")
    assert "=" not in value
    assert len(value) > 40


def test_auth_email_estavel():
    email = auth_email("usuario.teste")
    assert email.startswith("u_")
    assert email.endswith("@auth.dismepe.invalid")
