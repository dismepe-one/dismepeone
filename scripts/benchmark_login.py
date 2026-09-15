from __future__ import annotations

import getpass
import statistics
import time
from math import ceil

import httpx

API = "http://localhost:8000"
N = 20

usuario = input("Usuário real para teste: ").strip()
senha = getpass.getpass("Senha (não será exibida nem gravada): ")

if not usuario or not senha:
    raise SystemExit("Usuário e senha são obrigatórios.")

wall_times = []
server_times = []
failures = []

for i in range(1, N + 1):
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                API + "/auth/login",
                json={"usuario": usuario, "senha": senha},
            )
            elapsed = (time.perf_counter() - started) * 1000
            if r.status_code != 200:
                failures.append((i, r.status_code, r.text[:180]))
                print(f"{i:02d}/{N} FALHA HTTP {r.status_code} - {elapsed:.0f} ms")
                continue

            data = r.json()
            wall_times.append(elapsed)
            server_times.append(float(data.get("elapsedMs") or elapsed))

            # encerra a sessão criada neste ciclo
            try:
                client.post(API + "/auth/logout")
            except Exception:
                pass

            print(
                f"{i:02d}/{N} OK | navegador/API: {elapsed:.0f} ms "
                f"| servidor: {server_times[-1]:.0f} ms"
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        failures.append((i, "EXC", str(exc)))
        print(f"{i:02d}/{N} FALHA | {elapsed:.0f} ms | {exc}")

if not wall_times:
    raise SystemExit("\nNenhum login foi concluído com sucesso.")

ordered = sorted(wall_times)
p95_index = max(0, min(len(ordered) - 1, ceil(len(ordered) * 0.95) - 1))

print("\n=== RESULTADO ===")
print("Sucessos:", len(wall_times))
print("Falhas:", len(failures))
print(f"Mediana: {statistics.median(wall_times):.0f} ms")
print(f"P95: {ordered[p95_index]:.0f} ms")
print(f"Mínimo: {min(wall_times):.0f} ms")
print(f"Máximo: {max(wall_times):.0f} ms")
print(f"Servidor mediana: {statistics.median(server_times):.0f} ms")

approved = (
    len(failures) == 0
    and statistics.median(wall_times) < 1000
    and ordered[p95_index] < 2000
)

print("Status Fase 1:", "APROVADA" if approved else "AINDA NÃO APROVADA")

if failures:
    print("\nFalhas:")
    for item in failures[:10]:
        print(" -", item)
