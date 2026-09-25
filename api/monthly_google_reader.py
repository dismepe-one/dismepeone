"""Credenciais exclusivas da homologação mensal.

Nunca reutiliza as variáveis da conta de serviço do aplicativo oficial.
O JSON permanece somente no ambiente privado do Render.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any


class MonthlyGoogleReaderError(RuntimeError):
    pass


def monthly_google_reader_info() -> dict[str, Any] | None:
    encoded = os.getenv("DISMEPE_MONTHLY_GOOGLE_READER_B64", "").strip()
    if not encoded:
        return None
    try:
        data = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise MonthlyGoogleReaderError("Conta Google de homologação inválida.") from exc
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise MonthlyGoogleReaderError("Conta Google de homologação inválida.")
    email = data.get("client_email")
    expected = os.getenv("DISMEPE_MONTHLY_GOOGLE_READER_EMAIL", "").strip().lower()
    if not isinstance(email, str) or not expected or email.lower() != expected:
        raise MonthlyGoogleReaderError("Identidade Google exclusiva não confirmada.")
    return data
