from __future__ import annotations

import sys
import httpx

URL = "http://localhost:8000/health"

try:
    r = httpx.get(URL, timeout=5)
    data = r.json()
except Exception as exc:
    print("FALHA: API não respondeu:", exc)
    raise SystemExit(1)

print("HTTP:", r.status_code)
print("Serviço:", data.get("service"))
print("Versão:", data.get("version"))
print("Config OK:", data.get("ok"))
if data.get("missingConfig"):
    print("Configuração faltando:", ", ".join(data["missingConfig"]))

raise SystemExit(0 if r.status_code == 200 and data.get("ok") else 1)
