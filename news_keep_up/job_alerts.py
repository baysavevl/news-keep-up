from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from .config import load_sources
from .db import (
    connect_database,
    get_job_opportunity_source_fingerprint,
    init_db,
    list_pending_job_alerts,
    mark_job_alert_delivered,
    upsert_item,
    upsert_job_opportunity,
    upsert_source,
)
from .gemini import GeminiClient
from .job_filters import (
    NON_TECHNICAL_ROLE_TERMS,
    is_workable_from_vietnam_candidate,
    is_workable_from_vietnam_opportunity,
)
from .models import CandidateItem, JobOpportunity, Settings, Source
from .sources import fetch_source
from .telegram import send_telegram_message
from .utils import ICT, now_ict

DEFAULT_FDE_JOB_SOURCES_PATH = Path("config/fde_job_sources.json")
USER_AGENT = "news-keep-up/0.1 (+https://github.com/baysavevl/news-keep-up)"

JOB_TITLE_TERMS = (
    "forward deployed",
    "forward-deployed",
    "forward deployment",
    "fde",
    "deployment strategist",
    "deployed engineer",
    "ai deployment",
    "ai field engineer",
    "customer engineer",
    "customer-facing ai",
    "applied ai engineer",
    "ai solutions engineer",
    "genai solutions",
    "solution architect",
    "solutions architect",
    "solution engineer",
    "solutions engineer",
    "implementation engineer",
    "integration engineer",
    "agent ops",
    "ai agent engineer",
    "llm engineer",
    "rag engineer",
    "delivery solutions architect",
)

JOB_DOMAIN_TERMS = (
    "ai agents",
    "agentic ai",
    "enterprise ai",
    "genai",
    "llm",
    "rag",
    "langchain",
    "langgraph",
    "llamaindex",
    "openai",
    "anthropic",
    "gemini",
    "bedrock",
    "vertex ai",
    "databricks",
    "llmops",
    "ai implementation",
    "ai deployment",
    "production ai",
    "customer deployment",
    "enterprise integration",
    "workflow automation",
    "professional services",
    "field engineering",
)

JOB_LOCATION_TERMS = (
    "ho chi minh",
    "hcmc",
    "saigon",
    "hanoi",
    "vietnam",
    "viet nam",
    "vietnamese",
    "remote",
    "apac",
    "apj",
    "asia",
    "southeast asia",
    "south east asia",
    "asean",
    "singapore",
    "malaysia",
    "thailand",
    "indonesia",
    "philippines",
    "hong kong",
    "taiwan",
    "japan",
    "korea",
    "australia",
    "india",
)

def run_fde_job_alerts(
    settings: Settings,
    dry_run: bool = False,
    sources_path=DEFAULT_FDE_JOB_SOURCES_PATH,
    current: datetime | None = None,
) -> str:
    conn = connect_database(settings)
    init_db(conn)
    try:
        sources = load_sources(sources_path)
        for source in sources:
            upsert_source(conn, source)

        candidates = _new_job_candidates(conn, settings, sources)
        if candidates:
            crawled_at = _crawled_at(current)
            opportunities = GeminiClient(settings).classify_job_candidates(candidates, crawled_at)
            for opportunity in opportunities:
                upsert_job_opportunity(conn, opportunity)

        alert_limit = max(1, settings.max_llm_items_per_run)
        alerts = [
            opportunity
            for opportunity in list_pending_job_alerts(conn, limit=alert_limit * 8)
            if is_workable_from_vietnam_opportunity(opportunity)
        ][:alert_limit]
        messages = [format_job_alert(opportunity, current=current) for opportunity in alerts]
        delivery_configured = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        if not dry_run:
            if delivery_configured:
                for opportunity, message in zip(alerts, messages):
                    send_telegram_message(message, settings)
                    mark_job_alert_delivered(conn, opportunity.id, opportunity.alert_fingerprint)
                return "\n\n".join(messages)
            return ""
        return "\n\n".join(messages)
    finally:
        conn.close()


