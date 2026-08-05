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
    record_source_fetch_logs,
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
from .models import CandidateItem, JobOpportunity, Settings, Source, SourceFetchLog
from .scheduler import is_fde_job_alert_send_window
from .source_health import failed_source_fetch_log, successful_source_fetch_log
from .sources import fetch_source
from .telegram import send_telegram_message
from .utils import ICT, now_ict

DEFAULT_FDE_JOB_SOURCES_PATH = Path("config/fde_job_sources.json")
USER_AGENT = "news-keep-up/0.1 (+https://github.com/baysavevl/news-keep-up)"
JOB_ALERT_BATCH_LIMIT = 3

JOB_TITLE_TERMS = (
    "forward deployed",
    "forward-deployed",
    "forward deployment",
    "fde",
    "deployment strategist",
    "deployed engineer",
    "ai deployment",
    "ai field engineer",
    "ai engineer",
    "ai architect",
    "ai consultant",
    "customer engineer",
    "customer-facing ai",
    "applied ai engineer",
    "machine learning engineer",
    "ml engineer",
    "ai solutions engineer",
    "genai solutions",
    "technical solutions engineer",
    "solution architect",
    "solutions architect",
    "solution engineer",
    "solutions engineer",
    "enterprise solutions engineer",
    "sales engineer",
    "presales engineer",
    "pre-sales engineer",
    "presales",
    "pre-sales",
    "presales consultant",
    "solutions consultant",
    "solution consultant",
    "technical consultant",
    "technical account manager",
    "customer success engineer",
    "customer success architect",
    "professional services engineer",
    "professional services consultant",
    "deployment engineer",
    "field engineer",
    "value engineer",
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
    "generative ai",
    "machine learning",
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

FREELANCE_PROJECT_TERMS = (
    "agentic ai",
    "ai agent",
    "ai agents",
    "artificial intelligence agent",
    "generative ai",
    "genai",
    "llm",
    "rag",
    "openai",
    "anthropic",
    "gemini",
    "langchain",
    "langgraph",
    "llamaindex",
    "ai chatbot",
    "chatbot",
    "workflow automation",
    "ai automation",
    "ai integration",
    "machine learning",
)

FREELANCE_IMPLEMENTATION_TERMS = (
    "architect",
    "automation",
    "build",
    "chatbot",
    "contract",
    "develop",
    "engineer",
    "freelance",
    "implement",
    "integration",
    "platform",
    "project",
    "specialist",
    "workflow",
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
    send_window_current: datetime | None = None,
    force: bool = False,
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

        alert_limit = min(JOB_ALERT_BATCH_LIMIT, max(1, settings.max_llm_items_per_run))
        alert_candidates = [
            opportunity
            for opportunity in list_pending_job_alerts(conn, limit=alert_limit * 8)
            if is_workable_from_vietnam_opportunity(opportunity)
        ]
        alerts = _dedupe_opportunities_by_url(alert_candidates)[:alert_limit]
        messages = [format_job_alert(opportunity, current=current) for opportunity in alerts]
        delivery_configured = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        if not dry_run:
            if not force and not is_fde_job_alert_send_window(send_window_current or current):
                return ""
            if delivery_configured:
                for opportunity, message in zip(alerts, messages):
                    send_telegram_message(message, settings)
                    mark_job_alert_delivered(conn, opportunity.id, opportunity.alert_fingerprint)
                return "\n\n".join(messages)
            return ""
        return "\n\n".join(messages)
    finally:
        conn.close()


def probe_fde_job_sources(
    settings: Settings,
    sources_path=DEFAULT_FDE_JOB_SOURCES_PATH,
) -> dict:
    conn = connect_database(settings)
    init_db(conn)
    rows: list[dict] = []
    try:
        sources = load_sources(sources_path)
        for source, candidates in _fetch_candidates(sources, settings, conn):
            source_filtered = [
                candidate
                for candidate in candidates
                if _candidate_matches_source_filters(source, candidate)
            ]
            fde_candidates = [
                candidate
                for candidate in source_filtered
                if is_fde_job_candidate(candidate)
            ]
            workable_candidates = [
                candidate
                for candidate in fde_candidates
                if is_workable_from_vietnam_candidate(candidate)
            ]
            rows.append({
                "source": source.name,
                "fetched_items": len(candidates),
                "source_filtered_candidates": len(source_filtered),
                "fde_candidates": len(fde_candidates),
                "workable_candidates": len(workable_candidates),
            })
    finally:
        conn.close()

    return {
        "sources": len(rows),
        "fetched_items": sum(row["fetched_items"] for row in rows),
        "source_filtered_candidates": sum(row["source_filtered_candidates"] for row in rows),
        "fde_candidates": sum(row["fde_candidates"] for row in rows),
        "workable_candidates": sum(row["workable_candidates"] for row in rows),
        "rows": rows,
    }


def format_job_alert(opportunity: JobOpportunity, current: datetime | None = None) -> str:
    timestamp = current or now_ict()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ICT)
    else:
        timestamp = timestamp.astimezone(ICT)
    verify = ", ".join(opportunity.what_to_verify[:3]) or "Vietnam eligibility"
    action = _action_label(opportunity)
    source = opportunity.apply_url or opportunity.source_url
    priority_icon = _priority_icon(opportunity.priority)
    source_label = _pretty_label(opportunity.source_type)
    status_label = _pretty_label(opportunity.status)
    location = opportunity.location or "Verify location"
    remote_policy = opportunity.remote_policy or "Verify"
    compensation = _join_known([opportunity.compensation, opportunity.package]) or "Chưa thấy trong source"
    benefits = opportunity.benefits or "Chưa thấy trong source"
    footprint = _join_known([opportunity.company_size, opportunity.company_coverage]) or "Chưa thấy trong source"
    lines = [
        f"{priority_icon} <b>Tech Job Alert</b> · {escape(opportunity.priority)} · {opportunity.confidence_score}/100",
        f"Time: {escape(timestamp.strftime('%d %b %H:%M'))} ICT",
        "",
        f"<b>{escape(opportunity.role_title)}</b>",
        f"🏢 Công ty: {escape(opportunity.company)}",
        f"🏷 Hạng mục: {escape(opportunity.category)}",
        f"📍 Địa điểm: {escape(location)}",
        f"🌍 Quốc gia: {escape(opportunity.country or _country_from_location(location) or 'Verify')}",
        f"🌐 Remote: {escape(remote_policy)}",
        f"💰 Lương/package: {escape(compensation)}",
        f"🎁 Phúc lợi: {escape(benefits)}",
        f"🏬 Company footprint: {escape(footprint)}",
        f"🇻🇳 Khả năng từ VN: {escape(opportunity.vietnam_eligibility)} · {escape(opportunity.evidence_type)} signal",
        f"📌 Trạng thái: {escape(status_label)} · Nguồn: {escape(source_label)}",
        f"🔎 Phân tích: {escape(opportunity.why_it_fits)}",
        f"❓ Cần verify: {escape(verify)}",
        f"🎯 Hành động: {escape(action)}",
        f'🔗 Link: <a href="{escape(source, quote=True)}">{escape(source)}</a>',
    ]
    focus = _focus_line(opportunity)
    if focus:
        lines.insert(9, focus)
    if opportunity.outreach_angle:
        lines.insert(-1, f"✉️ Outreach: {escape(opportunity.outreach_angle)}")
    return "\n".join(lines).strip()


def _dedupe_opportunities_by_url(opportunities: list[JobOpportunity]) -> list[JobOpportunity]:
    deduped: list[JobOpportunity] = []
    seen: set[str] = set()
    for opportunity in opportunities:
        key = opportunity.apply_url or opportunity.source_url or opportunity.id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(opportunity)
    return deduped


def _new_job_candidates(
    conn,
    settings: Settings,
    sources: list[Source],
) -> list[tuple[int, CandidateItem]]:
    queued: list[tuple[int, CandidateItem]] = []
    seen_candidate_urls: set[str] = set()
    per_source_limit = max(1, settings.max_candidates_per_source)
    for source, candidates in _fetch_candidates(sources, settings, conn):
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
    if _is_freelance_project_candidate(candidate, text):
        return True
    return title_hit and (domain_hit or location_hit or hidden_hiring_hit)


def _is_freelance_project_candidate(candidate: CandidateItem, text: str) -> bool:
    source_text = " ".join([
        candidate.source_name,
        candidate.source_category,
        candidate.url,
    ]).lower()
    if not any(term in source_text for term in (
        "freelance",
        "upwork",
        "freelancer.com",
        "guru.com",
        "peopleperhour",
        "arc.dev",
        "usebraintrust",
    )):
        return False
    project_hit = any(term in text for term in FREELANCE_PROJECT_TERMS)
    implementation_hit = any(term in text for term in FREELANCE_IMPLEMENTATION_TERMS)
    return project_hit and implementation_hit


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
    # Solution Engineer is the second-priority focus after FDE.
    if any(term in text for term in ("solution engineer", "solutions engineer", "solution architect", "solutions architect")):
        score += 45
    # Broader FDE-adjacent roles (presales/SE/TAM/CS/professional services) rank below the core focus.
    if any(term in text for term in (
        "presales", "pre-sales", "sales engineer", "solutions consultant", "solution consultant",
        "technical account manager", "customer success engineer", "professional services",
        "implementation engineer", "integration engineer", "customer engineer", "field engineer",
    )):
        score += 25
    # Hybrid tech/product/business scope is a priority signal for these roles.
    if any(term in text for term in ("product", "business", "go-to-market", "gtm", "stakeholder", "customer-facing", "client-facing")):
        score += 15
    if any(term in text for term in ("vietnam", "viet nam", "ho chi minh", "hcmc", "hanoi", "vietnamese", "remote vietnam")):
        score += 60
    # WFH / fully remote is the most desirable arrangement.
    if any(term in text for term in ("work from home", "wfh", "fully remote", "remote-first", "remote first")):
        score += 25
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


def _fetch_candidates(
    sources: list[Source],
    settings: Settings,
    conn,
) -> Iterable[tuple[Source, list[CandidateItem]]]:
    timeout_seconds = max(1, settings.source_fetch_timeout_seconds)
    max_workers = max(1, min(settings.max_source_workers, len(sources) or 1))
    results: list[tuple[Source, list[CandidateItem], SourceFetchLog]] = []
    if max_workers == 1:
        for source in sources:
            candidates, log = _fetch_source_candidates(source, timeout_seconds)
            results.append((source, candidates, log))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_source_candidates, source, timeout_seconds): source
                for source in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    candidates, log = future.result()
                except Exception:
                    candidates = []
                    log = failed_source_fetch_log("fde-jobs", source, RuntimeError("source fetch worker failed"))
                results.append((source, candidates, log))

    record_source_fetch_logs(conn, [log for _, _, log in results])
    for source, candidates, _ in results:
        yield source, candidates


