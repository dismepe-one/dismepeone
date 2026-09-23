from __future__ import annotations

"""Passkeys WebAuthn para o portal Indústrias, isoladas da ponte legada por senha."""
import base64
import hashlib
import json
import secrets
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .config import get_settings
from .security import issue_session_token, normalizar, decode_session_token
from .supabase_edge import login_via_edge, InvalidCredentials, UpstreamUnavailable
from .industries import _industry_profile, industry_must_change_password

settings = get_settings()
router = APIRouter(prefix="/passkeys", tags=["Passkeys Indústrias"])
RP_ID = "dismepeone.com.br"
ORIGIN = "https://" + RP_ID
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
COOKIE = settings.cookie_name


class LoginStart(BaseModel):
    usuario: str = Field(min_length=2, max_length=160)


class RegistrationStart(BaseModel):
    senha: str = Field(min_length=1, max_length=256)


class CeremonyFinish(BaseModel):
    id: str = Field(min_length=36, max_length=36)
    credencial: dict[str, Any]


class RevokeKey(BaseModel):
    credencial_id: str = Field(min_length=12, max_length=1024)


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def require_official(request: Request):
    # O RP não deve aceitar onrender.com, subdomínios, IPs ou origens externas.
    if request.url.hostname != RP_ID or request.url.scheme != "https":
        raise HTTPException(403, "Abra o endereço oficial https://dismepeone.com.br.")
    if request.method != "GET" and request.headers.get("origin") != ORIGIN:
        raise HTTPException(403, "Origem da solicitação não autorizada.")


def session_username(session: str | None) -> str:
    if not session:
        raise HTTPException(401, "Entre na sua conta com senha antes de cadastrar a chave.")
    try:
        claims = decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except Exception as exc:
        raise HTTPException(401, "Sessão expirada. Entre novamente.") from exc
    return str(claims.get("usuario") or claims.get("sub") or "").strip()


async def logged_industry(session: str | None):
    # Verifica autorização no portal e bloqueia a inscrição durante a troca obrigatória de senha.
    profile = await _industry_profile(session, require_password_changed=True)
    if normalizar(profile.get("tipo")) != "INDUSTRIA":
        raise HTTPException(403, "O cadastro biométrico piloto está disponível apenas para contas de Indústrias.")
    username = session_username(session)
    account = await edge("ACCOUNT", usuario=username)
    if normalizar(account["usuario"]["usuario"]) != normalizar(username):
        raise HTTPException(403, "Identidade da sessão não confirmada.")
    return account["usuario"]


async def edge(action: str, **kwargs) -> dict:
    if not settings.edge_token or not settings.supabase_publishable_key:
        raise HTTPException(503, "Serviço de chaves de acesso não configurado.")
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(
                settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-passkeys",
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "x-dismepe-token": settings.edge_token,
                    "Content-Type": "application/json",
                },
                json={"acao": action, **kwargs},
            )
            data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Serviço biométrico indisponível.") from exc
    if not isinstance(data, dict) or data.get("sucesso") is not True:
        message = str(data.get("erro") or "Operação não concluída.") if isinstance(data, dict) else "Resposta inválida."
        raise HTTPException(r.status_code if 400 <= r.status_code < 500 else 503, message)
    return data


def check_payload(credential: dict):
    if len(json.dumps(credential, ensure_ascii=False)) > 16384:
        raise HTTPException(422, "Resposta biométrica excede o tamanho permitido.")


def guard_failure(exc: Exception):
    # Não revelar detalhes criptográficos nem o cadastro de outras contas.
    raise HTTPException(401, "A verificação da chave de acesso falhou ou expirou.") from exc


@router.get("/availability")
async def availability(request: Request):
    require_official(request)
    return {"sucesso": True, "disponivel": True, "escopo": "INDUSTRIA", "rpId": RP_ID}


