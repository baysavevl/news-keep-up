from __future__ import annotations

import re
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

DIGEST_THREAD_TITLES = {
    "engineer": "🤖 AI/SWE News Thread",
    "fde": "🧭 FDE News Thread",
    "news": "🗞️ AI/FDE/SWE News Thread",
    "morning": "🌅 Morning News Thread",
    "afternoon": "🌤️ Afternoon News Thread",
}

DIGEST_THREAD_SCOPES = {
    "engineer": "Practical AI, SWE workflow, engineering practice",
    "fde": "Customer rollout, field delivery, enterprise implementation",
    "news": "AI, SWE, FDE, solution architecture",
    "morning": "AI, SWE, FDE, solution architecture",
    "afternoon": "AI, SWE, FDE, solution architecture",
}

DIGEST_THREAD_SCHEDULES = {
    "engineer": "every 3 hours at :40",
    "fde": "every 2 hours at :20",
    "news": "manual or compatibility slot",
    "morning": "manual or compatibility slot",
    "afternoon": "manual or compatibility slot",
}

DIGEST_SELECTION_POLICIES = {
    "engineer": (2, 3, 1),
    "fde": (3, 5, 1),
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
    "AWS APN Blog": 93,
    "AWS Startups Blog": 91,
    "About Amazon AWS News": 92,
    "a16z Substack": 88,
    "Chip Huyen": 88,
    "Lilian Weng": 89,
    "The Gradient": 86,
    "Understanding AI": 84,
    "The AI Economy": 84,
    "Enterprise Context Management": 83,
    "AI Realized Now": 82,
    "AI Supremacy": 82,
    "Last Week in AI": 82,
    "Zapier Engineering": 82,
    "Grab Engineering": 84,
    "Pinterest Engineering Medium": 83,
    "PayPal Tech Medium": 82,
    "Walmart Global Tech Medium": 82,
    "Dagster Blog": 82,
    "Product Impact Pod": 80,
    "Forward Feed": 79,
    "Operational AI": 79,
    "Enterprise AI Weekly": 78,
    "Ben Sykes Enterprise AI": 78,
    "Hands On AI Agent Mastery": 78,
    "Rany ElHousieny Medium": 76,
    "Ajay Kumar Medium": 76,
}

CONTENT_QUALITY_TERMS = {
    "acceptance criteria",
    "architecture",
    "automation",
    "case study",
    "code review",
    "delivery",
    "eval",
    "evals",
    "guardrail",
    "guardrails",
    "implementation",
    "integration",
    "metrics",
    "observability",
    "pattern",
    "patterns",
    "playbook",
    "practice",
    "practices",
    "production",
    "product workflow",
    "reliability",
    "rollout",
    "testing",
    "workflow",
    "workflows",
}

