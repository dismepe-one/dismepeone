from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

from .industries_stock_sync import (
    WORKER_PID_FILE,
    _state_update,
    _sync_stock_once_blocking,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    args = parser.parse_args()

    started_monotonic = time.monotonic()

    pid = os.getpid()
    WORKER_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKER_PID_FILE.write_text(str(pid), encoding="utf-8")
    _state_update(
        lastStatus="RUNNING",
        lastAttemptAt=datetime.now(timezone.utc).isoformat(),
        workerPid=pid,
        lastError=None,
    )

    try:
        result = _sync_stock_once_blocking(force=bool(args.force))
        if args.scheduled and result.get("lastStatus") == "IMPORTED":
            from .industries_stock_notice import notify_stock_worker
            notify_stock_worker(str(result.get("lastSha256") or ""))
        duration = round(time.monotonic() - started_monotonic, 2)
        _state_update(lastDurationSeconds=duration, workerPid=None)
        print(
            f"stock-worker complete status={result.get('lastStatus')} "
            f"rows={result.get('lastRows')} duration={duration}s",
            flush=True,
        )
        return 0
    except Exception as exc:
        duration = round(time.monotonic() - started_monotonic, 2)
        _state_update(
            lastStatus="ERROR",
            lastAttemptAt=datetime.now(timezone.utc).isoformat(),
            lastDurationSeconds=duration,
            workerPid=None,
            lastError=str(exc)[:700],
        )
        print(f"stock-worker error duration={duration}s: {exc}", flush=True)
        return 1
    finally:
        try:
            current = WORKER_PID_FILE.read_text(encoding="utf-8").strip()
            if current == str(pid):
                WORKER_PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
