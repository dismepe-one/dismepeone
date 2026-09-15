from __future__ import annotations

import base64
import hashlib
import hmac
import time
import unicodedata
from typing import Any

import jwt


def normalizar(value: Any) -> str:
    """
    Replica a função normalizar() do Código.gs:
    NFD -> remove acentos -> trim -> uppercase.
    """
    text = str("" if value is None else value)
    decomposed = unicodedata.normalize("NFD", text)
    without_accents = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return without_accents.strip().upper()


def senha_interna(usuario: str, senha: str, pepper: str) -> str:
    """
    Replica supabaseV191SenhaInterna_():
    HMAC-SHA256(normalizar(usuario) + "|" + senha, pepper)
    -> base64url sem "=" -> prefixo D1!
    """
    message = f"{normalizar(usuario)}|{senha}".encode("utf-8")
    digest = hmac.new(
        pepper.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    token = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return "D1!" + token


def auth_email(usuario: str) -> str:
    """
    Replica supabaseV202EmailInterno_().
    Mantido para a futura migração do login direto no Supabase Auth.
    """
    digest = hashlib.sha256(normalizar(usuario).encode("utf-8")).digest()
    token = base64.urlsafe_b64encode(digest).decode("ascii")
    token = "".join(ch for ch in token if ch.isalnum())[:28].lower()
    return f"u_{token}@auth.dismepe.invalid"


def issue_session_token(
    *,
    usuario: str,
    profile: dict,
    secret: str,
    issuer: str,
    lifetime_seconds: int,
) -> str:
    now = int(time.time())
    payload = {
        "iss": issuer,
        "sub": usuario,
        "iat": now,
        "exp": now + lifetime_seconds,
        "usuario": usuario,
        "tipo": profile.get("tipo", ""),
        "vendedor": profile.get("vendedor", ""),
        "nome": profile.get("nome", ""),
        "setor": profile.get("setor", ""),
        "permissoes": profile.get("permissoes", {}),
        "ver": 2,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_session_token(
    token: str,
    *,
    secret: str,
    issuer: str,
) -> dict:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=issuer,
    )