GENERIC_CONTENT_TERMS = {
    "announcement",
    "api features",
    "benchmark",
    "benchmarks",
    "cloud regions",
    "model availability",
    "public beta",
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


def format_digest_announcement(
    slot: str,
    selections: list[DigestSelection],
    now: datetime | None = None,
) -> str:
    current = now or now_ict()
    if current.tzinfo is None:
        current = current.replace(tzinfo=ICT)
    else:
        current = current.astimezone(ICT)
    fresh_count = sum(1 for selection in selections if not selection.candidate.is_backfill)
    backfill_count = sum(1 for selection in selections if selection.candidate.is_backfill)
    return "\n".join([
        f"<b>{escape(DIGEST_THREAD_TITLES.get(slot, '🗞️ News Thread'))}</b>",
        f"Time: {escape(current.strftime('%d %b %H:%M'))} ICT",
        f"Schedule: {escape(DIGEST_THREAD_SCHEDULES.get(slot, 'manual'))}",
        f"Scope: {escape(DIGEST_THREAD_SCOPES.get(slot, 'high-signal engineering news'))}",
        f"Selected: {len(selections)} items · {fresh_count} fresh · {backfill_count} backfill",
    ])


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
        (
            f"{escape(slot_label)} · {current.strftime('%d %b %H:%M')} ICT · "
            f"{fresh_count} fresh · {backfill_count} backfill{part_label}"
        ),
        "",
    ]

    if not selections:
        lines.extend([
            "✅ Scheduler OK.",
            "No qualifying items found for this slot.",
            "Cron heartbeat: notification delivery is working, but the news filter did not find a high-signal item.",
        ])
        return "\n".join(lines).strip()

    for selection in selections:
        item = selection.candidate
        enrichment = item.enrichment
        title = f"{_display_icon(item, enrichment)} {item.title}".strip()
        lines.extend([
            f"<b>{selection.position}. {escape(title)}</b>",
            _source_author_line(item),
            f"Topic: {escape(enrichment.category)} / {escape(enrichment.topic)}",
        ])
        if slot == "fde":
            lines.append(f"FDE topic: {escape(_fde_topic_label(item, enrichment))}")
        if item.is_backfill:
            lines.append("Backfill - still relevant")
        key_idea = _key_idea(item, enrichment)
        min_highlights, max_highlights = _highlight_bounds(slot)
        highlights = _highlights(
            item,
            enrichment,
            "" if slot == "fde" else key_idea,
            min_count=min_highlights,
            max_count=max_highlights,
        )
        lines.extend([
            (
                f"Fit: Impact: {escape(_impact_label(item, enrichment))} · "
                f"Trust: {escape(_trust_label(item))} · Importance: {enrichment.relevance_score}/100"
            ),
            f"Why read: {escape(_why_read(item, enrichment, key_idea, slot))}",
            "Scan:",
            *[f"• {escape(highlight)}" for highlight in _label_highlights(highlights, slot)],
            f"Takeaway: {escape(_trim_text(enrichment.takeaway_vi, 180))}",
            f'Read: <a href="{escape(item.url, quote=True)}">Read</a>',
            "",
        ])
    return "\n".join(lines).strip()


def _selection_chunks(selections: list[DigestSelection], size: int) -> list[list[DigestSelection]]:
    return [selections[index:index + size] for index in range(0, len(selections), size)]


def _source_author_line(item: DigestCandidate) -> str:
    author = item.author.strip() or "Unknown"
    return f"Source: {escape(item.source_name)} · Author: {escape(author)}"


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


FDE_TOPIC_SIGNALS = [
    (
        "Engineering",
        (
            "api",
            "architecture",
            "auth",
            "coding",
            "data",
            "idempot",
            "integration",
            "latency",
            "rag",
            "retry",
            "schema",
            "system design",
            "tenant",
            "tool",
            "typed error",
            "voice",
        ),
    ),
    (
        "Consulting",
        (
            "blocker",
            "consult",
            "customer context",
            "discovery",
            "requirement",
            "stakeholder",
            "workflow mapping",
        ),
    ),
    (
        "Product",
        (
            "adoption",
            "feedback",
            "product",
            "roadmap",
            "reusable",
            "user",
            "value",
        ),
    ),
    (
        "Delivery/Ops",
        (
            "acceptance",
            "debug",
            "deployment",
            "eval",
            "handoff",
            "incident",
            "kpi",
            "launch",
            "metric",
            "observability",
            "production",
            "rollback",
            "rollout",
            "sre",
        ),
    ),
    (
        "Security/Governance",
        (
            "audit",
            "compliance",
            "governance",
            "guardrail",
            "permission",
            "pii",
            "policy",
            "redact",
            "security",
        ),
    ),
    (
        "Customer/Business",
        (
            "business",
            "customer",
            "roi",
            "success metric",
            "value metric",
        ),
    ),
]


def _fde_topic_label(item: DigestCandidate, enrichment: Enrichment) -> str:
    text = " ".join([
        item.title,
        item.source_category,
        enrichment.category,
        enrichment.topic,
        enrichment.summary,
        enrichment.why_it_matters,
        enrichment.takeaway_vi,
    ]).lower()
    scored: list[tuple[int, int, str]] = []
    for index, (label, signals) in enumerate(FDE_TOPIC_SIGNALS):
        hits = sum(1 for signal in signals if signal in text)
        if hits:
            scored.append((-hits, index, label))
    if not scored:
        return "Engineering"
    return " · ".join(label for _, _, label in sorted(scored)[:2])


def _key_idea(item: DigestCandidate, enrichment: Enrichment) -> str:
    title = item.title
    for part in _summary_parts(enrichment.summary):
        if not _too_similar(part, title):
            return part[:240]
    for part in _summary_parts(enrichment.why_it_matters):
        if not _too_similar(part, title):
            return part[:240]
    return _fallback_key_idea(item)


