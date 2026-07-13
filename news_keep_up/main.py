from __future__ import annotations

import argparse
from dataclasses import replace

from .config import load_settings
from .db import connect_database, init_db
from .digest import run_digest
from .interview import run_fde_interview_guideline

PROFILE_SOURCE_PATHS = {
    "engineer": "config/sources.json",
    "fde": "config/fde_sources.json",
    "fde-interview": "config/fde_interview_sources.json",
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
    run_parser.add_argument("--sources-path", help="Override source config path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
        else:
            message = run_digest(settings, args.slot, dry_run=args.dry_run, sources_path=sources_path)
        if args.dry_run:
            print(message)
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