def format_job_alert(opportunity: JobOpportunity, current: datetime | None = None) -> str:
    timestamp = current or now_ict()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ICT)
    else:
        timestamp = timestamp.astimezone(ICT)
    verify = ", ".join(opportunity.what_to_verify[:3]) or "Vietnam eligibility"
    action = _action_label(opportunity)
    source = opportunity.apply_url or opportunity.source_url
    location_parts = [
        opportunity.company,
        opportunity.location or "Verify location",
    ]
    if opportunity.remote_policy:
        location_parts.append(opportunity.remote_policy)
    elif opportunity.vietnam_eligibility:
        location_parts.append(f"VN: {opportunity.vietnam_eligibility}")
    location_line = " · ".join(part for part in location_parts if part)
    lines = [
        "<b>🧭 FDE Job Alert</b>",
        f"Time: {escape(timestamp.strftime('%d %b %H:%M'))} ICT",
        "",
        f"<b>{escape(opportunity.role_title)}</b>",
        escape(location_line),
        f"Priority: <b>{escape(opportunity.priority)}</b> · Status: {escape(opportunity.status)} · Confidence: {opportunity.confidence_score}/100",
        f"Category: {escape(opportunity.category)} · Source: {escape(opportunity.source_type)}",
        f"Vietnam eligibility: {escape(opportunity.vietnam_eligibility)}",
        f"Phân tích: {escape(opportunity.why_it_fits)}",
        f"Verify: {escape(verify)}",
        f"Action: {escape(action)}",
        f'Link: <a href="{escape(source, quote=True)}">{escape(source)}</a>',
    ]
    if opportunity.outreach_angle:
        lines.insert(-1, f"Outreach: {escape(opportunity.outreach_angle)}")
    return "\n".join(lines).strip()


def _new_job_candidates(
    conn,
    settings: Settings,
    sources: list[Source],
) -> list[tuple[int, CandidateItem]]:
    queued: list[tuple[int, CandidateItem]] = []
    seen_candidate_urls: set[str] = set()
    per_source_limit = max(1, settings.max_candidates_per_source)
    for source, candidates in _fetch_candidates(sources, settings):
        source_queued: list[tuple[int, CandidateItem]] = []
        for candidate in candidates:
            if not _candidate_matches_source_filters(source, candidate):
                continue
            if not is_fde_job_candidate(candidate):
                continue
            if not is_workable_from_vietnam_candidate(candidate):
                continue
            dedupe_key = candidate.canonical_url or candidate.url
            if dedupe_key in seen_candidate_urls:
                continue
            seen_candidate_urls.add(dedupe_key)
            item_id, _ = upsert_item(conn, candidate)
            previous_fingerprint = get_job_opportunity_source_fingerprint(conn, item_id)
            if previous_fingerprint == candidate.fingerprint:
                continue
            source_queued.append((item_id, candidate))
        queued.extend(sorted(source_queued, key=lambda pair: _job_candidate_score(pair[1]), reverse=True)[:per_source_limit])
    return sorted(queued, key=lambda pair: _job_candidate_score(pair[1]), reverse=True)[:max(1, settings.max_llm_items_per_run)]


def is_fde_job_candidate(candidate: CandidateItem) -> bool:
    text = " ".join([
        candidate.title,
        candidate.summary,
        candidate.content,
        candidate.author,
        candidate.url,
    ]).lower()
    if any(term in text for term in NON_TECHNICAL_ROLE_TERMS):
        return False
    title_hit = any(term in text for term in JOB_TITLE_TERMS)
    domain_hit = any(term in text for term in JOB_DOMAIN_TERMS)
    location_hit = any(term in text for term in JOB_LOCATION_TERMS)
    hidden_hiring_hit = any(term in text for term in ("hiring", "we are hiring", "dm me", "apply", "career", "job"))
    if _looks_like_search_noise(text):
        return False
    return title_hit and (domain_hit or location_hit or hidden_hiring_hit)