def _highlight_bounds(slot: str) -> tuple[int, int]:
    if slot == "fde":
        return (5, 5)
    return (3, 5)


def _highlights(
    item: DigestCandidate,
    enrichment: Enrichment,
    key_idea: str,
    min_count: int = 3,
    max_count: int = 5,
) -> list[str]:
    candidates = [
        *_summary_parts(enrichment.summary),
        *_summary_parts(enrichment.why_it_matters),
    ]
    highlights: list[str] = []
    for part in candidates:
        cleaned = _clean_highlight(part)
        if not cleaned:
            continue
        if _too_similar(cleaned, item.title) or _too_similar(cleaned, key_idea):
            continue
        if any(_too_similar(cleaned, existing) for existing in highlights):
            continue
        highlights.append(_trim_text(cleaned, 170))
        if len(highlights) >= max_count:
            break

    for fallback in _fallback_highlights(item, enrichment):
        if len(highlights) >= min_count:
            break
        if not any(_too_similar(fallback, existing) for existing in highlights):
            highlights.append(fallback)
    return highlights[:max_count]


def _why_read(item: DigestCandidate, enrichment: Enrichment, key_idea: str, slot: str) -> str:
    if slot == "fde":
        candidates = [
            _clean_leading_label(enrichment.why_it_matters),
            key_idea,
            _fallback_key_idea(item),
        ]
    else:
        candidates = [
            key_idea,
            _clean_leading_label(enrichment.why_it_matters),
            _fallback_key_idea(item),
        ]
    for candidate in candidates:
        cleaned = _trim_text(candidate, 220)
        if cleaned and not _too_similar(cleaned, item.title):
            return cleaned
    if slot == "fde":
        return "Only useful if it changes customer rollout, integration, governance, or production handoff decisions."
    return "Useful only if it changes how the team builds, reviews, ships, or operates software."


def _clean_leading_label(text: str) -> str:
    cleaned = text.strip(" -•")
    lowered = cleaned.lower()
    for prefix in ("impact:", "why it matters:", "summary:", "key idea:"):
        if lowered.startswith(prefix):
            return cleaned[len(prefix):].strip(" -")
    return cleaned


def _label_highlights(highlights: list[str], slot: str) -> list[str]:
    labels = (
        ["Rollout", "Evidence", "Risk", "Action", "Fit"]
        if slot == "fde"
        else ["Change", "Evidence", "Risk", "Action", "Fit"]
    )
    labeled: list[str] = []
    for index, highlight in enumerate(highlights):
        cleaned = _trim_text(_clean_leading_label(highlight), 170)
        if cleaned:
            labeled.append(f"{labels[index % len(labels)]}: {cleaned}")
    return labeled


def _trim_text(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not shortened:
        shortened = normalized[:max_chars].rstrip(" ,;:-")
    return f"{shortened}..."


def _summary_parts(summary: str) -> list[str]:
    normalized = " ".join(summary.split())
    normalized = normalized.replace(" • ", ". ").replace(" - ", ". ")
    parts = [part.strip(" -•") for part in normalized.replace("; ", ". ").split(". ") if part.strip(" -•")]
    return [part for part in parts if not _is_feed_fragment(part) and len(part) >= 24][:6]


def _clean_highlight(part: str) -> str:
    cleaned = part.strip(" -•")
    lowered = cleaned.lower()
    for prefix in ("key idea:", "highlight:", "impact:", "why it matters:", "summary:"):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" -")
            lowered = cleaned.lower()
    if not cleaned or len(cleaned) < 24:
        return ""
    return cleaned


def _fallback_key_idea(item: DigestCandidate) -> str:
    if item.source_category.startswith("discussion"):
        return "Tín hiệu từ cộng đồng về một vấn đề đang được kỹ sư thảo luận, cần kiểm chứng trước khi áp dụng."
    if item.source_category.startswith("fde") or item.source_category in {"field-engineering", "enterprise-ai"}:
        return "Tín hiệu liên quan đến triển khai AI trong môi trường khách hàng, cần đọc dưới góc rollout và rủi ro vận hành."
    return "Tín hiệu về AI engineering có thể ảnh hưởng đến cách đội kỹ thuật thiết kế, tự động hóa hoặc vận hành workflow."


