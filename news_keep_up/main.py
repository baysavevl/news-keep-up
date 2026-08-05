from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from .config import load_settings
from .db import connect_database, init_db, list_source_fetch_health
from .digest import run_digest
from .interview import run_fde_interview_guideline
from .job_alerts import probe_fde_job_sources, run_fde_job_alerts
from .scheduler_runner import SCHEDULER_TICK_LOOKBACK_MINUTES, run_scheduler_tick, run_scheduler_worker
from .source_intelligence import run_fde_job_source_intelligence

PROFILE_SOURCE_PATHS = {
    "engineer": "config/sources.json",
    "fde": "config/fde_sources.json",
    "fde-interview": "config/fde_interview_sources.json",
    "fde-jobs": "config/fde_job_sources.json",
    "fde-job-sources": "config/fde_job_source_discovery_sources.json",
    "news": "config/sources.json",
    "morning": "config/sources.json",
    "afternoon": "config/sources.json",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-keep-up")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Initialize the local or Turso database")
    init_parser.add_argument("--db-path", help="Override local SQLite DB path")

    run_parser = subparsers.add_parser("run-digest", help="Fetch, enrich, select, and send a digest")
    run_parser.add_argument("--slot", choices=sorted(PROFILE_SOURCE_PATHS), required=True)
    run_parser.add_argument("--dry-run", action="store_true", help="Print digest instead of sending Telegram")
    run_parser.add_argument("--db-path", help="Override local SQLite DB path")
    run_parser.add_argument("--env-file", help="Load environment variables from a .env file before running")
    run_parser.add_argument("--sources-path", help="Override source config path")
    run_parser.add_argument("--force", action="store_true", help="Force fde-jobs delivery outside the normal send window")

    tick_parser = subparsers.add_parser("scheduler-tick", help="Run one scheduler tick in-process")
    tick_parser.add_argument("--db-path", help="Override local SQLite DB path")
    tick_parser.add_argument("--env-file", help="Load environment variables from a .env file before running")
    tick_parser.add_argument("--lookback-minutes", type=int, default=SCHEDULER_TICK_LOOKBACK_MINUTES)
    tick_parser.add_argument("--max-jobs-per-tick", type=int, default=0, help="0 means no service-side cap")

    worker_parser = subparsers.add_parser("scheduler-worker", help="Run the scheduler as a long-lived service")
    worker_parser.add_argument("--db-path", help="Override local SQLite DB path")
    worker_parser.add_argument("--env-file", help="Load environment variables from a .env file before running")
    worker_parser.add_argument("--interval-seconds", type=int, default=60)
    worker_parser.add_argument("--lookback-minutes", type=int, default=SCHEDULER_TICK_LOOKBACK_MINUTES)
    worker_parser.add_argument("--max-jobs-per-tick", type=int, default=0, help="0 means no service-side cap")
    worker_parser.add_argument("--once", action="store_true", help="Run one tick and exit")

    health_parser = subparsers.add_parser("source-health", help="Show recent failing or empty sources")
    health_parser.add_argument("--db-path", help="Override local SQLite DB path")
    health_parser.add_argument("--env-file", help="Load environment variables from a .env file before running")
    health_parser.add_argument("--slot", default="", help="Filter by slot, for example fde-jobs")
    health_parser.add_argument("--since", default="", help="Only include fetch logs at or after this ISO timestamp")
    health_parser.add_argument("--limit", type=int, default=10)
    health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    probe_parser = subparsers.add_parser("probe-job-sources", help="Fetch FDE job sources and log source health without LLM classification or Telegram delivery")
    probe_parser.add_argument("--db-path", help="Override local SQLite DB path")
    probe_parser.add_argument("--env-file", help="Load environment variables from a .env file before running")
    probe_parser.add_argument("--sources-path", default="config/fde_job_sources.json")
    probe_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "env_file", None):
        _apply_env_file(args.env_file)
    settings = load_settings()
    if getattr(args, "db_path", None):
        settings = replace(settings, db_path=args.db_path)

    if args.command == "init-db":
        conn = connect_database(settings)
        init_db(conn)
        print(f"Database initialized at {settings.db_path}")
        return 0

    if args.command == "run-digest":
        sources_path = args.sources_path or PROFILE_SOURCE_PATHS[args.slot]
        if args.slot == "fde-interview":
            message = run_fde_interview_guideline(settings, dry_run=args.dry_run)
        elif args.slot == "fde-jobs":
            message = run_fde_job_alerts(
                settings,
                dry_run=args.dry_run,
                sources_path=sources_path,
                force=args.force,
            )
        elif args.slot == "fde-job-sources":
            message = run_fde_job_source_intelligence(settings, dry_run=args.dry_run, discovery_sources_path=sources_path)
        else:
            message = run_digest(settings, args.slot, dry_run=args.dry_run, sources_path=sources_path)
        if args.dry_run:
            print(message)
        return 0

    if args.command == "scheduler-tick":
        result = run_scheduler_tick(
            settings=settings,
            lookback_minutes=args.lookback_minutes,
            max_jobs_per_tick=_max_jobs_arg(args.max_jobs_per_tick),
        )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0

    if args.command == "scheduler-worker":
        run_scheduler_worker(
            settings=settings,
            interval_seconds=args.interval_seconds,
            lookback_minutes=args.lookback_minutes,
            max_jobs_per_tick=_max_jobs_arg(args.max_jobs_per_tick),
            stop_after_ticks=1 if args.once else None,
        )
        return 0

    if args.command == "source-health":
        conn = connect_database(settings)
        init_db(conn)
        try:
            health = list_source_fetch_health(
                conn,
                slot=args.slot,
                since=args.since,
                limit=args.limit,
            )
        finally:
            conn.close()
        if args.json:
            print(json.dumps([row.__dict__ for row in health], ensure_ascii=True, sort_keys=True))
        else:
            print(_source_health_text(health))
        return 0

    if args.command == "probe-job-sources":
        summary = probe_fde_job_sources(settings, sources_path=args.sources_path)
        if args.json:
            print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
        else:
            print(_job_source_probe_text(summary))
        return 0

    parser.error("unknown command")
    return 2


def _max_jobs_arg(value: int) -> int | None:
    return value if value > 0 else None


def _apply_env_file(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        os.environ.setdefault(key, raw)


def _source_health_text(health) -> str:
    if not health:
        return "No source fetch logs found."
    lines = ["Source health"]
    for row in health:
        parts = [
            row.source_name,
            f"failed={row.failed_runs}",
            f"empty={row.empty_runs}",
            f"items={row.total_items}",
            f"last={row.last_status}",
        ]
        if row.last_error:
            parts.append(row.last_error)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _job_source_probe_text(summary: dict) -> str:
    lines = [
        "FDE job source probe",
        (
            f"sources={summary.get('sources', 0)} "
            f"fetched={summary.get('fetched_items', 0)} "
            f"source_filtered={summary.get('source_filtered_candidates', 0)} "
            f"fde={summary.get('fde_candidates', 0)} "
            f"workable={summary.get('workable_candidates', 0)}"
        ),
    ]
    rows = sorted(
        summary.get("rows", []),
        key=lambda row: (
            -int(row.get("workable_candidates", 0)),
            -int(row.get("fde_candidates", 0)),
            -int(row.get("fetched_items", 0)),
        ),
    )
    for row in rows[:12]:
        lines.append(
            f"{row.get('source', '')} | fetched={row.get('fetched_items', 0)} "
            f"filtered={row.get('source_filtered_candidates', 0)} "
            f"fde={row.get('fde_candidates', 0)} "
            f"workable={row.get('workable_candidates', 0)}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
