from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .config import load_sources
from .db import (
    connect_database,
    init_db,
    record_source_evaluation,
    record_source_fetch_logs,
    row_value,
    upsert_source,
    upsert_source_candidate,
)
from .job_search_policy import domain_terms, load_job_search_policy, role_terms
from .models import CandidateItem, Settings, Source, SourceCandidate, SourceEvaluation, SourceFetchLog
from .source_health import failed_source_fetch_log, successful_source_fetch_log
from .sources import fetch_source
from .utils import ICT, canonicalize_url, fingerprint_text, now_ict

DEFAULT_FDE_JOB_SOURCE_DISCOVERY_PATH = Path("config/fde_job_source_discovery_sources.json")
DEFAULT_FDE_JOB_ACTIVE_SOURCES_PATH = Path("config/fde_job_sources.json")
USER_AGENT = "news-keep-up/0.1 (+https://github.com/baysavevl/news-keep-up)"

SOURCE_URL_SIGNALS = (
    "jobs.ashbyhq.com",
    "greenhouse.io",
    "lever.co",
    "workable.com",
    "teamtailor.com",
    "recruitee.com",
    "smartrecruiters.com",
    "myworkdayjobs.com",
    "rippling-ats.com",
    "bamboohr.com",
    "careers",
    "jobs",
)

def run_fde_job_source_intelligence(
    settings: Settings,
    dry_run: bool = False,
    discovery_sources_path=DEFAULT_FDE_JOB_SOURCE_DISCOVERY_PATH,
    active_sources_path=DEFAULT_FDE_JOB_ACTIVE_SOURCES_PATH,
    current: datetime | None = None,
) -> str:
    conn = connect_database(settings)
    init_db(conn)
    try:
        active_sources = load_sources(active_sources_path)
        discovery_sources = load_sources(discovery_sources_path)
        for source in [*active_sources, *discovery_sources]:
            upsert_source(conn, source)

        evaluation_date = _date_key(current)
        evaluations = [_evaluate_source(conn, source, evaluation_date) for source in active_sources]
        for evaluation in evaluations:
            record_source_evaluation(conn, evaluation)

        source_candidates: list[SourceCandidate] = []
        active_urls = {canonicalize_url(source.url) for source in active_sources}
        for source, candidates in _fetch_candidates(discovery_sources, settings, conn):
            for candidate in candidates:
                if not is_source_candidate(candidate):
                    continue
                if canonicalize_url(candidate.url) in active_urls:
                    continue
                source_candidate = _source_candidate_from_item(candidate, source)
                inserted, _ = upsert_source_candidate(conn, source_candidate)
                if inserted:
                    source_candidates.append(source_candidate)

        message = format_source_intelligence_summary(evaluations, source_candidates)
        # Source maintenance is intentionally quiet; job alerts own Telegram notifications.
        return message
    finally:
        conn.close()


def is_source_candidate(candidate: CandidateItem) -> bool:
    text = " ".join([
        candidate.title,
        candidate.summary,
        candidate.url,
        candidate.source_name,
        candidate.source_category,
    ]).lower()
    url_hit = any(signal in text for signal in SOURCE_URL_SIGNALS)
    role_hit = any(signal in text for signal in role_terms())
    domain_hit = any(signal in text for signal in domain_terms())
    region_hit = any(
        signal in text for signal in ("apac", "asia", "vietnam", "remote")
    )
    return url_hit and role_hit and (domain_hit or region_hit)


def format_source_intelligence_summary(
    evaluations: list[SourceEvaluation],
    candidates: list[SourceCandidate],
) -> str:
    keep = sum(1 for evaluation in evaluations if evaluation.verdict == "keep")
    watch = sum(1 for evaluation in evaluations if evaluation.verdict == "watch")
    prune = sum(1 for evaluation in evaluations if evaluation.verdict == "prune")
    return "\n".join([
        "FDE Job Source Intelligence",
        f"evaluated sources: {len(evaluations)}",
        f"verdicts: keep={keep}, watch={watch}, prune={prune}",
        f"new source candidates: {len(candidates)}",
    ])