def _fallback_highlights(item: DigestCandidate, enrichment: Enrichment) -> list[str]:
    if item.source_category.startswith("fde") or item.source_category in {"field-engineering", "enterprise-ai"}:
        return [
            "Đọc để xác định bài học cho discovery, rollout, stakeholder alignment hoặc handoff với khách hàng.",
            "Kiểm tra xem nội dung có gợi ý guardrail, eval, observability hay tiêu chí production readiness nào không.",
            "Chuyển ý đáng tin thành một câu hỏi phỏng vấn hoặc một checklist triển khai ngắn cho FDE.",
            "Tách phần có thể áp dụng ngay cho customer workflow khỏi phần chỉ là nhận định chiến lược.",
            "Ghi lại owner, metric và rủi ro vận hành cần hỏi lại trước khi biến insight thành kế hoạch rollout.",
        ]
    if item.source_category.startswith("discussion"):
        return [
            "Ưu tiên xem các bình luận có kinh nghiệm thực chiến, số liệu, failure mode hoặc phản biện đáng tin.",
            "Dùng như early signal, không xem là kết luận cho tới khi có nguồn chính thống hoặc case study đi kèm.",
            "Nếu liên quan đến workflow nội bộ, thử biến insight thành một experiment nhỏ thay vì áp dụng rộng ngay.",
            "So sánh các quan điểm trái chiều để tìm constraint thật thay vì chỉ lấy ý kiến được upvote cao.",
            "Chỉ chuyển thành action khi có bối cảnh triển khai, dữ liệu hoặc trade-off rõ ràng.",
        ]
    topic = enrichment.topic.lower()
    if "agent" in topic or "automation" in topic or "orchestration" in topic:
        return [
            "Đọc theo câu hỏi: agent này giảm bước thủ công nào, cần người kiểm soát ở điểm nào, và đo hiệu quả ra sao.",
            "Tìm dấu hiệu về eval, rollback, permission, observability hoặc cost trước khi đưa vào workflow thật.",
            "Nếu phù hợp, biến insight thành một playbook nhỏ cho coding agent hoặc automation trong team.",
            "Xác định rõ boundary giữa đề xuất của model, tool action và bước cần con người approve.",
            "Ưu tiên pattern có log, trace và cơ chế phục hồi khi tool call hoặc dữ liệu đầu vào lỗi.",
        ]
    return [
        "Đọc để tìm thay đổi cụ thể trong tooling, process hoặc architecture thay vì chỉ lấy thông tin announcement.",
        "Đánh giá bằng impact lên developer productivity, reliability, cost hoặc tốc độ delivery.",
        "Chỉ áp dụng nếu có bước thử nghiệm nhỏ và metric kiểm chứng rõ ràng.",
        "Tìm constraint về vận hành, bảo mật hoặc tích hợp trước khi đưa vào backlog.",
        "Biến insight thành một câu hỏi review kiến trúc nếu chưa đủ chắc để triển khai.",
    ]


def _too_similar(left: str, right: str) -> bool:
    left_tokens = _content_tokens(left)
    right_tokens = _content_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap / max(1, min(len(left_tokens), len(right_tokens))) >= 0.72


def _content_tokens(text: str) -> set[str]:
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "into", "your", "you",
        "are", "was", "were", "how", "what", "why", "about", "more", "than", "then",
        "one", "every", "model", "models", "ai",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stopwords
    }


