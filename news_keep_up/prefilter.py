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
    ("customer deployment", 24),
    ("customer rollout", 24),
    ("pilot to production", 22),
    ("production rollout", 20),
    ("launch gate", 18),
    ("acceptance criteria", 18),
    ("workflow integration", 18),
    ("eval gate", 18),
    ("eval", 12),
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
    "customer embedded",
    "customer-embedded",
    "customer delivery",
    "customer rollout",
    "customer deployment",
    "field delivery",
    "pilot to production",
    "production rollout",
    "workflow integration",
    "solution engineer",
    "sales engineer",
]

FDE_DELIVERY_PHRASES = [
    "implementation",
    "deploy",
    "deployment",
    "rollout",
    "evals",
    "guardrails",
    "rollout metrics",
    "workflow",
    "integration",
    "production",
    "production readiness",
    "launch gate",
    "acceptance criteria",
    "handoff",
    "rollback",
    "observability",
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
    "agent infrastructure",
    "api for computer-use agents",
    "arxiv listings",
    "computer-use agents",
    "deploy ai agents to slack",
    "generic research tooling",
    "my research",
    "not a concrete fde",
    "not a customer deployment",
    "not a customer rollout",
    "not customer deployment",
    "not field delivery",
    "own isolated computer",
    "personal research",
    "personal micro-apps",
    "research interests",
    "to-read list",
    "users add their own features",
    "without seeing code",
]

FDE_GENERIC_AI_PHRASES = [
    "api launch",
    "api launches",
    "api features",
    "benchmark",
    "benchmarks",
    "cloud deployment options",
    "cloud roundups",
    "coding-agent tools",
    "developer preview",
    "feature bundle",
    "faster coding-agent tools",
    "general aws updates",
    "model api",
    "model availability",
    "model launch",
    "model news",
    "new model",
    "service availability",
    "weekly roundup",
]

PRACTICAL_AI_WORKFLOW_PHRASES = [
    "adoption",
    "architecture",
    "automation",
    "case study",
    "code review",
    "delivery team",
    "delivery teams",
    "developer productivity",
    "engineering lifecycle",
    "eval",
    "evals",
    "guardrail",
    "guardrails",
    "how to",
    "implementation",
    "integration",
    "lesson",
    "lessons learned",
    "metrics",
    "observability",
    "pattern",
    "patterns",
    "playbook",
    "practice",
    "practices",
    "production",
    "product workflow",
    "product workflows",
    "reliability",
    "rollout",
    "ship",
    "testing",
    "workflow",
    "workflows",
]

AI_AGENT_PHRASES = [
    "agent",
    "agentic",
    "agents",
    "ai",
    "automation",
    "claude code",
    "coding agent",
    "codex",
    "llm",
    "mcp",
    "rag",
]

GENERIC_AI_ANNOUNCEMENT_PHRASES = [
    "announcement",
    "api features",
    "benchmark",
    "benchmarks",
    "cloud regions",
    "developer-tool launch",
    "is now in public beta",
    "launch announcement",
    "model availability",
    "model api",
    "new agent model",
    "public beta",
]

AI_AGENT_SOURCE_CATEGORIES = {
    "ai-engineering",
    "agentic-engineering",
    "developer-tools",
    "agent-frameworks",
    "agent-orchestration",
    "ai-automation",
    "ai-observability",
    "llm-ops",
    "ai-product",
    "ai-research",
    "discussion",
}


def prefilter_score(item: CandidateItem) -> int:
    text = " ".join([item.title, item.summary, item.content, item.source_category]).lower()
    if any(phrase in text for phrase in EXCLUDE_PHRASES):
        return 0

    score = 0
    for phrase, weight in INCLUDE_WEIGHTS:
        if phrase in text:
            score += weight

    if item.source_category in {
        "ai-engineering",
        "agentic-engineering",
        "developer-tools",
        "agent-frameworks",
        "agent-orchestration",
        "ai-automation",
        "ai-observability",
        "llm-ops",
    }:
        score += 10
    if item.source_category == "discussion":
        score -= 5
    return max(0, min(100, score))


def is_candidate_relevant(item: CandidateItem) -> bool:
    threshold = 45 if item.source_category == "discussion" else 30
    return prefilter_score(item) >= threshold


def is_candidate_relevant_for_slot(item: CandidateItem, slot: str) -> bool:
    if slot != "fde":
        return is_candidate_relevant(item) and _has_practical_ai_or_engineering_signal(item)

    content_text = " ".join([item.title, item.summary, item.content]).lower()
    if any(phrase in content_text for phrase in EXCLUDE_PHRASES + FDE_EXCLUDE_PHRASES):
        return False
    has_enterprise_delivery = _has_enterprise_delivery_signal(content_text)
    has_contextual_governance = has_enterprise_delivery and _has_agent_governance_signal(content_text)
    if _is_generic_ai_without_field_delivery(content_text, has_enterprise_delivery, has_contextual_governance):
        return False
    if _has_direct_fde_signal(content_text):
        return prefilter_score(item) >= 30
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


def _is_generic_ai_without_field_delivery(
    text: str,
    has_enterprise_delivery: bool,
    has_contextual_governance: bool,
) -> bool:
    if has_enterprise_delivery or has_contextual_governance or _has_direct_fde_signal(text):
        return False
    return any(phrase in text for phrase in FDE_GENERIC_AI_PHRASES)


def _has_practical_ai_or_engineering_signal(item: CandidateItem) -> bool:
    text = " ".join([item.title, item.summary, item.content, item.source_category]).lower()
    if item.source_category not in AI_AGENT_SOURCE_CATEGORIES:
        return True
    practical_count = sum(1 for phrase in PRACTICAL_AI_WORKFLOW_PHRASES if phrase in text)
    has_ai_agent = any(phrase in text for phrase in AI_AGENT_PHRASES)
    if any(phrase in text for phrase in GENERIC_AI_ANNOUNCEMENT_PHRASES) and practical_count < 2:
        return False
    return has_ai_agent and practical_count >= 1
