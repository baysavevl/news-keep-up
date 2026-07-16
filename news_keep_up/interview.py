from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from html import escape

from .gemini import GeminiClient
from .models import Settings
from .telegram import send_telegram_message
from .utils import ICT, now_ict


@dataclass(frozen=True)
class FdeInterviewGuideline:
    slug: str
    icon: str
    category: str
    title: str
    summary: str
    drill: str
    source_label: str
    source_url: str


FDE_INTERVIEW_GUIDELINES = [
    FdeInterviewGuideline(
        "agent-state",
        "🧭",
        "Agent architecture",
        "State is not chat history",
        "Explain current node, allowed tools, persisted results, retry behavior, and human review gates.",
        "Draw one billing-agent state machine with timeout and resume paths.",
        "LangGraph overview",
        "https://docs.langchain.com/oss/python/langgraph/overview",
    ),
    FdeInterviewGuideline(
        "tool-boundaries",
        "🛡",
        "Tool safety",
        "Separate read tools from write tools",
        "Production agents need typed schemas, scoped auth, validation, idempotency keys, and blocked unsafe actions.",
        "Design CRM lookup plus ticket creation tools and list rejected calls.",
        "OpenAI function calling",
        "https://developers.openai.com/api/docs/guides/function-calling",
    ),
    FdeInterviewGuideline(
        "eval-gates",
        "📊",
        "Evals",
        "Evals turn demos into deployments",
        "A strong FDE converts customer workflows into release gates: task success, safety, escalation, latency.",
        "Write 10 eval cases for billing, missing identity, tool timeout, and unsafe refund.",
        "OpenAI evals",
        "https://developers.openai.com/api/docs/guides/evals",
    ),
    FdeInterviewGuideline(
        "rag-vs-tools",
        "📚",
        "RAG",
        "Use docs for policy, tools for live state",
        "Interviewers look for freshness boundaries: retrieved policy text is not the same as account truth.",
        "Explain which facts need citation and which need live API calls.",
        "OpenAI retrieval",
        "https://developers.openai.com/api/docs/guides/retrieval",
    ),
    FdeInterviewGuideline(
        "voice-latency",
        "🎙",
        "Voice agents",
        "Voice adds latency and interruption risk",
        "Track STT, model, tool, TTS, total turn time, barge-in behavior, and human handoff quality.",
        "Sketch a Vietnamese support call timeline with one interruption.",
        "OpenAI realtime",
        "https://developers.openai.com/api/docs/guides/realtime",
    ),
    FdeInterviewGuideline(
        "enterprise-api",
        "🔌",
        "Integration",
        "The last mile is API, auth, and messy data",
        "A customer deployment fails when tenant boundaries, retries, stale records, or typed errors are vague.",
        "Create a failure matrix for 401, 403, 404, 409, 429, and 5xx.",
        "OpenAPI specification",
        "https://swagger.io/specification/",
    ),
    FdeInterviewGuideline(
        "security-guardrails",
        "🔐",
        "Security",
        "Enterprise trust is permissioned agency",
        "Show how the agent refuses, escalates, redacts PII, logs audit events, and avoids prompt injection.",
        "Write an authorization matrix for read, create ticket, refund, and account update.",
        "OWASP LLM Top 10",
        "https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),
    FdeInterviewGuideline(
        "observability",
        "🔎",
        "Observability",
        "Debug the boundary, not the vibe",
        "Good FDE answers name traces, tool calls, inputs, outputs, cost, latency, and acceptance metrics.",
        "Draft a 5-minute incident update: symptom, scope, suspected boundary, next action, ETA.",
        "Datadog Agent Observability",
        "https://www.datadoghq.com/blog/using-evaluation-frameworks-with-agent-observability/",
    ),
    FdeInterviewGuideline(
        "customer-discovery",
        "🤝",
        "Discovery",
        "Find the workflow before proposing architecture",
        "Interviewers test whether you can expose success metrics, blockers, stakeholders, data owners, and launch risk.",
        "Write five discovery questions for a bank support-agent rollout.",
        "First Round FDE hiring",
        "https://review.firstround.com/so-you-want-to-hire-a-forward-deployed-engineer/",
    ),
    FdeInterviewGuideline(
        "case-study",
        "📝",
        "Case study",
        "Use proof, tradeoffs, and launch metrics",
        "A strong written answer covers objective, workflow, architecture, risks, rollout plan, KPIs, and open questions.",
        "Write a one-page deployment memo for a bilingual billing agent.",
        "FDE interview guide",
        "https://www.tryexponent.com/blog/forward-deployed-engineer-interview-the-definitive-2026-guide-fde",
    ),
    FdeInterviewGuideline(
        "production-coding",
        "🧪",
        "Coding",
        "Code for idempotency and bad inputs",
        "FDE coding often maps to normalization, retries, dedupe, trace IDs, validation, and operational edge cases.",
        "Implement normalize-events -> idempotent action -> audit log in small functions.",
        "FDE coding copilot",
        "https://www.fwddeploy.com/mastering-the-forward-deployed-engineering-interview",
    ),
    FdeInterviewGuideline(
        "fit-story",
        "🎯",
        "Fit",
        "Translate backend work into deployment ownership",
        "Anchor answers in customer context, production debugging, measurable impact, reusable assets, and product feedback loops.",
        "Rewrite one Zalo project as a customer deployment story with before/after metrics.",
        "Pragmatic Engineer FDE",
        "https://newsletter.pragmaticengineer.com/p/forward-deployed-engineers",
    ),
]

INTERVIEW_SUPPORT_BY_SLUG = {
    "agent-state": (
        "Engineering",
        "System design / agent architecture",
        "state machine, persistence, retry path, resume path, human review gate",
    ),
    "tool-boundaries": (
        "Engineering",
        "System design / tool safety",
        "typed schema, scoped auth, validation, idempotency key, blocked unsafe action",
    ),
    "eval-gates": (
        "Delivery/Ops",
        "Deployment readiness",
        "task success eval, safety eval, escalation rule, latency target, launch gate",
    ),
    "rag-vs-tools": (
        "Engineering",
        "System design / RAG vs tools",
        "freshness boundary, citation, policy retrieval, live account state, API truth",
    ),
    "voice-latency": (
        "Engineering",
        "Voice agent design",
        "latency budget, interruption handling, turn timeline, barge-in, human handoff",
    ),
    "enterprise-api": (
        "Engineering",
        "Integration design",
        "auth, tenant boundary, retry, typed error, stale record, rate limit",
    ),
    "security-guardrails": (
        "Security/Governance",
        "Security / governance",
        "permission model, PII redaction, audit log, escalation, prompt-injection defense",
    ),
    "observability": (
        "Delivery/Ops",
        "Production debugging",
        "trace, tool call, input/output log, cost, latency, acceptance metric",
    ),
    "customer-discovery": (
        "Consulting",
        "Customer discovery",
        "success metric, stakeholder, blocker, data owner, launch risk",
    ),
    "case-study": (
        "Consulting",
        "Written case study",
        "objective, workflow, architecture tradeoff, rollout plan, KPI, open question",
    ),
    "production-coding": (
        "Engineering",
        "Coding screen",
        "normalization, idempotency, validation, retry, dedupe, trace ID, audit log",
    ),
    "fit-story": (
        "Product",
        "Behavioral / fit",
        "customer context, deployment ownership, measurable impact, reusable asset, product feedback",
    ),
}


def select_fde_interview_guideline(current: datetime | None = None) -> FdeInterviewGuideline:
    return select_fde_interview_guidelines(current, count=1)[0]


def select_fde_interview_guidelines(
    current: datetime | None = None,
    count: int = 2,
) -> list[FdeInterviewGuideline]:
    now = current or now_ict()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ICT)
    else:
        now = now.astimezone(ICT)
    minutes = now.hour * 60 + now.minute
    window = max(0, (minutes - (7 * 60 + 35)) // 60)
    day_offset = now.toordinal() * 16
    start = day_offset + window * max(1, count)
    return [
        FDE_INTERVIEW_GUIDELINES[(start + offset) % len(FDE_INTERVIEW_GUIDELINES)]
        for offset in range(max(1, count))
    ]


def format_fde_interview_guideline(
    cards: FdeInterviewGuideline | list[FdeInterviewGuideline],
) -> str:
    normalized_cards = [cards] if isinstance(cards, FdeInterviewGuideline) else cards
    lines = ["<b>🧭 FDE Interview Guideline</b>"]
    for index, card in enumerate(normalized_cards, start=1):
        fde_topic, interview_focus, knowledge = _interview_support(card)
        lines.extend([
            "",
            f"<b>{index}. {escape(card.icon)} {escape(card.category)}: {escape(card.title)}</b>",
            f"🎯 FDE topic: {escape(fde_topic)}",
            f"🧩 Interview focus: {escape(interview_focus)}",
            f"📚 Kiến thức: {escape(knowledge)}",
            f"💡 {escape(card.summary)}",
            f"🧪 Drill: {escape(card.drill)}",
            f'🔗 Source: <a href="{escape(card.source_url, quote=True)}">{escape(card.source_label)}</a>',
        ])
    return "\n".join(lines).strip()


def format_fde_interview_announcement(
    cards: list[FdeInterviewGuideline],
    current: datetime | None = None,
) -> str:
    now = current or now_ict()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ICT)
    else:
        now = now.astimezone(ICT)
    fde_topics = []
    for card in cards:
        fde_topic, _, _ = _interview_support(card)
        if fde_topic not in fde_topics:
            fde_topics.append(fde_topic)
    return "\n".join([
        "<b>🧭 FDE Interview Prep Thread</b>",
        f"Time: {escape(now.strftime('%d %b %H:%M'))} ICT",
        "Schedule: hourly at :35",
        f"Contents: {len(cards)} focused drills",
        f"FDE topics: {escape(' · '.join(fde_topics[:3]))}",
    ])


