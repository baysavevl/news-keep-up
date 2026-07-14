from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
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
    row_value,
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

DIGEST_ITEMS_PER_MESSAGE = 2

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
    "Google DeepMind Blog": 94,
    "Google Cloud AI ML Blog": 94,
    "Google Cloud Blog AI": 94,
    "Microsoft Azure Blog AI": 93,
    "Microsoft AI Blog": 93,
    "Azure AI Foundry Blog": 92,
    "AWS Machine Learning Blog": 93,
    "AWS Bedrock Blog": 92,
    "AWS Architecture Blog": 91,
    "NVIDIA AI Developer Blog": 91,
    "Salesforce Engineering": 91,
    "Palantir Blog": 91,
    "The Pragmatic Engineer": 90,
    "The Pragmatic Engineer FDE": 90,
    "First Round Review": 89,
    "Martin Fowler": 89,
    "Netflix TechBlog": 88,
    "Stripe Blog": 88,
    "Cloudflare Blog": 88,
    "Datadog Engineering": 87,
    "InfoQ AI ML Data Engineering": 86,
    "GitHub Blog": 86,
    "Vercel Blog": 85,
    "Hugging Face Blog": 85,
    "LangChain Blog": 84,
    "LlamaIndex Blog": 84,
    "Braintrust Blog": 84,
    "Arize AI Blog": 83,
    "Langfuse Blog": 83,
    "Temporal Blog": 83,
    "Lenny's Newsletter": 83,
    "Cohere Blog": 82,
    "Mistral AI News": 82,
    "Pinecone Blog": 82,
    "Weaviate Blog": 82,
    "Qdrant Blog": 82,
    "Twilio Blog": 82,
    "LiveKit Blog": 82,
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
    return "\n\n".join(format_digest_messages(slot, selections, now=now))


def format_digest_messages(
    slot: str,
    selections: list[DigestSelection],
    now: datetime | None = None,
    items_per_message: int = DIGEST_ITEMS_PER_MESSAGE,
) -> list[str]:
    current = now or now_ict()
    if current.tzinfo is None:
        current = current.replace(tzinfo=ICT)
    else:
        current = current.astimezone(ICT)
    chunks = _selection_chunks(selections, max(1, items_per_message))
    if not chunks:
        chunks = [[]]
    return [
        _format_digest_chunk(slot, chunk, selections, current, index + 1, len(chunks))
        for index, chunk in enumerate(chunks)
    ]


def _format_digest_chunk(
    slot: str,
    selections: list[DigestSelection],
    all_selections: list[DigestSelection],
    current: datetime,
    part_index: int,
    part_count: int,
) -> str:
    digest_title = DIGEST_TITLES.get(slot, "AI/FDE/SWE Digest")
    slot_label = DIGEST_SLOT_LABELS.get(slot, slot.replace("-", " ").title())
    fresh_count = sum(1 for selection in all_selections if not selection.candidate.is_backfill)
    backfill_count = sum(1 for selection in all_selections if selection.candidate.is_backfill)
    part_label = f" | Part {part_index}/{part_count}" if part_count > 1 else ""
    lines = [
        f"<b>{escape(digest_title)}</b>",
        f"{escape(slot_label)} | {current.strftime('%d %b %Y %H:%M')} ICT",
        f"{fresh_count} fresh, {backfill_count} backfill{part_label}",
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
            _source_author_line(item),
            f"🏷 Category: {escape(enrichment.category)} / {escape(enrichment.topic)}",
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
            "-----",
            f"🔥 Popularity: {escape(_popularity_label(item, enrichment))} | 🛡 Trust: {escape(_trust_label(item))}",
            f"⚖️ Importance: {enrichment.relevance_score}/100 | 🎯 Impact: {escape(_impact_label(item, enrichment))}",
            "",
        ])
    return "\n".join(lines).strip()


def _selection_chunks(selections: list[DigestSelection], size: int) -> list[list[DigestSelection]]:
    return [selections[index:index + size] for index in range(0, len(selections), size)]