def _evaluate_source(conn, source: Source, evaluation_date: str) -> SourceEvaluation:
    cutoff = (now_ict() - timedelta(days=7)).isoformat()
    fetched_row = conn.execute(
        "SELECT COUNT(*) AS count FROM items WHERE source_name=? AND fetched_at >= ?",
        (source.name, cutoff),
    ).fetchone()
    opportunities_row = conn.execute(
        """SELECT COUNT(*) AS count
           FROM job_opportunities jo
           JOIN items i ON i.id = jo.source_item_id
           WHERE i.source_name=? AND jo.updated_at >= datetime('now', '-7 days')""",
        (source.name,),
    ).fetchone()
    alerts_row = conn.execute(
        """SELECT COUNT(*) AS count
           FROM job_alert_deliveries jad
           JOIN job_opportunities jo ON jo.id = jad.opportunity_id
           JOIN items i ON i.id = jo.source_item_id
           WHERE i.source_name=? AND jad.delivered_at >= datetime('now', '-7 days')""",
        (source.name,),
    ).fetchone()
    fetched = int(row_value(fetched_row, "count", 0) if fetched_row else 0)
    opportunities = int(row_value(opportunities_row, "count", 0) if opportunities_row else 0)
    alerts = int(row_value(alerts_row, "count", 0) if alerts_row else 0)
    score = min(100, alerts * 45 + opportunities * 12 + min(fetched, 20) * 2)
    if alerts > 0 or opportunities >= 3:
        verdict = "keep"
    elif fetched == 0:
        verdict = "prune"
    else:
        verdict = "watch"
    reason = (
        f"{fetched} fetched items, {opportunities} opportunities, {alerts} alerts in the last 7 days."
    )
    return SourceEvaluation(
        source_name=source.name,
        source_url=source.url,
        evaluation_date=evaluation_date,
        fetched_items_7d=fetched,
        opportunities_7d=opportunities,
        alerts_7d=alerts,
        score=score,
        verdict=verdict,
        reason=reason,
    )


def _source_candidate_from_item(item: CandidateItem, source: Source) -> SourceCandidate:
    source_type = str(item.raw.get("source_type") or source.metadata.get("source_type") or _guess_source_type(item.url))
    name = _source_candidate_name(item)
    category = "ats-index-search" if source_type == "ATS" else "job-source-candidate"
    score = _source_candidate_score(item, source_type)
    return SourceCandidate(
        id=_source_candidate_id(name, item.url),
        name=name,
        kind=item.source_kind or source.kind,
        url=item.url,
        category=category,
        source_type=source_type,
        status="candidate",
        score=score,
        discovered_from=source.name,
        reason=_source_candidate_reason(item, source_type),
    )


def _source_candidate_score(item: CandidateItem, source_type: str) -> int:
    text = f"{item.title} {item.summary} {item.url}".lower()
    score = 40
    if source_type == "ATS":
        score += 25
    if "forward deployed" in text or "fde" in text:
        score += 20
    if "vietnam" in text or "apac" in text or "southeast asia" in text:
        score += 10
    return min(100, score)


def _source_candidate_reason(item: CandidateItem, source_type: str) -> str:
    text = f"{item.title} {item.summary}".lower()
    policy = load_job_search_policy()
    label = next(
        (
            family.label
            for family in policy.role_families
            if any(alias in text for alias in family.title_aliases)
        ),
        "approved technical job scope",
    )
    if source_type == "ATS":
        return f"Indexed ATS/career source with {label} regional keywords."
    return f"Potential job or hiring-signal source with {label} regional keywords."


def _source_candidate_name(item: CandidateItem) -> str:
    title = item.title.strip() or item.url
    return title[:80]


def _source_candidate_id(name: str, url: str) -> str:
    url_hash = fingerprint_text(canonicalize_url(url))[:12]
    return _slug(f"{name}-{url_hash}")


def _guess_source_type(url: str) -> str:
    lowered = url.lower()
    if any(host in lowered for host in ("ashbyhq.com", "greenhouse.io", "lever.co", "workable.com", "teamtailor.com")):
        return "ATS"
    if "linkedin.com" in lowered:
        return "LinkedIn_post"
    if "jobs" in lowered or "careers" in lowered:
        return "job_board"
    return "aggregator"


def _fetch_candidates(sources: list[Source], settings: Settings, conn) -> Iterable[tuple[Source, list[CandidateItem]]]:
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
                except Exception as exc:
                    candidates = []
                    log = failed_source_fetch_log("fde-job-sources", source, exc)
                results.append((source, candidates, log))

    record_source_fetch_logs(conn, [log for _, _, log in results])
    for source, candidates, _ in results:
        yield source, candidates


def _fetch_source_candidates(source: Source, timeout_seconds: int) -> tuple[list[CandidateItem], SourceFetchLog]:
    try:
        candidates = fetch_source(source, USER_AGENT, timeout_seconds)
        return candidates, successful_source_fetch_log("fde-job-sources", source, len(candidates))
    except Exception as exc:
        return [], failed_source_fetch_log("fde-job-sources", source, exc)


def _date_key(current: datetime | None) -> str:
    timestamp = current or now_ict()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ICT)
    else:
        timestamp = timestamp.astimezone(ICT)
    return timestamp.date().isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", slug)[:120] or "source-candidate"
