from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html import escape
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
from .models import CandidateItem, DigestCandidate, DigestSelection, Enrichment, Settings, Source
from .prefilter import is_candidate_relevant_for_slot
from .sources import fetch_source
from .telegram import send_telegram_message
from .utils import ICT, now_ict

USER_AGENT = "news-keep-up/0.1 (+https://github.com/baysavevl/news-keep-up)"

DIGEST_TITLES = {
    "engineer": "Engineer Digest",
    "fde": "FDE Digest",
}

DIGEST_SLOT_LABELS = {
    "fde": "FDE",
}

DIGEST_SELECTION_POLICIES = {
    "fde": (8, 8, 2),
}

TOPIC_ICONS = {
    "coding-agents": "🤖",
    "ai-tools": "🛠️",
    "rag": "📚",
    "mcp": "🔌",
    "evals": "📊",
    "fde": "🧭",
}

SOURCE_TRUST_OVERRIDES = {
    "Anthropic News": 96,
    "OpenAI News": 96,
    "Google AI Blog": 94,
    "Google Cloud Blog AI": 94,
    "Microsoft Azure Blog AI": 93,
    "AWS Machine Learning Blog": 93,
    "AWS Architecture Blog": 91,
    "Salesforce Engineering": 91,
    "Palantir Blog": 91,
    "The Pragmatic Engineer": 90,
    "Martin Fowler": 89,
    "Netflix TechBlog": 88,
    "Stripe Blog": 88,
    "Cloudflare Blog": 88,
    "Datadog Engineering": 87,
    "InfoQ AI ML Data Engineering": 86,
    "GitHub Blog": 86,
    "Vercel Blog": 85,
    "LangChain Blog": 84,
    "Lenny's Newsletter": 83,
}


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
        if _is_discussion_category(row.source_category) and discussion_count >= discussion_limit:
            return False
        selected.append(row)
        selected_ids.add(row.item_id)
        if _is_discussion_category(row.source_category):
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
    digest_title = DIGEST_TITLES.get(slot, "AI/FDE/SWE Digest")
    slot_label = DIGEST_SLOT_LABELS.get(slot, slot.replace("-", " ").title())
    fresh_count = sum(1 for selection in selections if not selection.candidate.is_backfill)
    backfill_count = sum(1 for selection in selections if selection.candidate.is_backfill)
    lines = [
        f"<b>{escape(digest_title)}</b>",
        f"{escape(slot_label)} | {current.strftime('%d %b %Y %H:%M')} ICT",
        f"{fresh_count} fresh, {backfill_count} backfill",
        "",
    ]

    if not selections:
        lines.append("No qualifying items found.")
        return "\n".join(lines).strip()

    for selection in selections:
        item = selection.candidate
        enrichment = item.enrichment
        title = f"{_display_icon(item, enrichment)} {item.title}".strip()
        lines.extend([
            f"<b>{selection.position}. {escape(title)}</b>",
            f"🏷 Category: {escape(enrichment.category)} / {escape(enrichment.topic)} | From: {escape(item.source_name)}",
            f"🔥 Popularity: {escape(_popularity_label(item, enrichment))} | 🛡 Trust: {escape(_trust_label(item))}",
            f"⚖️ Importance: {enrichment.relevance_score}/100 | 🎯 Impact: {escape(_impact_label(item, enrichment))}",
        ])
        translated_title = _display_title_vi(item.title, enrichment.title_vi)
        if translated_title:
            lines.append(f"VN title: {escape(translated_title)}")
        if item.is_backfill:
            lines.append("Backfill - still relevant")
        highlights = _highlights(enrichment.summary, enrichment.why_it_matters)
        lines.extend([
            f"💡 Ý chính: {escape(_key_idea(enrichment.summary))}",
            "✨ Highlights:",
            f"• {escape(highlights[0])}",
            f"• {escape(highlights[1])}",
            f"🇻🇳 VN: {escape(enrichment.takeaway_vi)}",
            f'🔗 Read: <a href="{escape(item.url, quote=True)}">Read</a>',
            "",
        ])
    return "\n".join(lines).strip()


def _display_title_vi(title: str, title_vi: str) -> str:
    marker = "(bản dịch tự động chưa có)"
    cleaned = title_vi.replace(marker, "").strip()
    if not cleaned or cleaned == title:
        return ""
    return cleaned


def _display_icon(item: DigestCandidate, enrichment: Enrichment) -> str:
    raw_icon = enrichment.icon.strip()
    if raw_icon and raw_icon.upper() not in {"AI", "FDE"}:
        return raw_icon
    topic = enrichment.topic.lower()
    if item.source_category.startswith("fde"):
        return TOPIC_ICONS["fde"]
    for key, icon in TOPIC_ICONS.items():
        if key in topic:
            return icon
    if "agent" in topic:
        return TOPIC_ICONS["coding-agents"]
    return "🧠"


def _popularity_label(item: DigestCandidate, enrichment: Enrichment) -> str:
    bonus = 0
    if item.source_category.startswith("discussion"):
        bonus += 8
    if item.source_category in {"fde-industry", "enterprise-ai", "field-engineering"}:
        bonus += 5
    score = max(0, min(100, enrichment.relevance_score + bonus))
    if score >= 85:
        label = "High"
    elif score >= 70:
        label = "Medium"
    else:
        label = "Niche"
    return f"{label} ({score}/100)"


