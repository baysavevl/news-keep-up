from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, Response, jsonify, request

from .config import load_settings
from .db import (
    claim_scheduler_run,
    connect_database,
    finish_scheduler_run,
    init_db,
    mark_delivered,
    row_value,
)
from .digest import run_digest
from .interview import run_fde_interview_guideline
from .scheduler import due_digest_jobs
from .telegram import set_telegram_chat_photo
from .telegram_commands import handle_telegram_update
from .utils import now_ict


@dataclass(frozen=True)
class DigestProfile:
    slot: str
    sources_path: str
    env_prefix: str = ""
    mode: str = "digest"


DIGEST_PROFILES = {
    "news": DigestProfile("news", "config/sources.json"),
    "morning": DigestProfile("morning", "config/sources.json"),
    "afternoon": DigestProfile("afternoon", "config/sources.json"),
    "engineer": DigestProfile("engineer", "config/sources.json", "ENGINEER"),
    "fde": DigestProfile("fde", "config/fde_sources.json", "FDE"),
    "fde-interview": DigestProfile("fde-interview", "config/fde_interview_sources.json", "FDE", "interview"),
}

app = Flask(__name__)

AVATAR_PATHS = {
    "engineer": Path(__file__).resolve().parent.parent / "assets" / "telegram" / "engineer-ai-avatar.png",
    "fde": Path(__file__).resolve().parent.parent / "assets" / "telegram" / "fde-avatar.png",
}

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="news-keep-up favicon">
  <rect width="64" height="64" rx="14" fill="#0f172a"/>
  <path d="M18 17h28a4 4 0 0 1 4 4v25a4 4 0 0 1-4 4H18a4 4 0 0 1-4-4V21a4 4 0 0 1 4-4Z" fill="#f8fafc"/>
  <path d="M22 25h20M22 33h20M22 41h13" stroke="#0f172a" stroke-width="4" stroke-linecap="round"/>
  <path d="M44 39c4-5 4-13 0-18" stroke="#14b8a6" stroke-width="4" stroke-linecap="round" fill="none"/>
  <path d="M51 45c7-9 7-24 0-34" stroke="#38bdf8" stroke-width="4" stroke-linecap="round" fill="none"/>
