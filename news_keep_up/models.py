from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    turso_database_url: str = ""
    turso_auth_token: str = ""
    db_path: Path = Path("data/news-keep-up.db")
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_fallback_model: str = "gemini-2.5-flash"
    max_llm_items_per_run: int = 20
    max_llm_calls_per_day: int = 40
    max_candidates_per_source: int = 10
    min_relevance_score: int = 65
    backfill_lookback_days: int = 10
    source_fetch_timeout_seconds: int = 5
    max_source_workers: int = 12


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    url: str
    category: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateItem:
    source_name: str
    source_kind: str
    source_category: str
    title: str
    url: str
    canonical_url: str
    summary: str = ""
    content: str = ""
    author: str = ""
    published_at: str = ""
    fetched_at: str = ""
    fingerprint: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Enrichment:
    model: str
    relevance_score: int
    category: str
    topic: str
    icon: str
    title_vi: str
    summary: str
    why_it_matters: str
    takeaway_vi: str
    should_send: bool


@dataclass(frozen=True)
class DigestCandidate:
    item_id: int
    title: str
    url: str
    source_name: str
    source_category: str
    published_at: str
    fetched_at: str
    enrichment: Enrichment
    author: str = ""
    is_backfill: bool = False


@dataclass(frozen=True)
class DigestSelection:
    candidate: DigestCandidate
    position: int
