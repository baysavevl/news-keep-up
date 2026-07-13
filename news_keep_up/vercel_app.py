from __future__ import annotations

import os
from dataclasses import dataclass

from flask import Flask, jsonify, request

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


@app.get("/")
def health_check():
    return jsonify({"ok": True, "service": "news-keep-up"})


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
