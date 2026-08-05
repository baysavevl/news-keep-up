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


@dataclass(frozen=True)
class JobOpportunity:
    id: str
    source_item_id: int
    source_fingerprint: str
    crawled_at: str
    priority: str
    company: str
    role_title: str
    category: str
    location: str
    remote_policy: str
    vietnam_eligibility: str
    evidence_type: str
    status: str
    posted_date: str
    source_type: str
    source_url: str
    apply_url: str
    contact_person: str
    contact_url: str
    why_it_fits: str
    what_to_verify: list[str] = field(default_factory=list)
    required_seniority: str = ""
    required_skills: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)
    country: str = ""
    compensation: str = ""
    benefits: str = ""
    package: str = ""
    company_size: str = ""
    company_coverage: str = ""
    company_expansion_signal: str = ""
    linkedin_post_signal: str = ""
    recommended_action: str = "set_alert"
    outreach_angle: str = ""
    confidence_score: int = 0
    should_alert: bool = False

    @property
    def alert_fingerprint(self) -> str:
        parts = [
            f"priority={self.priority}",
            f"status={self.status}",
            f"eligibility={self.vietnam_eligibility}",
            f"location={self.location}",
            f"role={self.role_title}",
            f"apply={self.apply_url or self.source_url}",
        ]
        return "|".join(_compact_fingerprint_part(part) for part in parts)


def _compact_fingerprint_part(value: str) -> str:
    return " ".join(str(value).split()).strip()


@dataclass(frozen=True)
class SourceCandidate:
    id: str
    name: str
    kind: str
    url: str
    category: str
    source_type: str
    status: str
    score: int
    discovered_from: str
    reason: str

    @property
    def fingerprint(self) -> str:
        return "|".join(_compact_fingerprint_part(part) for part in (
            self.name,
            self.kind,
            self.url,
            self.category,
            self.source_type,
            self.status,
            str(self.score),
            self.reason,
        ))


@dataclass(frozen=True)
class SourceEvaluation:
    source_name: str
    source_url: str
    evaluation_date: str
    fetched_items_7d: int
    opportunities_7d: int
    alerts_7d: int
    score: int
    verdict: str
    reason: str


@dataclass(frozen=True)
class SourceFetchLog:
    slot: str
    source_name: str
    source_url: str
    source_kind: str
    status: str
    item_count: int
    error_type: str = ""
    error_message: str = ""
    fetched_at: str = ""


@dataclass(frozen=True)
class SourceFetchHealth:
    source_name: str
    source_url: str
    source_kind: str
    total_runs: int
    ok_runs: int
    failed_runs: int
    empty_runs: int
    total_items: int
    last_status: str
    last_error: str
    last_fetched_at: str
