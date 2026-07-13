from __future__ import annotations

import os

from flask import Flask, jsonify, request

from .config import load_settings
from .digest import run_digest

VALID_SLOTS = {"morning", "afternoon"}

app = Flask(__name__)


@app.get("/")
def health_check():
    return jsonify({"ok": True, "service": "news-keep-up"})


@app.get("/api/digest/<slot>")
def digest_endpoint(slot: str):
    if slot not in VALID_SLOTS:
        return jsonify({"ok": False, "error": "invalid digest slot"}), 400

    auth_error = _cron_auth_error()
    if auth_error is not None:
        return auth_error

    dry_run = request.args.get("dry_run", "").lower() in {"1", "true", "yes"}
    try:
        message = run_digest(load_settings(), slot, dry_run=dry_run)
    except Exception as exc:
        app.logger.exception("Digest run failed")
        return jsonify({"ok": False, "slot": slot, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "slot": slot,
        "dry_run": dry_run,
        "message_length": len(message),
    })


def _cron_auth_error():
    cron_secret = os.environ.get("CRON_SECRET", "")
    if not cron_secret:
        return jsonify({"ok": False, "error": "CRON_SECRET is not configured"}), 500

    if request.headers.get("Authorization", "") != f"Bearer {cron_secret}":
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    return None