def _is_feed_fragment(part: str) -> bool:
    lowered = part.lower()
    if lowered.startswith(("hi hacker news", "hello hacker news", "hey hacker news", "hi hn", "hello hn", "hey hn")):
        return True
    if lowered.startswith(("here's a demo", "here is a demo", "here's the demo", "here is the demo")):
        return True
    if "here are the docs" in lowered or "here's the docs" in lowered or "here is the docs" in lowered:
        return True
    if lowered.startswith("the post ") and " appeared first" in lowered:
        return True
    if lowered.startswith("it lets") and (len(part) < 30 or part.endswith("..") or part.endswith("...")):
        return True
    if "continue reading on medium" in lowered:
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
    sources = load_sources(sources_path)
    current_item_ids = _fetch_store_and_enrich(conn, settings, slot, sources)
    min_items, max_items, discussion_limit = _selection_policy(slot)
    rows = _load_digest_candidates_for_slot(
        conn,
        settings,
        slot,
        current_item_ids,
        allowed_source_names={source.name for source in sources},
        min_items=min_items,
    )
    rows = _review_digest_candidates(conn, settings, slot, rows, max_items)
    selections = select_digest_items(rows, min_items=min_items, max_items=max_items, discussion_limit=discussion_limit)
    content_messages = format_digest_messages(slot, selections)
    messages = (
        [format_digest_announcement(slot, selections), *content_messages]
        if selections
        else content_messages
    )
    message = "\n\n".join(messages)
    if not dry_run:
        if not selections:
            for chunk_message in messages:
                send_telegram_message(chunk_message, settings)
            return message
        send_telegram_message(messages[0], settings)
        for chunk, chunk_message in zip(_selection_chunks(selections, DIGEST_ITEMS_PER_MESSAGE), content_messages):
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
        reviewed_row = replace(row, enrichment=enrichment)
        if not _digest_candidate_matches_slot(reviewed_row, slot):
            continue
        reviewed_rows.append(reviewed_row)

    if reviewed_rows:
        model = next(iter(reviewed.values())).model
        record_llm_usage(conn, model, today, slot, None, "review")
    return sorted(reviewed_rows, key=_candidate_sort_key)


def _digest_candidate_matches_slot(row: DigestCandidate, slot: str) -> bool:
    review_text = " ".join([
        row.enrichment.summary,
        row.enrichment.why_it_matters,
    ])
    candidate = CandidateItem(
        source_name=row.source_name,
        source_kind="stored",
        source_category=row.source_category,
        title=row.title,
        url=row.url,
        canonical_url=row.url,
        summary=review_text,
        author=row.author,
        published_at=row.published_at,
        fetched_at=row.fetched_at,
    )
    return is_candidate_relevant_for_slot(candidate, slot)


def _fetch_store_and_enrich(conn, settings: Settings, slot: str, sources: list[Source]) -> set[int]:
    current_item_ids: set[int] = set()
    llm_calls_this_run = 0
    today = now_ict().date().isoformat()
    client = GeminiClient(settings)

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


def _load_digest_candidates(
    conn,
    settings: Settings,
    current_item_ids: set[int],
    *,
    slot: str | None = None,
    allowed_source_names: set[str] | None = None,
) -> list[DigestCandidate]:
    fetched_cutoff = (now_ict() - timedelta(days=settings.backfill_lookback_days)).isoformat()
    published_cutoff = (now_ict() - timedelta(days=settings.backfill_lookback_days)).astimezone(timezone.utc).isoformat()
    if allowed_source_names is not None and not allowed_source_names:
        return []

    conditions = [
        "e.should_send = 1",
        "e.relevance_score >= ?",
        "(i.fetched_at IS NULL OR i.fetched_at = '' OR i.fetched_at >= ?)",
        "(i.published_at IS NULL OR i.published_at = '' OR i.published_at >= ?)",
    ]
    params: list[object] = [settings.min_relevance_score, fetched_cutoff, published_cutoff]
    conditions.append("NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.item_id = i.id)")
    if allowed_source_names is not None:
        ordered_source_names = sorted(allowed_source_names)
        placeholders = ", ".join("?" for _ in ordered_source_names)
        conditions.append(f"i.source_name IN ({placeholders})")
        params.extend(ordered_source_names)

    rows = conn.execute(
        f"""SELECT i.id, i.title, i.url, i.source_name, i.source_category, i.author, i.published_at, i.fetched_at,
                  i.source_kind, i.canonical_url, i.summary AS item_summary, i.content AS item_content,
                  e.model, e.relevance_score, e.category, e.topic, e.icon, e.title_vi,
                  e.summary, e.why_it_matters, e.takeaway_vi, e.should_send
           FROM items i
           JOIN enrichments e ON e.item_id = i.id
           WHERE {" AND ".join(conditions)}
           ORDER BY e.relevance_score DESC, i.published_at DESC""",
        tuple(params),
    ).fetchall()
    candidates: list[DigestCandidate] = []
    for row in rows:
        enrichment = Enrichment(
            model=row_value(row, "model", 12),
            relevance_score=int(row_value(row, "relevance_score", 13)),
            category=row_value(row, "category", 14),
            topic=row_value(row, "topic", 15),
            icon=row_value(row, "icon", 16),
            title_vi=row_value(row, "title_vi", 17),
            summary=row_value(row, "summary", 18),
            why_it_matters=row_value(row, "why_it_matters", 19),
            takeaway_vi=row_value(row, "takeaway_vi", 20),
            should_send=bool(row_value(row, "should_send", 21)),
        )
        item_id = int(row_value(row, "id", 0))
        candidate_item = CandidateItem(
            source_name=row_value(row, "source_name", 3),
            source_kind=row_value(row, "source_kind", 8) or "",
            source_category=row_value(row, "source_category", 4),
            title=row_value(row, "title", 1),
            url=row_value(row, "url", 2),
            canonical_url=row_value(row, "canonical_url", 9) or row_value(row, "url", 2),
            summary=row_value(row, "item_summary", 10) or "",
            content=row_value(row, "item_content", 11) or "",
            author=row_value(row, "author", 5) or "",
            published_at=row_value(row, "published_at", 6) or "",
            fetched_at=row_value(row, "fetched_at", 7) or "",
        )
        if slot is not None and not is_candidate_relevant_for_slot(candidate_item, slot):
            continue
        candidates.append(DigestCandidate(
            item_id=item_id,
            title=candidate_item.title,
            url=candidate_item.url,
            source_name=candidate_item.source_name,
            source_category=candidate_item.source_category,
            published_at=candidate_item.published_at,
            fetched_at=candidate_item.fetched_at,
            author=candidate_item.author,
            enrichment=enrichment,
            is_backfill=item_id not in current_item_ids,
        ))
    return candidates


