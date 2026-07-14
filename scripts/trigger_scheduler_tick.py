#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://news-keep-up.vercel.app"
DEFAULT_ENV_PATH = Path(".vercel/.env.production.local")
LOCK_PATH = Path("/tmp/news-keep-up-scheduler-tick.lock")


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger the production news-keep-up scheduler tick.")
    parser.add_argument("--base-url", default=os.environ.get("NEWS_KEEP_UP_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--env-file", default=os.environ.get("NEWS_KEEP_UP_ENV_FILE", str(DEFAULT_ENV_PATH)))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("NEWS_KEEP_UP_TICK_TIMEOUT", "295")))
    args = parser.parse_args()

    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(_log_line({"ok": True, "skipped": "another tick is still running"}), flush=True)
            return 0

        secret = _cron_secret(Path(args.env_file))
        if not secret:
            print(_log_line({"ok": False, "error": "CRON_SECRET not found"}), flush=True)
            return 1

        return _trigger(args.base_url.rstrip("/"), secret, args.timeout)


def _trigger(base_url: str, secret: str, timeout: int) -> int:
    request = Request(
        f"{base_url}/api/scheduler/tick",
        headers={"Authorization": f"Bearer {secret}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            print(_log_line({"status": response.status, **payload}), flush=True)
            return 0 if response.status == 200 and payload.get("ok") is True else 1
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(_log_line({"ok": False, "status": exc.code, "error": body[:500]}), flush=True)
        return 1
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(_log_line({"ok": False, "error": str(exc)}), flush=True)
        return 1


def _cron_secret(path: Path) -> str:
    value = os.environ.get("CRON_SECRET", "")
    if value:
        return value
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        if key.strip() != "CRON_SECRET":
            continue
        raw = raw.strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        return raw
    return ""


def _log_line(payload: dict) -> str:
    return json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **payload,
    }, ensure_ascii=True, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