def _trust_label(item: DigestCandidate) -> str:
    score = _source_trust_score(item)
    if score >= 85:
        label = "High"
    elif score >= 70:
        label = "Medium"
    else:
        label = "Emerging"
    return f"{label} ({score}/100)"


def _source_trust_score(item: DigestCandidate) -> int:
    if item.source_name in SOURCE_TRUST_OVERRIDES:
        return SOURCE_TRUST_OVERRIDES[item.source_name]
    if item.source_category.startswith("discussion"):
        return 62
    if item.source_category in {"fde-industry", "field-engineering"}:
        return 78
    if item.source_category in {"enterprise-ai", "ai-product", "developer-tools"}:
        return 82
    if item.source_category in {"software-engineering", "systems-engineering", "security-engineering"}:
        return 80
    return 72


def _impact_label(item: DigestCandidate, enrichment: Enrichment) -> str:
    score = _impact_score(item, enrichment)
    if score >= 85:
        label = "High"
    elif score >= 70:
        label = "Medium"
    else:
        label = "Niche"
    return f"{label} ({score}/100)"


def _impact_score(item: DigestCandidate, enrichment: Enrichment) -> int:
    topic = enrichment.topic.lower()
    category = enrichment.category.lower()
    score = enrichment.relevance_score
    if item.source_category in {"fde-industry", "enterprise-ai", "field-engineering"}:
        score += 6
    if any(token in topic or token in category for token in ("rollout", "deployment", "eval", "guardrail", "governance")):
        score += 8
    if item.source_category.startswith("discussion"):
        score -= 4
    return max(0, min(100, score))


def _key_idea(summary: str) -> str:
    sentences = _summary_parts(summary)
    return sentences[0] if sentences else summary


def _highlights(summary: str, why_it_matters: str) -> tuple[str, str]:
    sentences = _summary_parts(summary)
    first = sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else why_it_matters)
    second = why_it_matters
    return (first[:280], second[:280])


def _summary_parts(summary: str) -> list[str]:
    normalized = " ".join(summary.split())
    parts = [part.strip(" -•") for part in normalized.replace("; ", ". ").split(". ") if part.strip(" -•")]
    return [part for part in parts if not _is_feed_fragment(part)][:3]


def _is_feed_fragment(part: str) -> bool:
    lowered = part.lower()
    if lowered.startswith("the post ") and " appeared first" in lowered:
        return True
    if lowered.startswith("it lets") and (len(part) < 30 or part.endswith("..") or part.endswith("...")):
        return True
    return False


def _selection_policy(slot: str) -> tuple[int, int, int]:
    return DIGEST_SELECTION_POLICIES.get(slot, (3, 5, 1))


def _is_discussion_category(category: str) -> bool:
    return category == "discussion" or category.startswith("discussion-")


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
    min_items, max_items, discussion_limit = _selection_policy(slot)
    selections = select_digest_items(rows, min_items=min_items, max_items=max_items, discussion_limit=discussion_limit)
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

    sources = load_sources(sources_path)
    for source in sources:
        upsert_source(conn, source)

    for source, candidates in _fetch_candidates(sources, settings):
        for candidate in candidates:
            if not is_candidate_relevant_for_slot(candidate, slot):
                continue
            item_id, _ = upsert_item(conn, candidate)
            current_item_ids.add(item_id)
            cached_enrichment = get_enrichment(conn, item_id)
            if cached_enrichment is not None and not _should_refresh_enrichment(settings, cached_enrichment):
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


def _fetch_candidates(sources: list[Source], settings: Settings) -> Iterable[tuple[Source, list[CandidateItem]]]:
    timeout_seconds = max(1, settings.source_fetch_timeout_seconds)
    max_workers = max(1, min(settings.max_source_workers, len(sources) or 1))
    if max_workers == 1:
        for source in sources:
            try:
                candidates = fetch_source(source, USER_AGENT, timeout_seconds)[:settings.max_candidates_per_source]
            except Exception:
                candidates = []
            yield source, candidates
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_source, source, USER_AGENT, timeout_seconds): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                candidates = future.result()[:settings.max_candidates_per_source]
            except Exception:
                candidates = []
            yield source, candidates


def _should_refresh_enrichment(settings: Settings, enrichment: Enrichment) -> bool:
    return bool(settings.gemini_api_key and enrichment.model.startswith("fallback:"))


def _load_digest_candidates(conn, settings: Settings, current_item_ids: set[int]) -> list[DigestCandidate]:
    fetched_cutoff = (now_ict() - timedelta(days=settings.backfill_lookback_days)).isoformat()
    published_cutoff = (now_ict() - timedelta(days=settings.backfill_lookback_days)).astimezone(timezone.utc).isoformat()
    rows = conn.execute(
        """SELECT i.id, i.title, i.url, i.source_name, i.source_category, i.published_at, i.fetched_at,
                  e.model, e.relevance_score, e.category, e.topic, e.icon, e.title_vi,
                  e.summary, e.why_it_matters, e.takeaway_vi, e.should_send
           FROM items i
           JOIN enrichments e ON e.item_id = i.id
           WHERE e.should_send = 1
             AND e.relevance_score >= ?
             AND (i.fetched_at IS NULL OR i.fetched_at = '' OR i.fetched_at >= ?)
             AND (i.published_at IS NULL OR i.published_at = '' OR i.published_at >= ?)
             AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)
           ORDER BY e.relevance_score DESC, i.published_at DESC""",
        (settings.min_relevance_score, fetched_cutoff, published_cutoff),
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
