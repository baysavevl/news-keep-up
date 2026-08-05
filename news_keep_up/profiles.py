from __future__ import annotations

import os
from base64 import b64decode
from dataclasses import dataclass, replace

from .config import load_settings
from .db import connect_database, get_profile_setting, init_db
from .digest import run_digest
from .interview import run_fde_interview_guideline
from .job_alerts import run_fde_job_alerts
from .source_intelligence import run_fde_job_source_intelligence


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


def telegram_delivery_configured(settings) -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def run_digest_profile(
    profile: DigestProfile,
    dry_run: bool,
    current=None,
    send_window_current=None,
    force: bool = False,
) -> dict:
    settings = settings_for_profile(profile)
    delivery_configured = telegram_delivery_configured(settings)
    if profile.mode in {"digest", "interview"} and not dry_run and not delivery_configured:
        return {
            "delivery_configured": False,
            "message": "Telegram delivery is not configured for this digest profile.",
            "message_length": 0,
        }

    if profile.mode == "interview":
        message = run_fde_interview_guideline(settings, dry_run=dry_run)
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
        )
    return {
        "delivery_configured": delivery_configured,
        "message_length": len(message),
    }


def settings_for_profile(profile: DigestProfile):
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
        return ""
