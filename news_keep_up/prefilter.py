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
    ("forward deployed", 25),
    ("field engineering", 24),
    ("field engineer", 22),
    ("ai deployment", 24),
    ("enterprise ai", 22),
    ("enterprise agent", 22),
    ("customer-facing", 20),
    ("customer embedded", 20),
    ("pilot to production", 22),
    ("production rollout", 20),
    ("workflow integration", 18),
    ("guardrails", 16),
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

FDE_STRONG_PHRASES = [
    "forward deployed",
    "fde",
    "field engineer",
    "field engineering",
    "ai deployment",
    "deployment engineer",
    "applied ai architect",
    "technical deployment",
    "customer-facing",
    "customer embedded",
    "customer-embedded",
    "customer delivery",
    "pilot to production",
    "production rollout",
    "workflow integration",
    "enterprise ai",
    "enterprise agent",
    "enterprise agents",
    "solution engineer",
    "sales engineer",
]

FDE_DELIVERY_PHRASES = [
    "client",
    "stakeholder",
    "implementation",
    "deploy",
    "deployment",
    "rollout",
    "evals",
    "guardrails",
    "rollout metrics",
    "workflow",
    "integration",
    "customer",
    "enterprise",
    "production",
]

FDE_AGENT_PHRASES = [
    "ai agent",
    "agentic",
    "agents",
    "agent ",
]

FDE_GOVERNANCE_PHRASES = [
    "eval",
    "evaluate",
    "evaluation",
    "guardrail",
    "policy",
    "policies",
    "govern",
    "governance",
    "identity",
    "permission",
    "authorization",
    "audit",
    "compliance",
    "reliable",
    "reliability",
    "resilience",
    "testing",
    "telemetry",
    "observability",
]

FDE_WORKFLOW_PHRASES = [
    "customer assistant",
    "customer service",
    "support",
    "ai sre",
    "incident response",
    "case management",
    "workflow",
    "rollout",
    "production",
    "deployment",
]

FDE_CONTEXT_PHRASES = [
    "customer",
    "client",
    "enterprise",
    "field",
    "solution",
    "solutions",
    "stakeholder",
    "deployment",
    "implementation",
    "palantir",
    "aip",
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

FDE_EXCLUDE_PHRASES = [
    "job hunt",
    "job search",
    "ranked jobs",
    "verified contacts",
    "new cs grad",
    "got two offers",
    "need to decide",
    "career advice",
    "salary negotiation",
    "serverless gpus",
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


def is_candidate_relevant_for_slot(item: CandidateItem, slot: str) -> bool:
    if slot != "fde":
        return is_candidate_relevant(item)

    content_text = " ".join([item.title, item.summary, item.content]).lower()
    if any(phrase in content_text for phrase in EXCLUDE_PHRASES + FDE_EXCLUDE_PHRASES):
        return False
    if _has_direct_fde_signal(content_text):
        return prefilter_score(item) >= 30
    has_enterprise_delivery = _has_enterprise_delivery_signal(content_text)
    has_contextual_governance = has_enterprise_delivery and _has_agent_governance_signal(content_text)
    if item.source_category == "discussion-fde":
        return has_contextual_governance and prefilter_score(item) >= 55
    if item.source_category in {"ai-engineering", "enterprise-ai", "field-engineering"}:
        return (
            has_enterprise_delivery
            or has_contextual_governance
        ) and prefilter_score(item) >= 40
    if item.source_category == "fde-industry":
        return (
            has_enterprise_delivery
            or has_contextual_governance
        ) and prefilter_score(item) >= 35
    return False


def _has_direct_fde_signal(text: str) -> bool:
    return any(phrase in text for phrase in FDE_STRONG_PHRASES)


def _has_enterprise_delivery_signal(text: str) -> bool:
    context_count = sum(1 for phrase in FDE_CONTEXT_PHRASES if phrase in text)
    delivery_count = sum(1 for phrase in FDE_DELIVERY_PHRASES if phrase in text)
    return context_count >= 1 and delivery_count >= 2


def _has_agent_governance_signal(text: str) -> bool:
    if not any(phrase in text for phrase in FDE_AGENT_PHRASES):
        return False
    governance_count = sum(1 for phrase in FDE_GOVERNANCE_PHRASES if phrase in text)
    workflow_count = sum(1 for phrase in FDE_WORKFLOW_PHRASES if phrase in text)
    delivery_count = sum(1 for phrase in FDE_DELIVERY_PHRASES if phrase in text)
    return governance_count >= 2 or (governance_count >= 1 and workflow_count + delivery_count >= 1)
