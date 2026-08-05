from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from typing import Callable, TextIO

from .config import load_settings
from .db import claim_scheduler_run, connect_database, finish_scheduler_run, init_db
from .models import Settings
from .profiles import DIGEST_PROFILES, DigestProfile, run_digest_profile
from .scheduler import due_digest_jobs
from .utils import now_ict

SCHEDULER_TICK_LOOKBACK_MINUTES = 180


def run_scheduler_tick(
    settings: Settings | None = None,
    current: datetime | None = None,
    lookback_minutes: int = SCHEDULER_TICK_LOOKBACK_MINUTES,
    max_jobs_per_tick: int | None = None,
    profile_runner: Callable[..., dict] = run_digest_profile,
    profiles: dict[str, DigestProfile] = DIGEST_PROFILES,
) -> dict:
    checked_at = current or now_ict()
    base_settings = settings or load_settings()
    conn = connect_database(base_settings)
    init_db(conn)
    results = []
    triggered = 0
    try:
        for job in due_digest_jobs(checked_at, lookback_minutes=lookback_minutes):
            if max_jobs_per_tick is not None and triggered >= max_jobs_per_tick:
                break
            if not claim_scheduler_run(conn, job.slot, job.scheduled_for_key, checked_at.isoformat()):
                results.append({
                    "slot": job.slot,
                    "scheduled_for": job.scheduled_for_key,
                    "status": "already_handled",
                })
                continue

            triggered += 1
            profile = profiles[job.slot]
            try:
                result = profile_runner(
                    profile,
                    dry_run=False,
                    current=job.scheduled_for,
                    send_window_current=checked_at,
                )
            except Exception as exc:
                finish_scheduler_run(
                    conn,
                    job.slot,
                    job.scheduled_for_key,
                    "failed",
                    error=str(exc),
                )
                results.append({
                    "slot": job.slot,
                    "scheduled_for": job.scheduled_for_key,
                    "status": "failed",
                    "error": str(exc),
                })
                continue

            finish_scheduler_run(
                conn,
                job.slot,
                job.scheduled_for_key,
                "done",
                message_length=int(result.get("message_length", 0)),
            )
            results.append({
                "slot": job.slot,
                "scheduled_for": job.scheduled_for_key,
                "status": "done",
                **result,
            })
    finally:
        conn.close()

    return {
        "ok": True,
        "triggered": triggered,
        "checked_at": checked_at.isoformat(),
        "results": results,
    }


def run_scheduler_worker(
    settings: Settings | None = None,
    interval_seconds: int = 60,
    lookback_minutes: int = SCHEDULER_TICK_LOOKBACK_MINUTES,
    max_jobs_per_tick: int | None = None,
    stop_after_ticks: int | None = None,
    output: TextIO | None = None,
) -> list[dict]:
    sink = output or sys.stdout
    results: list[dict] = []
    tick_count = 0
    while stop_after_ticks is None or tick_count < stop_after_ticks:
        result = run_scheduler_tick(
            settings=settings,
            lookback_minutes=lookback_minutes,
            max_jobs_per_tick=max_jobs_per_tick,
        )
        results.append(result)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True), file=sink, flush=True)
        tick_count += 1
        if stop_after_ticks is not None and tick_count >= stop_after_ticks:
            break
        time.sleep(max(1, interval_seconds))
    return results
