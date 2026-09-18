from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from .industries_stock_sync import (
    WORKER_PID_FILE,
    _state_update,
    _sync_stock_once_blocking,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        os.nice(15)
    except (AttributeError, OSError):
        pass

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
        _sync_stock_once_blocking(force=bool(args.force))
        return 0
    except Exception as exc:
        _state_update(
            lastStatus="ERROR",
            lastAttemptAt=datetime.now(timezone.utc).isoformat(),
            workerPid=None,
            lastError=str(exc)[:700],
        )
        print(f"stock-worker error: {exc}", flush=True)
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
