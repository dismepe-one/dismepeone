from __future__ import annotations

import os
import sys
from pathlib import Path

REQUIRED = [
    "DISMEPE_SUPABASE_URL",
    "DISMEPE_SUPABASE_PUBLISHABLE_KEY",
    "DISMEPE_EDGE_TOKEN",
    "DISMEPE_AUTH_PEPPER",
    "DISMEPE_JWT_SECRET",
]

root = Path(__file__).resolve().parents[1]
portal = root / "frontend" / "portal-v2-homolog.html"
missing = [name for name in REQUIRED if not os.getenv(name, "").strip()]
errors: list[str] = []

if missing:
    errors.append("Variáveis ausentes: " + ", ".join(missing))
if len(os.getenv("DISMEPE_JWT_SECRET", "")) < 32:
    errors.append("DISMEPE_JWT_SECRET precisa ter pelo menos 32 caracteres")
if os.getenv("DISMEPE_COOKIE_SECURE", "").lower() not in {"true", "1", "yes", "on"}:
    errors.append("DISMEPE_COOKIE_SECURE precisa estar true em produção HTTPS")
if os.getenv("ENVIRONMENT", "").lower() != "production":
    errors.append("ENVIRONMENT precisa estar production")
origins = os.getenv("DISMEPE_CORS_ORIGINS", "")
if not origins or "127.0.0.1" in origins or "localhost" in origins:
    errors.append("DISMEPE_CORS_ORIGINS precisa usar o domínio HTTPS real, sem localhost/127.0.0.1")
if not portal.is_file():
    errors.append(f"Frontend não encontrado: {portal}")

if errors:
    print("PREFLIGHT PRODUÇÃO: FALHOU")
    for item in errors:
        print("-", item)
    sys.exit(1)

print("PREFLIGHT PRODUÇÃO: OK")
print("- frontend incluído")
print("- segredos obrigatórios presentes")
print("- cookie Secure habilitado")
print("- ambiente production")
print("- CORS sem origem local")