def _source_author_line(item: DigestCandidate) -> str:
    author = item.author.strip() or "Unknown"
    return f"📰 Source: {escape(item.source_name)} | ✍️ Author: {escape(author)}"


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
    if item.source_name.startswith("Hacker News"):
        return 62
    if item.source_category.startswith("discussion"):
        return 62
    if item.source_category in {"fde-industry", "field-engineering"}:
        return 78
    if item.source_category in {"enterprise-ai", "ai-product", "developer-tools"}:
        return 82
    if item.source_category in {
        "ai-engineering",
        "agentic-engineering",
        "agent-frameworks",
        "agent-orchestration",
        "ai-automation",
        "ai-observability",
        "llm-ops",
    }:
        return 81
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
    rows = _review_digest_candidates(conn, settings, slot, rows, max_items)
    selections = select_digest_items(rows, min_items=min_items, max_items=max_items, discussion_limit=discussion_limit)
    messages = format_digest_messages(slot, selections)
    message = "\n\n".join(messages)
    if selections and not dry_run:
        for chunk, chunk_message in zip(_selection_chunks(selections, DIGEST_ITEMS_PER_MESSAGE), messages):
            send_telegram_message(chunk_message, settings)
            mark_delivered(
                conn,
                [selection.candidate.item_id for selection in chunk],
                slot,
                {selection.candidate.item_id for selection in chunk if selection.candidate.is_backfill},
            )
    return message


def _review_digest_candidates(
    conn,
    settings: Settings,
    slot: str,
    rows: list[DigestCandidate],
    max_items: int,
) -> list[DigestCandidate]:
    if not settings.gemini_api_key or not rows:
        return rows
    today = now_ict().date().isoformat()
    if count_llm_calls_today(conn, today) >= settings.max_llm_calls_per_day:
        return rows

    review_window = rows[:max(max_items * 3, max_items)]
    reviewed = GeminiClient(settings).review_digest_candidates(slot, review_window, max_items)
    if not reviewed:
        return rows

    reviewed_rows: list[DigestCandidate] = []
    for row in rows:
        enrichment = reviewed.get(row.item_id)
        if enrichment is None:
            reviewed_rows.append(row)
            continue
        if not enrichment.should_send:
            continue
        reviewed_rows.append(replace(row, enrichment=enrichment))

    if reviewed_rows:
        model = next(iter(reviewed.values())).model
        record_llm_usage(conn, model, today, slot, None, "review")
    return sorted(reviewed_rows, key=_candidate_sort_key)


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
        """SELECT i.id, i.title, i.url, i.source_name, i.source_category, i.author, i.published_at, i.fetched_at,
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
            model=row_value(row, "model", 8),
            relevance_score=int(row_value(row, "relevance_score", 9)),
            category=row_value(row, "category", 10),
            topic=row_value(row, "topic", 11),
            icon=row_value(row, "icon", 12),
            title_vi=row_value(row, "title_vi", 13),
            summary=row_value(row, "summary", 14),
            why_it_matters=row_value(row, "why_it_matters", 15),
            takeaway_vi=row_value(row, "takeaway_vi", 16),
            should_send=bool(row_value(row, "should_send", 17)),
        )
        item_id = int(row_value(row, "id", 0))
        candidates.append(DigestCandidate(
            item_id=item_id,
            title=row_value(row, "title", 1),
            url=row_value(row, "url", 2),
            source_name=row_value(row, "source_name", 3),
            source_category=row_value(row, "source_category", 4),
            published_at=row_value(row, "published_at", 6) or "",
            fetched_at=row_value(row, "fetched_at", 7) or "",
            author=row_value(row, "author", 5) or "",
            enrichment=enrichment,
            is_backfill=item_id not in current_item_ids,
        ))
    return candidates


def _candidate_sort_key(row: DigestCandidate) -> tuple[int, int, int, int, int, str]:
    impact = _impact_score(row, row.enrichment)
    impact_bucket = impact // 5
    return (
        -impact_bucket,
        -_candidate_recency_timestamp(row),
        -impact,
        -row.enrichment.relevance_score,
        -_source_trust_score(row),
        row.title,
    )


def _candidate_recency_timestamp(row: DigestCandidate) -> int:
    raw = row.published_at or row.fetched_at
    if not raw:
        return 0
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ICT)
    return int(parsed.timestamp())
