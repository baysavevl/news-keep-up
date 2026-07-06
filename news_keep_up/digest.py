from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from .config import DEFAULT_SOURCES_PATH, load_sources
from .db import (
    connect_database,
    count_llm_calls_today,
    get_enrichment,
    init_db,
    mark_delivered,
    record_llm_usage,
    upsert_enrichment,
    upsert_item,
    upsert_source,
)
from .gemini import GeminiClient, fallback_enrichment
from .models import CandidateItem, DigestCandidate, DigestSelection, Enrichment, Settings
from .prefilter import is_candidate_relevant
from .sources import fetch_source
from .telegram import send_telegram_message
from .utils import ICT, now_ict

USER_AGENT = "news-keep-up/0.1 (+https://github.com/baysavevl/news-keep-up)"


def select_digest_items(
    rows: list[DigestCandidate],
    min_items: int,
    max_items: int,
    discussion_limit: int,
) -> list[DigestSelection]:
    selected: list[DigestCandidate] = []
    selected_ids: set[int] = set()
    discussion_count = 0

    fresh = sorted((row for row in rows if not row.is_backfill), key=_candidate_sort_key)
    backfill = sorted((row for row in rows if row.is_backfill), key=_candidate_sort_key)

    def try_add(row: DigestCandidate) -> bool:
        nonlocal discussion_count
        if row.item_id in selected_ids or len(selected) >= max_items:
            return False
        if row.source_category == "discussion" and discussion_count >= discussion_limit:
            return False
        selected.append(row)
        selected_ids.add(row.item_id)
        if row.source_category == "discussion":
            discussion_count += 1
        return True

    for row in fresh:
        try_add(row)

    if len(selected) < min_items:
        for row in backfill:
            try_add(row)
            if len(selected) >= min_items:
                break

    return [DigestSelection(candidate=row, position=index + 1) for index, row in enumerate(selected)]


def format_digest(slot: str, selections: list[DigestSelection], now: datetime | None = None) -> str:
    current = now or now_ict()
    if current.tzinfo is None:
        current = current.replace(tzinfo=ICT)
    else:
        current = current.astimezone(ICT)
    slot_label = slot.replace("-", " ").title()
    fresh_count = sum(1 for selection in selections if not selection.candidate.is_backfill)
    backfill_count = sum(1 for selection in selections if selection.candidate.is_backfill)
    lines = [
        f"AI/FDE/SWE Digest | {slot_label} | {current.strftime('%d %b %Y %H:%M')} ICT",
        f"{fresh_count} fresh, {backfill_count} backfill",
        "",
    ]

    if not selections:
        lines.append("No qualifying items found.")
        return "\n".join(lines).strip()

    for selection in selections:
        item = selection.candidate
        enrichment = item.enrichment
        lines.extend([
            f"{selection.position}. {enrichment.icon} {item.title}",
            f"Title VN: {enrichment.title_vi}",
        ])
        if item.is_backfill:
            lines.append("Backfill - still relevant")
        lines.extend([
            f"Category: {enrichment.category} | Topic: {enrichment.topic} | Source: {item.source_name}",
            f"Summary: {enrichment.summary}",
            f"Why it matters: {enrichment.why_it_matters}",
            f"Takeaway VN: {enrichment.takeaway_vi}",
            f"Link: {item.url}",
            "",
        ])
    return "\n".join(lines).strip()


def run_digest(
    settings: Settings,
    slot: str,
    dry_run: bool = False,
    sources_path=DEFAULT_SOURCES_PATH,
) -> str:
    conn = connect_database(settings)
    init_db(conn)
    current_item_ids = _fetch_store_and_enrich(conn, settings, slot, sources_path)
    rows = _load_digest_candidates(conn, settings, current_item_ids)
    selections = select_digest_items(rows, min_items=3, max_items=5, discussion_limit=1)
    message = format_digest(slot, selections)
    if selections and not dry_run:
        send_telegram_message(message, settings)
        mark_delivered(
            conn,
            [selection.candidate.item_id for selection in selections],
            slot,
            {selection.candidate.item_id for selection in selections if selection.candidate.is_backfill},
        )
    return message


def _fetch_store_and_enrich(conn, settings: Settings, slot: str, sources_path) -> set[int]:
    current_item_ids: set[int] = set()
    llm_calls_this_run = 0
    today = now_ict().date().isoformat()
    client = GeminiClient(settings)

    for source in load_sources(sources_path):
        upsert_source(conn, source)
        try:
            candidates = fetch_source(source, USER_AGENT)[:settings.max_candidates_per_source]
        except Exception:
            continue
        for candidate in candidates:
            if not is_candidate_relevant(candidate):
                continue
            item_id, _ = upsert_item(conn, candidate)
            current_item_ids.add(item_id)
            if get_enrichment(conn, item_id) is not None:
                continue

            daily_calls = count_llm_calls_today(conn, today)
            if llm_calls_this_run >= settings.max_llm_items_per_run or daily_calls >= settings.max_llm_calls_per_day:
                enrichment = fallback_enrichment(candidate, "budget-limit")
                upsert_enrichment(conn, item_id, enrichment)
                continue

            enrichment = client.enrich(candidate)
            upsert_enrichment(conn, item_id, enrichment)
            if not enrichment.model.startswith("fallback:"):
                record_llm_usage(conn, enrichment.model, today, slot, item_id, "ok")
                llm_calls_this_run += 1
    return current_item_ids


def _load_digest_candidates(conn, settings: Settings, current_item_ids: set[int]) -> list[DigestCandidate]:
    cutoff = (now_ict() - timedelta(days=settings.backfill_lookback_days)).isoformat()
    rows = conn.execute(
        """SELECT i.id, i.title, i.url, i.source_name, i.source_category, i.published_at, i.fetched_at,
                  e.model, e.relevance_score, e.category, e.topic, e.icon, e.title_vi,
                  e.summary, e.why_it_matters, e.takeaway_vi, e.should_send
           FROM items i
           JOIN enrichments e ON e.item_id = i.id
           WHERE e.should_send = 1
             AND e.relevance_score >= ?
             AND (i.fetched_at IS NULL OR i.fetched_at = '' OR i.fetched_at >= ?)
             AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)
           ORDER BY e.relevance_score DESC, i.published_at DESC""",
        (settings.min_relevance_score, cutoff),
    ).fetchall()
    candidates: list[DigestCandidate] = []
    for row in rows:
        enrichment = Enrichment(
            model=row["model"],
            relevance_score=int(row["relevance_score"]),
            category=row["category"],
            topic=row["topic"],
            icon=row["icon"],
            title_vi=row["title_vi"],
            summary=row["summary"],
            why_it_matters=row["why_it_matters"],
            takeaway_vi=row["takeaway_vi"],
            should_send=bool(row["should_send"]),
        )
        candidates.append(DigestCandidate(
            item_id=int(row["id"]),
            title=row["title"],
            url=row["url"],
            source_name=row["source_name"],
            source_category=row["source_category"],
            published_at=row["published_at"] or "",
            fetched_at=row["fetched_at"] or "",
            enrichment=enrichment,
            is_backfill=int(row["id"]) not in current_item_ids,
        ))
    return candidates


def _candidate_sort_key(row: DigestCandidate) -> tuple[int, str]:
    return (-row.enrichment.relevance_score, row.published_at or row.fetched_at)
