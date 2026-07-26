from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable

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

        alerts = list_pending_job_alerts(conn, limit=max(1, settings.max_llm_items_per_run))
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
    lines = [
        "<b>🧭 FDE Job Alert</b>",
        f"Time: {escape(timestamp.strftime('%d %b %H:%M'))} ICT",
        f"Priority: <b>{escape(opportunity.priority)}</b> · Confidence: {opportunity.confidence_score}/100",
        "",
        f"Company: {escape(opportunity.company)}",
        f"Role/Signal: {escape(opportunity.role_title)}",
        f"Category: {escape(opportunity.category)}",
        f"Location: {escape(opportunity.location or 'Verify')}",
        f"Vietnam eligibility: {escape(opportunity.vietnam_eligibility)}",
        f"Status: {escape(opportunity.status)} · Source: {escape(opportunity.source_type)}",
        f"Why this matters: {escape(opportunity.why_it_fits)}",
        f"Verify: {escape(verify)}",
        f"Action: {escape(action)}",
        f'Source: <a href="{escape(source, quote=True)}">{escape(source)}</a>',
    ]
    if opportunity.outreach_angle:
        lines.insert(-1, f"Outreach angle: {escape(opportunity.outreach_angle)}")
    return "\n".join(lines).strip()


def _new_job_candidates(
    conn,
    settings: Settings,
    sources: list[Source],
) -> list[tuple[int, CandidateItem]]:
    queued: list[tuple[int, CandidateItem]] = []
    for _, candidates in _fetch_candidates(sources, settings):
        for candidate in candidates:
            if not is_fde_job_candidate(candidate):
                continue
            item_id, _ = upsert_item(conn, candidate)
            previous_fingerprint = get_job_opportunity_source_fingerprint(conn, item_id)
            if previous_fingerprint == candidate.fingerprint:
                continue
            queued.append((item_id, candidate))
            if len(queued) >= max(1, settings.max_llm_items_per_run):
                return queued
    return queued


def is_fde_job_candidate(candidate: CandidateItem) -> bool:
    text = " ".join([
        candidate.title,
        candidate.summary,
        candidate.content,
        candidate.source_name,
        candidate.source_category,
    ]).lower()
    title_hit = any(term in text for term in JOB_TITLE_TERMS)
    domain_hit = any(term in text for term in JOB_DOMAIN_TERMS)
    location_hit = any(term in text for term in JOB_LOCATION_TERMS)
    hidden_hiring_hit = any(term in text for term in ("hiring", "we are hiring", "dm me", "apply", "career", "job"))
    return title_hit and (domain_hit or location_hit or hidden_hiring_hit)


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
