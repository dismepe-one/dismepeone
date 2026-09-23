from __future__ import annotations

"""Web Push DISMEPE ONE: sessão existente + função SQL privada; sem tocar no sino legado."""
import asyncio
import base64
import hashlib
import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .security import decode_session_token

settings = get_settings()
router = APIRouter(prefix="/push")
ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("uvicorn.error")
EDGE_PATH = "/functions/v1/dismepe-push"
VAPID_PUBLIC = os.environ.get("DISMEPE_VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE = os.environ.get("DISMEPE_VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("DISMEPE_VAPID_SUBJECT", "")


def profile(session: str | None):
    if not session:
        raise HTTPException(401, "Sessão ausente.")
    try:
        return decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sessão expirada ou inválida.") from exc


def principal(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    return profile(session)


def user_id(user):
    return str(user.get("usuario") or user.get("sub") or "").strip()


def no_store(resp: Response):
    resp.headers["Cache-Control"] = "no-store, private"


async def edge(action: str, **data):
    if not settings.edge_token or not settings.supabase_publishable_key:
        raise HTTPException(503, "Canal privado de notificações não configurado.")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                settings.supabase_url.rstrip("/") + EDGE_PATH,
                json={"acao": action, **data},
                headers={"apikey": settings.supabase_publishable_key,
                         "x-dismepe-token": settings.edge_token,
                         "Content-Type": "application/json"},
            )
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Push SQL indisponível: %s", type(exc).__name__)
        raise HTTPException(503, "Serviço de dispositivos indisponível.") from exc
    if not isinstance(result, dict) or result.get("sucesso") is not True:
        detail = result.get("erro", "Falha ao consultar dispositivos.") if isinstance(result, dict) else "Resposta inválida."
        raise HTTPException(response.status_code if 400 <= response.status_code < 500 else 503, detail)
    return result


def hash_endpoint(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def valid_endpoint(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
        return u.scheme == "https" and bool(u.hostname) and not u.username and not u.password and u.port in (None, 443) and len(endpoint) <= 2048 and (
            u.hostname == "fcm.googleapis.com"
            or u.hostname.endswith(".push.apple.com")
            or u.hostname.endswith(".push.services.mozilla.com")
            or u.hostname == "updates.push.services.mozilla.com"
            or u.hostname == "wns2-pn1p.notify.windows.com"
            or u.hostname.endswith(".notify.windows.com")
            or u.hostname == "android.googleapis.com"
            or u.hostname.endswith(".googleapis.com")
        )
    except ValueError:
        return False


class Subscription(BaseModel):
    endpoint: str = Field(min_length=20, max_length=2048)
    keys: dict[str, str]


class Register(BaseModel):
    inscricao: Subscription
    descricao: str = Field(default="", max_length=90)
    plataforma: str = Field(default="", max_length=90)


class Revoke(BaseModel):
    id: str = Field(default="", max_length=60)
    endpoint: str = Field(default="", max_length=2048)


@router.get("/config")
async def config(response: Response, user: dict = Depends(principal)):
    no_store(response)
    return {"sucesso": True, "publicKey": VAPID_PUBLIC, "enabled": bool(VAPID_PRIVATE and VAPID_PUBLIC and VAPID_SUBJECT)}


@router.post("/devices")
async def register(payload: Register, response: Response, user: dict = Depends(principal)):
    no_store(response)
    sub = payload.inscricao
    keys = sub.keys
    if not valid_endpoint(sub.endpoint) or not (
        70 <= len(keys.get("p256dh", "")) <= 120 and 15 <= len(keys.get("auth", "")) <= 50
    ):
        raise HTTPException(422, "Assinatura de dispositivo inválida.")
    return await edge("REGISTER", usuario=user_id(user), inscricao=sub.model_dump(),
                      endpoint_hash=hash_endpoint(sub.endpoint),
                      descricao=payload.descricao, plataforma=payload.plataforma)


@router.get("/devices")
async def devices(response: Response, user: dict = Depends(principal)):
    no_store(response)
    return await edge("MY_DEVICES", usuario=user_id(user))


@router.post("/devices/revoke")
async def revoke(payload: Revoke, response: Response, user: dict = Depends(principal)):
    no_store(response)
    if not payload.id and not payload.endpoint:
        raise HTTPException(422, "Informe o dispositivo.")
    return await edge("REVOKE", usuario=user_id(user), id=payload.id,
                      endpoint_hash=hash_endpoint(payload.endpoint) if payload.endpoint else "")


@router.get("/notification/{notice_id}/destination")
async def destination(notice_id: str, response: Response, user: dict = Depends(principal)):
    no_store(response)
    return await edge("DESTINATION", usuario=user_id(user), id=notice_id)


@lru_cache(maxsize=1)
def vapid_pem():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    raw = base64.urlsafe_b64decode(VAPID_PRIVATE + "=" * (-len(VAPID_PRIVATE) % 4))
    if len(raw) != 32:
        raise RuntimeError("Chave VAPID inválida.")
    priv = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    der = priv.private_bytes(serialization.Encoding.DER,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    return base64.urlsafe_b64encode(der).decode('ascii')


def _deliver(subscription: dict, notice_id: str):
    from pywebpush import webpush, WebPushException
    endpoint = str(subscription.get("endpoint") or "")
    if not valid_endpoint(endpoint):
        return False, True
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"id": notice_id, "title": "DISMEPE ONE",
                             "body": "Você recebeu uma nova notificação.",
                             "url": "/?dismepe_notice=" + notice_id}, ensure_ascii=False),
            vapid_private_key=vapid_pem(),
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=86400,
            timeout=8,
        )
        return True, False
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning("Falha de entrega Push: status=%s", status)
        return False, status in (404, 410)
    except Exception as exc:
        log.warning("Falha de entrega Push: %s", type(exc).__name__)
        return False, False


async def deliver_notice(notice_id: str):
    """Envio após confirmação SQL, independente da leitura do sino atual."""
    if not (VAPID_PUBLIC and VAPID_PRIVATE and VAPID_SUBJECT):
        log.warning("Push indisponível: chaves não configuradas.")
        return
    try:
        data = await edge("RECIPIENTS", id=notice_id)
    except HTTPException:
        log.warning("Push não disparado: destinatários SQL indisponíveis.")
        return
    devices_list = data.get("dispositivos") or []
    sent = invalid = 0
    for row in devices_list:
        if not isinstance(row, dict):
            continue
        sub = row.get("inscricao")
        if not isinstance(sub, dict):
            continue
        success, gone = await asyncio.to_thread(_deliver, sub, notice_id)
        sent += int(success)
        invalid += int(gone)
        try:
            await edge("DELIVERY_RESULT", endpoint_hash=row.get("endpoint_hash"),
                       sucesso=success, invalido=gone)
        except HTTPException:
            log.warning("Não foi possível registrar status de Push.")
    log.info("Push DISMEPE ONE: aviso=%s dispositivos=%d entregues=%d expirados=%d",
             notice_id[:16], len(devices_list), sent, invalid)


@router.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(ROOT / "frontend" / "push-sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store", "Service-Worker-Allowed": "/",
                                 "X-Content-Type-Options": "nosniff"})


@router.get("/icon.svg", include_in_schema=False)
async def icon():
    return FileResponse(ROOT / "frontend" / "push-icon.svg", media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(ROOT / "frontend" / "push-manifest.webmanifest",
                        media_type="application/manifest+json",
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/client.js", include_in_schema=False)
async def client_js():
    return FileResponse(ROOT / "frontend" / "push-client.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