</svg>
"""


@app.get("/")
def health_check():
    return jsonify({"ok": True, "service": "news-keep-up"})


@app.get("/favicon.svg")
@app.get("/favicon.ico")
def favicon():
    return Response(
        FAVICON_SVG,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/digest/<slot>")
def digest_endpoint(slot: str):
    profile = DIGEST_PROFILES.get(slot)
    if profile is None:
        return jsonify({"ok": False, "error": "invalid digest slot"}), 400

    auth_error = _cron_auth_error()
    if auth_error is not None:
        return auth_error

    dry_run = request.args.get("dry_run", "").lower() in {"1", "true", "yes"}
    try:
        result = _run_digest_profile(profile, dry_run=dry_run)
    except Exception as exc:
        app.logger.exception("Digest run failed")
        return jsonify({"ok": False, "slot": slot, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "slot": slot,
        "dry_run": dry_run,
        **result,
    })


@app.get("/api/scheduler/tick")
def scheduler_tick_endpoint():
    auth_error = _cron_auth_error()
    if auth_error is not None:
        return auth_error

    current = now_ict()
    base_settings = load_settings()
    conn = connect_database(base_settings)
    init_db(conn)
    results = []
    triggered = 0
    max_jobs_per_tick = 1
    try:
        for job in due_digest_jobs(current):
            if triggered >= max_jobs_per_tick:
                break
            if not claim_scheduler_run(conn, job.slot, job.scheduled_for_key, current.isoformat()):
                results.append({
                    "slot": job.slot,
                    "scheduled_for": job.scheduled_for_key,
                    "status": "already_handled",
                })
                continue

            triggered += 1
            profile = DIGEST_PROFILES[job.slot]
            try:
                result = _run_digest_profile(profile, dry_run=False)
            except Exception as exc:
                app.logger.exception("Scheduled digest run failed")
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

    return jsonify({
        "ok": True,
        "triggered": triggered,
        "checked_at": current.isoformat(),
        "results": results,
    })


@app.post("/api/telegram/<slot>")
def telegram_webhook_endpoint(slot: str):
    profile = DIGEST_PROFILES.get(slot)
    if profile is None:
        return jsonify({"ok": False, "error": "invalid telegram slot"}), 400

    auth_error = _telegram_webhook_auth_error()
    if auth_error is not None:
        return auth_error

    settings = load_settings(env_prefix=profile.env_prefix)
    if not settings.telegram_bot_token:
        return jsonify({"ok": False, "slot": slot, "error": "Telegram bot token is not configured"}), 500

    try:
        result = handle_telegram_update(
            request.get_json(silent=True) or {},
            slot=profile.slot,
            sources_path=profile.sources_path,
            settings=settings,
        )
    except Exception as exc:
        app.logger.exception("Telegram command failed")
        return jsonify({"ok": False, "slot": slot, "error": str(exc)}), 500

    return jsonify({"slot": slot, **result})


@app.post("/api/admin/avatar/<slot>")
def avatar_admin_endpoint(slot: str):
    profile = DIGEST_PROFILES.get(slot)
    if profile is None or slot not in AVATAR_PATHS:
        return jsonify({"ok": False, "error": "invalid avatar slot"}), 400

    auth_error = _cron_auth_error()
    if auth_error is not None:
        return auth_error

    settings = load_settings(env_prefix=profile.env_prefix)
    if not _telegram_delivery_configured(settings):
        return jsonify({"ok": False, "slot": slot, "error": "Telegram delivery is not configured"}), 500

    try:
        set_telegram_chat_photo(settings, AVATAR_PATHS[slot])
    except Exception as exc:
        app.logger.exception("Telegram avatar update failed")
        return jsonify({"ok": False, "slot": slot, "error": str(exc)}), 500

    return jsonify({"ok": True, "slot": slot})


@app.post("/api/admin/mark-delivered/<slot>")
def mark_delivered_admin_endpoint(slot: str):
    profile = DIGEST_PROFILES.get(slot)
    if profile is None:
        return jsonify({"ok": False, "error": "invalid mark-delivered slot"}), 400

    auth_error = _cron_auth_error()
    if auth_error is not None:
        return auth_error

    settings = load_settings(env_prefix=profile.env_prefix)
    conn = connect_database(settings)
    init_db(conn)
    try:
        item_ids = _undelivered_item_ids(conn, limit=200)
        mark_delivered(conn, item_ids, slot, set())
    finally:
        conn.close()

    return jsonify({"ok": True, "slot": slot, "marked": len(item_ids)})


def _cron_auth_error():
    cron_secret = os.environ.get("CRON_SECRET", "")
    if not cron_secret:
        return jsonify({"ok": False, "error": "CRON_SECRET is not configured"}), 500

    if request.headers.get("Authorization", "") != f"Bearer {cron_secret}":
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    return None


def _telegram_webhook_auth_error():
    webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET") or os.environ.get("CRON_SECRET", "")
    if not webhook_secret:
        return jsonify({"ok": False, "error": "TELEGRAM_WEBHOOK_SECRET or CRON_SECRET is not configured"}), 500

    if request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != webhook_secret:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    return None


def _telegram_delivery_configured(settings) -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def _run_digest_profile(profile: DigestProfile, dry_run: bool) -> dict:
    settings = load_settings(env_prefix=profile.env_prefix)
    if not dry_run and not _telegram_delivery_configured(settings):
        return {
            "delivery_configured": False,
            "message": "Telegram delivery is not configured for this digest profile.",
            "message_length": 0,
        }

    if profile.mode == "interview":
        message = run_fde_interview_guideline(settings, dry_run=dry_run)
    else:
        message = run_digest(
            settings,
            profile.slot,
            dry_run=dry_run,
            sources_path=profile.sources_path,
        )
    return {
        "delivery_configured": True,
        "message_length": len(message),
    }


def _undelivered_item_ids(conn, limit: int) -> list[int]:
    rows = conn.execute(
        """SELECT i.id
           FROM items i
           JOIN enrichments e ON e.item_id = i.id
           WHERE e.should_send = 1
             AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)
           ORDER BY e.relevance_score DESC, i.published_at DESC, i.fetched_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [int(row_value(row, "id", 0)) for row in rows]