def _interview_support(card: FdeInterviewGuideline) -> tuple[str, str, str]:
    if card.slug in INTERVIEW_SUPPORT_BY_SLUG:
        return INTERVIEW_SUPPORT_BY_SLUG[card.slug]
    category = card.category.lower()
    if "coding" in category:
        return INTERVIEW_SUPPORT_BY_SLUG["production-coding"]
    if "fit" in category:
        return INTERVIEW_SUPPORT_BY_SLUG["fit-story"]
    if "integration" in category:
        return INTERVIEW_SUPPORT_BY_SLUG["enterprise-api"]
    if "security" in category:
        return INTERVIEW_SUPPORT_BY_SLUG["security-guardrails"]
    return (
        "Delivery/Ops",
        "FDE interview practice",
        "customer context, production constraint, tradeoff, measurable outcome",
    )


def run_fde_interview_guideline(
    settings: Settings,
    dry_run: bool = False,
    current: datetime | None = None,
) -> str:
    cards = select_fde_interview_guidelines(current)
    reviewed_cards: list[FdeInterviewGuideline] = []
    client = GeminiClient(settings)
    for card in cards:
        reviewed = client.review_interview_guideline(asdict(card))
        if reviewed:
            card = replace(
                card,
                icon=reviewed.get("icon", card.icon),
                category=reviewed.get("category", card.category),
                title=reviewed.get("title", card.title),
                summary=reviewed.get("summary", card.summary),
                drill=reviewed.get("drill", card.drill),
                source_label=reviewed.get("source_label", card.source_label),
            )
        reviewed_cards.append(card)
    announcement = format_fde_interview_announcement(reviewed_cards, current)
    guideline = format_fde_interview_guideline(reviewed_cards)
    message = f"{announcement}\n\n{guideline}"
    if not dry_run:
        send_telegram_message(announcement, settings)
        send_telegram_message(guideline, settings)
    return message
