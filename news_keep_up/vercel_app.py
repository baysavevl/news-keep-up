from __future__ import annotations

import os
from dataclasses import dataclass

from flask import Flask, Response, jsonify, request

from .config import load_settings
from .digest import run_digest
from .telegram_commands import handle_telegram_update


@dataclass(frozen=True)
class DigestProfile:
    slot: str
    sources_path: str
    env_prefix: str = ""


DIGEST_PROFILES = {
    "news": DigestProfile("news", "config/sources.json"),
    "morning": DigestProfile("morning", "config/sources.json"),
    "afternoon": DigestProfile("afternoon", "config/sources.json"),
    "engineer": DigestProfile("engineer", "config/sources.json", "ENGINEER"),
    "fde": DigestProfile("fde", "config/fde_sources.json", "FDE"),
}

app = Flask(__name__)

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
    settings = load_settings(env_prefix=profile.env_prefix)
    if not dry_run and not _telegram_delivery_configured(settings):
        return jsonify({
            "ok": True,
            "slot": slot,
            "dry_run": False,
            "delivery_configured": False,
            "message": "Telegram delivery is not configured for this digest profile.",
        })

    try:
        message = run_digest(
            settings,
            profile.slot,
            dry_run=dry_run,
            sources_path=profile.sources_path,
        )
    except Exception as exc:
        app.logger.exception("Digest run failed")
        return jsonify({"ok": False, "slot": slot, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "slot": slot,
        "dry_run": dry_run,
        "delivery_configured": True,
        "message_length": len(message),
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