@router.post("/register/options")
async def registration_options(
    request: Request, data: RegistrationStart,
    session: str | None = Cookie(default=None, alias=COOKIE),
):
    require_official(request)
    user = await logged_industry(session)
    username = user["usuario"]
    # Reconfirma a senha nesta operação, sem persistir ou registrar a senha.
    try:
        verified = await login_via_edge(usuario=username, senha=data.senha, settings=settings)
    except InvalidCredentials as exc:
        raise HTTPException(401, "Senha não confirmada.") from exc
    except UpstreamUnavailable as exc:
        raise HTTPException(503, "Não foi possível confirmar a senha agora.") from exc
    if normalizar(verified.get("usuario")) != normalizar(username):
        raise HTTPException(403, "A senha não corresponde à conta autenticada.")
    existing = await edge("CREDENTIAL_LIST", usuario=username)
    challenge = secrets.token_bytes(32)
    handle = hashlib.sha256(normalizar(username).encode("utf-8")).digest()
    descriptors = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(x["credential_id"]))
        for x in existing.get("credenciais", []) if x.get("ativo")
    ]
    options = generate_registration_options(
        rp_id=RP_ID, rp_name="DISMEPE ONE", user_id=handle,
        user_name=username, user_display_name=str(user.get("nome") or username)[:80],
        challenge=challenge, timeout=90000,
        exclude_credentials=descriptors,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    challenge_id = str(uuid.uuid4())
    await edge("CHALLENGE_NEW", usuario=username, proposito="REGISTRO",
               id=challenge_id, desafio=b64(challenge),
               session_hash=hashlib.sha256(session.encode("utf-8")).hexdigest())
    return {"sucesso": True, "id": challenge_id, "options": json.loads(options_to_json(options))}


@router.post("/register/verify")
async def registration_finish(
    request: Request, data: CeremonyFinish,
    session: str | None = Cookie(default=None, alias=COOKIE),
):
    require_official(request)
    user = await logged_industry(session)
    check_payload(data.credencial)
    result = await edge(
        "CHALLENGE_CONSUME", usuario=user["usuario"], proposito="REGISTRO", id=data.id,
        session_hash=hashlib.sha256(session.encode("utf-8")).hexdigest(),
    )
    try:
        verified = verify_registration_response(
            credential=data.credencial,
            expected_challenge=base64url_to_bytes(result["desafio"]),
            expected_origin=ORIGIN, expected_rp_id=RP_ID,
            require_user_verification=True,
        )
    except Exception as exc:
        guard_failure(exc)
    transport = data.credencial.get("response", {}).get("transports", [])
    await edge(
        "CREDENTIAL_ADD", usuario=user["usuario"],
        credential_id=b64(verified.credential_id),
        public_key=b64(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=transport if isinstance(transport, list) else [],
        nome="Passkey DISMEPE ONE",
    )
    return {"sucesso": True, "mensagem": "Chave de acesso cadastrada com segurança."}


@router.get("/credentials")
async def credentials(
    request: Request, session: str | None = Cookie(default=None, alias=COOKIE),
):
    require_official(request)
    user = await logged_industry(session)
    return await edge("CREDENTIAL_LIST", usuario=user["usuario"])


@router.post("/credentials/revoke")
async def revoke(
    request: Request, data: RevokeKey,
    session: str | None = Cookie(default=None, alias=COOKIE),
):
    require_official(request)
    user = await logged_industry(session)
    return await edge("CREDENTIAL_REVOKE", usuario=user["usuario"],
                      credential_id=data.credencial_id)


@router.post("/login/options")
async def login_options(request: Request, data: LoginStart):
    require_official(request)
    # O cliente não escolhe a identidade depois que o desafio é emitido.
    account = await edge("ACCOUNT", usuario=data.usuario)
    user = account["usuario"]
    existing = await edge("CREDENTIAL_LIST", usuario=user["usuario"])
    active = [x for x in existing.get("credenciais", []) if x.get("ativo")]
    if not active:
        raise HTTPException(404, "Nenhuma chave de acesso cadastrada para esta conta.")
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=RP_ID, challenge=challenge, timeout=90000,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(x["credential_id"])) for x in active],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = str(uuid.uuid4())
    await edge("CHALLENGE_NEW", usuario=user["usuario"], proposito="LOGIN",
               id=challenge_id, desafio=b64(challenge))
    return {"sucesso": True, "id": challenge_id, "usuario": user["usuario"],
            "options": json.loads(options_to_json(options))}


class LoginFinish(CeremonyFinish):
    usuario: str = Field(min_length=2, max_length=160)


@router.post("/login/verify")
async def login_finish(request: Request, data: LoginFinish, response: Response):
    require_official(request)
    check_payload(data.credencial)
    credential_id = str(data.credencial.get("id") or "")
    record = await edge("CREDENTIAL_GET", usuario=data.usuario, credential_id=credential_id)
    user = record["usuario"]
    result = await edge("CHALLENGE_CONSUME", usuario=user["usuario"], proposito="LOGIN", id=data.id)
    key = record["credencial"]
    try:
        verified = verify_authentication_response(
            credential=data.credencial,
            expected_challenge=base64url_to_bytes(result["desafio"]),
            expected_origin=ORIGIN, expected_rp_id=RP_ID,
            credential_public_key=base64url_to_bytes(key["public_key"]),
            credential_current_sign_count=int(key["sign_count"]),
            require_user_verification=True,
        )
    except Exception as exc:
        guard_failure(exc)
    if b64(verified.credential_id) != credential_id:
        raise HTTPException(401, "A chave não corresponde à conta.")
    confirmed = await edge(
        "CREDENTIAL_TOUCH", usuario=user["usuario"],
        credential_id=credential_id,
        sign_count_anterior=int(key["sign_count"]),
        sign_count=verified.new_sign_count,
    )
    fresh = confirmed["usuario"]
    perms = fresh.get("permissoes") or {}
    if not isinstance(perms, dict):
        perms = {}
    # Nunca concede acesso ao portal principal por uma sessão biométrica piloto.
    profile = {
        "usuario": fresh["usuario"], "nome": fresh.get("nome") or "",
        "vendedor": fresh.get("vendedor") or fresh.get("nome") or "",
        "tipo": fresh["tipo"], "setor": fresh.get("setor") or "",
        "permissoes": perms,
    }
    token = issue_session_token(
        usuario=fresh["usuario"], profile=profile, secret=settings.jwt_secret,
        issuer=settings.jwt_issuer, lifetime_seconds=settings.session_seconds,
    )
    response.set_cookie(
        key=COOKIE, value=token, max_age=settings.session_seconds,
        httponly=True, secure=True, samesite="lax",
        domain=settings.cookie_domain, path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"sucesso": True, "destino": "/industrias"}


@router.get("/login", include_in_schema=False)
async def login_page(request: Request):
    require_official(request)
    return FileResponse(ROOT / "frontend" / "passkeys-login.html",
                        media_type="text/html", headers={"Cache-Control": "no-store, private"})


@router.get("/client.js", include_in_schema=False)
async def client_script(request: Request):
    require_official(request)
    return FileResponse(ROOT / "frontend" / "passkeys-client.js",
                        media_type="application/javascript", headers={"Cache-Control": "no-store"})