def _fetch_source_candidates(source: Source, timeout_seconds: int) -> tuple[list[CandidateItem], SourceFetchLog]:
    try:
        candidates = fetch_source(source, USER_AGENT, timeout_seconds)
        return candidates, successful_source_fetch_log("fde-jobs", source, len(candidates))
    except Exception as exc:
        return [], failed_source_fetch_log("fde-jobs", source, exc)


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


def _priority_icon(priority: str) -> str:
    return {
        "High": "🔴",
        "Medium": "🟡",
        "Low": "⚪",
    }.get(priority, "🟡")


def _pretty_label(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").split()) or "verify"


def _focus_line(opportunity: JobOpportunity) -> str:
    parts = [part for part in [*opportunity.domain[:2], *opportunity.required_skills[:2]] if part]
    if not parts:
        return ""
    return f"🧩 Trọng tâm: {escape(', '.join(parts[:4]))}"


def _join_known(parts: list[str]) -> str:
    return " · ".join(part for part in parts if part)


def _country_from_location(location: str) -> str:
    lowered = location.lower()
    country_terms = [
        ("Vietnam", ("vietnam", "viet nam", "ho chi minh", "hcmc", "hanoi", "saigon")),
        ("United States", ("united states", "usa", "u.s.")),
        ("Singapore", ("singapore",)),
        ("India", ("india", "bengaluru", "bangalore")),
        ("Malaysia", ("malaysia",)),
        ("Thailand", ("thailand",)),
        ("Indonesia", ("indonesia",)),
        ("Philippines", ("philippines",)),
        ("Hong Kong", ("hong kong",)),
        ("Taiwan", ("taiwan",)),
        ("Japan", ("japan",)),
        ("Korea", ("korea",)),
        ("Australia", ("australia",)),
    ]
    for country, terms in country_terms:
        if any(term in lowered for term in terms):
            return country
    return ""