def _candidate_matches_source_filters(source: Source, candidate: CandidateItem) -> bool:
    metadata = source.metadata or {}
    url = candidate.url.lower()
    title = candidate.title.lower()
    text = " ".join([candidate.title, candidate.summary, candidate.content]).lower()
    host = urlparse(candidate.url).netloc.lower()

    include_hosts = _metadata_terms(metadata, "url_host_include_any")
    if include_hosts and not any(term in host for term in include_hosts):
        return False

    include_urls = _metadata_terms(metadata, "url_include_any")
    if include_urls and not any(term in url for term in include_urls):
        return False

    exclude_urls = _metadata_terms(metadata, "url_exclude_any")
    if exclude_urls and any(term in url for term in exclude_urls):
        return False

    include_titles = _metadata_terms(metadata, "title_include_any")
    if include_titles and not any(term in title for term in include_titles):
        return False

    exclude_titles = _metadata_terms(metadata, "title_exclude_any")
    if exclude_titles and any(term in title for term in exclude_titles):
        return False

    include_text = _metadata_terms(metadata, "text_include_any")
    if include_text and not any(term in text for term in include_text):
        return False

    exclude_text = _metadata_terms(metadata, "text_exclude_any")
    if exclude_text and any(term in text for term in exclude_text):
        return False

    return True


def _metadata_terms(metadata: dict, key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, list):
        return [str(item).lower() for item in value if str(item).strip()]
    return []


def _job_candidate_score(candidate: CandidateItem) -> int:
    text = " ".join([candidate.title, candidate.summary, candidate.content, candidate.url]).lower()
    score = 0
    if any(term in text for term in ("forward deployed", "forward-deployed", "forward deployment", "deployment strategist", "deployed engineer")):
        score += 100
    if "fde" in text:
        score += 60
    if any(term in text for term in ("vietnam", "viet nam", "ho chi minh", "hcmc", "hanoi", "vietnamese", "remote vietnam")):
        score += 60
    if any(term in text for term in ("apac", "southeast asia", "asean", "singapore", "malaysia", "philippines", "india", "remote")):
        score += 30
    if any(term in text for term in JOB_DOMAIN_TERMS):
        score += 30
    if any(term in text for term in ("ashbyhq.com", "greenhouse.io", "lever.co", "workdayjobs.com", "careers", "jobs")):
        score += 15
    if _looks_like_search_noise(text):
        score -= 100
    return score


def _looks_like_search_noise(text: str) -> bool:
    noise_terms = (
        "dictionary",
        "cambridge",
        "wikipedia",
        "news that matters",
        "search dictionary",
        "translation",
        "stock price",
    )
    return any(term in text for term in noise_terms)


def _fetch_candidates(sources: list[Source], settings: Settings) -> Iterable[tuple[Source, list[CandidateItem]]]:
    timeout_seconds = max(1, settings.source_fetch_timeout_seconds)
    max_workers = max(1, min(settings.max_source_workers, len(sources) or 1))
    if max_workers == 1:
        for source in sources:
            yield source, _fetch_source_candidates(source, timeout_seconds)
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_source_candidates, source, timeout_seconds): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                candidates = future.result()
            except Exception:
                candidates = []
            yield source, candidates


def _fetch_source_candidates(source: Source, timeout_seconds: int) -> list[CandidateItem]:
    try:
        return fetch_source(source, USER_AGENT, timeout_seconds)
    except Exception:
        return []


def _crawled_at(current: datetime | None) -> str:
    timestamp = current or now_ict()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ICT)
    else:
        timestamp = timestamp.astimezone(ICT)
    return timestamp.date().isoformat()


def _action_label(opportunity: JobOpportunity) -> str:
    labels = {
        "apply_now": "Apply now",
        "dm_recruiter_first": "DM recruiter first",
        "follow_company": "Follow company",
        "set_alert": "Track and verify",
        "ignore": "Ignore",
    }
    return labels.get(opportunity.recommended_action, "Track and verify")
