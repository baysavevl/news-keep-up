from __future__ import annotations

from .models import CandidateItem

INCLUDE_WEIGHTS: list[tuple[str, int]] = [
    ("agentic engineering", 35),
    ("coding agent", 35),
    ("ai agent", 30),
    ("agents", 18),
    ("llm", 18),
    ("ai engineering", 25),
    ("software engineering", 18),
    ("solution architect", 20),
    ("forward deployed engineer", 25),
    ("customer engineering", 18),
    ("claude code", 25),
    ("openai codex", 25),
    ("codex", 18),
    ("gemini cli", 25),
    ("cursor", 16),
    ("mcp", 20),
    ("rag", 18),
    ("evals", 18),
    ("workflow automation", 16),
    ("developer tools", 14),
    ("system design", 14),
    ("ai tools", 16),
    ("ai", 10),
]

EXCLUDE_PHRASES = [
    "job opening",
    "we are hiring",
    "apply now",
    "coupon",
    "promo code",
    "sponsored post",
    "giveaway",
]


def prefilter_score(item: CandidateItem) -> int:
    text = " ".join([item.title, item.summary, item.content, item.source_category]).lower()
    if any(phrase in text for phrase in EXCLUDE_PHRASES):
        return 0

    score = 0
    for phrase, weight in INCLUDE_WEIGHTS:
        if phrase in text:
            score += weight

    if item.source_category in {"ai-engineering", "agentic-engineering", "developer-tools"}:
        score += 10
    if item.source_category == "discussion":
        score -= 5
    return max(0, min(100, score))


def is_candidate_relevant(item: CandidateItem) -> bool:
    threshold = 45 if item.source_category == "discussion" else 30
    return prefilter_score(item) >= threshold
