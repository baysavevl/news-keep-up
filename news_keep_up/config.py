from __future__ import annotations

import json
import os
from base64 import b64decode
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .models import Settings, Source

DEFAULT_SOURCES_PATH = Path("config/sources.json")


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _secret_env(env: Mapping[str, str], key: str) -> str:
    raw = env.get(key)
    if raw:
        return raw

    encoded = env.get(f"{key}_B64")
    if not encoded:
        return ""
    try:
        return b64decode(encoded, validate=True).decode("utf-8")
    except Exception:
        return ""


def _profile_key(key: str, env_prefix: str) -> str:
    prefix = env_prefix.strip().upper()
    if not prefix:
        return key
    return f"{prefix}_{key}"


def _profile_secret_env(env: Mapping[str, str], key: str, env_prefix: str) -> str:
    if env_prefix.strip():
        return _secret_env(env, _profile_key(key, env_prefix))
    return _secret_env(env, key)


def _profile_plain_env(env: Mapping[str, str], key: str, env_prefix: str) -> str:
    if env_prefix.strip():
        return env.get(_profile_key(key, env_prefix), "")
    return env.get(key, "")


def load_settings(env: Mapping[str, str] | None = None, env_prefix: str = "") -> Settings:
    values = os.environ if env is None else env
    return Settings(
        gemini_api_key=_secret_env(values, "GEMINI_API_KEY"),
        telegram_bot_token=_profile_secret_env(values, "TELEGRAM_BOT_TOKEN", env_prefix),
        telegram_chat_id=_profile_plain_env(values, "TELEGRAM_CHAT_ID", env_prefix),
        turso_database_url=values.get("TURSO_DATABASE_URL", ""),
        turso_auth_token=values.get("TURSO_AUTH_TOKEN", ""),
        db_path=Path(values.get("DB_PATH", "data/news-keep-up.db")),
        gemini_model=values.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        gemini_fallback_model=values.get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash"),
        max_llm_items_per_run=_int_env(values, "MAX_LLM_ITEMS_PER_RUN", 20),
        max_llm_calls_per_day=_int_env(values, "MAX_LLM_CALLS_PER_DAY", 40),
        max_candidates_per_source=_int_env(values, "MAX_CANDIDATES_PER_SOURCE", 10),
        min_relevance_score=_int_env(values, "MIN_RELEVANCE_SCORE", 65),
        backfill_lookback_days=_int_env(values, "BACKFILL_LOOKBACK_DAYS", 7),
        source_fetch_timeout_seconds=_int_env(values, "SOURCE_FETCH_TIMEOUT_SECONDS", 5),
        max_source_workers=_int_env(values, "MAX_SOURCE_WORKERS", 12),
    )


def load_sources(path: Path | str = DEFAULT_SOURCES_PATH) -> list[Source]:
    source_path = Path(path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    sources: list[Source] = []
    for row in data:
        if not row.get("enabled", True):
            continue
        metadata = {k: v for k, v in row.items() if k not in {"name", "type", "url", "category", "enabled"}}
        sources.append(_source_from_dict(row, metadata))
    return sources


def _source_from_dict(row: dict[str, Any], metadata: dict[str, Any]) -> Source:
    return Source(
        name=str(row["name"]),
        kind=str(row.get("type", row.get("kind", "rss"))),
        url=str(row["url"]),
        category=str(row.get("category", "general")),
        enabled=bool(row.get("enabled", True)),
        metadata=metadata,
    )
