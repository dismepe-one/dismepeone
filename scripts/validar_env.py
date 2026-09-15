from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

REQUIRED = [
    "DISMEPE_SUPABASE_URL",
    "DISMEPE_SUPABASE_PUBLISHABLE_KEY",
    "DISMEPE_EDGE_TOKEN",
    "DISMEPE_AUTH_PEPPER",
    "DISMEPE_JWT_SECRET",
    "DISMEPE_CORS_ORIGINS",
    "DISMEPE_COOKIE_SECURE",
]

PLACEHOLDER_MARKERS = (
    "COLE_AQUI",
    "CHAVE_PUBLICAVEL",
    "SEGREDO_NOVO",
    "PREENCHA",
)


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def main() -> int:
    if not ENV.exists():
        print("ERRO: arquivo .env não encontrado.")
        return 1

    data = parse_env(ENV)
    errors: list[str] = []

    for key in REQUIRED:
        value = data.get(key, "")
        if not value:
            errors.append(f"{key}: ausente/vazio")
            continue
        if any(marker in value.upper() for marker in PLACEHOLDER_MARKERS):
            errors.append(f"{key}: ainda está com valor de exemplo")

    jwt = data.get("DISMEPE_JWT_SECRET", "")
    if jwt and len(jwt) < 32:
        errors.append("DISMEPE_JWT_SECRET: deve ter pelo menos 32 caracteres")

    url = data.get("DISMEPE_SUPABASE_URL", "")
    if url and not re.match(r"^https://[a-z0-9-]+\.supabase\.co/?$", url, re.I):
        errors.append("DISMEPE_SUPABASE_URL: formato inesperado")

    cookie_secure = data.get("DISMEPE_COOKIE_SECURE", "").lower()
    if cookie_secure not in {"true", "false"}:
        errors.append("DISMEPE_COOKIE_SECURE: use true ou false")

    if errors:
        print("\nENV AINDA NÃO ESTÁ PRONTO:\n")
        for item in errors:
            print(" -", item)
        print("\nNenhum segredo foi exibido.")
        return 1

    print("OK: .env preenchido e formato básico validado.")
    print("OK: nenhum segredo foi exibido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
