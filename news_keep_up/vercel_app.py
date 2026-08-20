from __future__ import annotations

import os
from base64 import b64decode
from dataclasses import dataclass, replace
from pathlib import Path

from flask import Flask, Response, jsonify, request

from .config import load_settings
from .db import (
    claim_scheduler_run,
    connect_database,
    finish_scheduler_run,
    get_profile_setting,
    init_db,
    mark_delivered,
    row_value,
)
from .digest import run_digest
from .interview import run_fde_interview_guideline
from .job_alerts import run_fde_job_alerts
from .scheduler import due_digest_jobs
from .source_intelligence import run_fde_job_source_intelligence
from .telegram import set_telegram_chat_photo
from .telegram_commands import handle_telegram_update
from .utils import now_ict


@dataclass(frozen=True)
class DigestProfile:
    slot: str
    sources_path: str
    env_prefix: str = ""
    mode: str = "digest"
    telegram_chat_id_env: str = ""
    telegram_bot_token_env: str = ""


DIGEST_PROFILES = {
    "news": DigestProfile("news", "config/sources.json"),
    "morning": DigestProfile("morning", "config/sources.json"),
    "afternoon": DigestProfile("afternoon", "config/sources.json"),
    "engineer": DigestProfile("engineer", "config/sources.json", "ENGINEER"),
    "fde": DigestProfile("fde", "config/fde_sources.json", "FDE"),
    "fde-interview": DigestProfile("fde-interview", "config/fde_interview_sources.json", "FDE", "interview"),
    "fde-jobs": DigestProfile(
        "fde-jobs",
        "config/fde_job_sources.json",
        "FDE",
        "jobs",
        telegram_chat_id_env="FDE_JOBS_TELEGRAM_CHAT_ID",
        telegram_bot_token_env="FDE_JOBS_TELEGRAM_BOT_TOKEN",
    ),
    "fde-job-sources": DigestProfile(
        "fde-job-sources",
        "config/fde_job_source_discovery_sources.json",
        "FDE",
        "source-intelligence",
    ),
}

app = Flask(__name__)
SCHEDULER_TICK_LOOKBACK_MINUTES = 180

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
    force = request.args.get("force", "").lower() in {"1", "true", "yes"}
    try:
        result = _run_digest_profile(profile, dry_run=dry_run, force=force)
    except Exception as exc:
        app.logger.exception("Digest run failed")
        return jsonify({"ok": False, "slot": slot, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "slot": slot,
        "dry_run": dry_run,
        "force": force,
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
    max_jobs_per_tick = 3
    try:
        for job in due_digest_jobs(current, lookback_minutes=SCHEDULER_TICK_LOOKBACK_MINUTES):
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
                result = _run_digest_profile(
                    profile,
                    dry_run=False,
                    current=job.scheduled_for,
                    send_window_current=current,
                )
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

    settings = _settings_for_profile(profile)
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


def _run_digest_profile(
    profile: DigestProfile,
    dry_run: bool,
    current=None,
    send_window_current=None,
    force: bool = False,
) -> dict:
    settings = _settings_for_profile(profile)
    delivery_configured = _telegram_delivery_configured(settings)
    if profile.mode in {"digest", "interview"} and not dry_run and not delivery_configured:
        return {
            "delivery_configured": False,
            "message": "Telegram delivery is not configured for this digest profile.",
            "message_length": 0,
        }

    if profile.mode == "interview":
        message = run_fde_interview_guideline(
            settings,
            dry_run=dry_run,
            current=current,
        )
    elif profile.mode == "jobs":
        message = run_fde_job_alerts(
            settings,
            dry_run=dry_run,
            sources_path=profile.sources_path,
            current=current,
            send_window_current=send_window_current,
            force=force,
        )
    elif profile.mode == "source-intelligence":
        message = run_fde_job_source_intelligence(
            settings,
            dry_run=dry_run,
            discovery_sources_path=profile.sources_path,
        )
    else:
        message = run_digest(
            settings,
            profile.slot,
            dry_run=dry_run,
            sources_path=profile.sources_path,
            current=current,
        )
    return {
        "delivery_configured": delivery_configured,
        "message_length": len(message),
    }


def _settings_for_profile(profile: DigestProfile):
    settings = load_settings(env_prefix=profile.env_prefix)
    if profile.telegram_chat_id_env:
        bot_token = _secret_from_env(profile.telegram_bot_token_env) if profile.telegram_bot_token_env else ""
        chat_id = os.environ.get(profile.telegram_chat_id_env, "") or _stored_profile_chat_id(settings, profile.slot)
        settings = replace(
            settings,
            telegram_chat_id=chat_id,
            telegram_bot_token=bot_token or settings.telegram_bot_token or _secret_from_env("TELEGRAM_BOT_TOKEN"),
        )
    return settings


def _secret_from_env(key: str) -> str:
    if not key:
        return ""
    raw = os.environ.get(key)
    if raw:
        return raw
    encoded = os.environ.get(f"{key}_B64")
    if not encoded:
        return ""
    try:
        return b64decode(encoded, validate=True).decode("utf-8")
    except Exception:
        return ""


def _stored_profile_chat_id(settings, slot: str) -> str:
    try:
        conn = connect_database(settings)
        init_db(conn)
        try:
            return get_profile_setting(conn, slot, "telegram_chat_id")
        finally:
            conn.close()
    except Exception:
        app.logger.exception("Failed to load stored profile chat id")
        return ""


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