def _load_digest_candidates_for_slot(
    conn,
    settings: Settings,
    slot: str,
    current_item_ids: set[int],
    *,
    allowed_source_names: set[str] | None = None,
    min_items: int = 1,
) -> list[DigestCandidate]:
    rows = _load_digest_candidates(
        conn,
        settings,
        current_item_ids,
        slot=slot,
        allowed_source_names=allowed_source_names,
    )
    if len(rows) >= min_items:
        return rows

    best_rows = rows
    for lookback_days in (14, 21):
        if settings.backfill_lookback_days >= lookback_days:
            continue
        expanded_settings = replace(settings, backfill_lookback_days=lookback_days)
        expanded_rows = _load_digest_candidates(
            conn,
            expanded_settings,
            current_item_ids,
            slot=slot,
            allowed_source_names=allowed_source_names,
        )
        if len(expanded_rows) > len(best_rows):
            best_rows = expanded_rows
        if len(best_rows) >= min_items:
            break
    return best_rows


def _candidate_sort_key(row: DigestCandidate) -> tuple[float, int, int, int, str]:
    final_score = _final_ranking_score(row)
    return (
        -final_score,
        -_candidate_recency_timestamp(row),
        -row.enrichment.relevance_score,
        -_source_trust_score(row),
        row.title,
    )


def _final_ranking_score(row: DigestCandidate) -> float:
    trust = _source_trust_score(row)
    impact = _impact_score(row, row.enrichment)
    quality = _content_quality_score(row)
    recency = _recency_score(row)
    backfill_penalty = 8 if row.is_backfill else 0
    return (
        row.enrichment.relevance_score * 0.30
        + trust * 0.25
        + impact * 0.25
        + quality * 0.15
        + recency * 0.05
        - backfill_penalty
    )


def _content_quality_score(row: DigestCandidate) -> int:
    text = " ".join([
        row.title,
        row.source_category,
        row.enrichment.category,
        row.enrichment.topic,
        row.enrichment.summary,
        row.enrichment.why_it_matters,
    ]).lower()
    quality_hits = sum(1 for term in CONTENT_QUALITY_TERMS if term in text)
    generic_hits = sum(1 for term in GENERIC_CONTENT_TERMS if term in text)
    score = 45 + quality_hits * 10 - generic_hits * 12
    if row.source_category.startswith("discussion"):
        score -= 10
    return max(0, min(100, score))


def _recency_score(row: DigestCandidate) -> int:
    timestamp = _candidate_recency_timestamp(row)
    if timestamp <= 0:
        return 0
    age_days = max(0, (now_ict().timestamp() - timestamp) / 86_400)
    return max(0, min(100, int(100 - age_days * 12)))


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
