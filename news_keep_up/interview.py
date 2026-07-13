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


def select_fde_interview_guideline(current: datetime | None = None) -> FdeInterviewGuideline:
    now = current or now_ict()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ICT)
    else:
        now = now.astimezone(ICT)
    minutes = now.hour * 60 + now.minute
    window = max(0, (minutes - (7 * 60 + 35)) // 120)
    day_offset = now.toordinal() * 8
    return FDE_INTERVIEW_GUIDELINES[(day_offset + window) % len(FDE_INTERVIEW_GUIDELINES)]


def format_fde_interview_guideline(card: FdeInterviewGuideline) -> str:
    return "\n".join([
        f"<b>{escape(card.icon)} FDE Interview Guideline</b>",
        f"🎯 {escape(card.category)}: {escape(card.title)}",
        f"💡 {escape(card.summary)}",
        f"🧪 Drill: {escape(card.drill)}",
        f'🔗 Source: <a href="{escape(card.source_url, quote=True)}">{escape(card.source_label)}</a>',
    ])


def run_fde_interview_guideline(
    settings: Settings,
    dry_run: bool = False,
    current: datetime | None = None,
) -> str:
    card = select_fde_interview_guideline(current)
    reviewed = GeminiClient(settings).review_interview_guideline(asdict(card))
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
    message = format_fde_interview_guideline(card)
    if not dry_run:
        send_telegram_message(message, settings)
    return message
