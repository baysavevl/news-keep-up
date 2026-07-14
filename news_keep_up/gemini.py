from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Mapping

from .models import CandidateItem, DigestCandidate, Enrichment, Settings
from .utils import clean_text


def build_prompt(item: CandidateItem) -> str:
    item_json = json.dumps({
        "title": item.title,
        "source": item.source_name,
        "source_category": item.source_category,
        "summary": item.summary,
        "url": item.url,
    }, ensure_ascii=False)
    return (
        "You curate a compact recurring digest for a software engineer, "
        "forward deployed engineer, and solution architect. Score only practical, "
        "high-signal items about AI, AI agents, developer tools, architecture, "
        "and customer-facing technical work. For Forward Deployed Engineer topics, "
        "prioritize customer deployment, enterprise workflow integration, evals, "
        "guardrails, stakeholder rollout, and product feedback loops. Reject generic "
        "AI infrastructure or coding-agent posts unless they clearly affect field "
        "engineering or enterprise deployment work. For FDE, reject generic AI roundups, "
        "API launches, model news, cloud service updates, and coding-agent tools unless "
        "the item includes customer rollout, field delivery, production governance, "
        "or enterprise implementation impact.\n\n"
        "Write for a Telegram scan: concrete, opinionated, and non-generic.\n"
        "- summary must start with one key idea that is not a title rewrite.\n"
        "- summary must then include 3-5 concrete highlights separated by semicolons or short sentences.\n"
        "- highlights must explain what changed, evidence/signals, constraints/risks, and what an engineer should do next.\n"
        "- do not copy the article title into summary or highlights.\n"
        "- why_it_matters must explain impact for SWE/FDE/solution architect work.\n"
        "- relevance_score is the importance score.\n"
        "- use category/topic that can be displayed beside popularity, source trust, importance, and impact.\n"
        "- icon should be a short emoji-like signal or compact label for the item.\n\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "relevance_score": 0,\n'
        '  "category": "ai-engineering",\n'
        '  "topic": "coding-agents",\n'
        '  "icon": "🤖",\n'
        '  "title_vi": "Vietnamese title translation",\n'
        '  "summary": "Key idea sentence. Highlight 1 with concrete detail; Highlight 2 with evidence or risk; Highlight 3 with action/use-case.",\n'
        '  "why_it_matters": "Impact: why this matters for SWE/FDE/solution architect work.",\n'
        '  "takeaway_vi": "One short Vietnamese takeaway.",\n'
        '  "should_send": true\n'
        "}\n\n"
        f"Item:\n{item_json}"
    )


def build_digest_review_prompt(slot: str, candidates: list[DigestCandidate], max_items: int) -> str:
    profile = "Forward Deployed Engineer" if slot == "fde" else "software engineer"
    items_json = json.dumps([
        {
            "item_id": item.item_id,
            "title": item.title,
            "source": item.source_name,
            "source_category": item.source_category,
            "url": item.url,
            "current_score": item.enrichment.relevance_score,
            "category": item.enrichment.category,
            "topic": item.enrichment.topic,
            "summary": item.enrichment.summary,
            "why_it_matters": item.enrichment.why_it_matters,
            "is_backfill": item.is_backfill,
        }
        for item in candidates
    ], ensure_ascii=False)
    return (
        f"You are the final Gemini editor for a Telegram digest for a {profile}. "
        f"Review this batch and rank only the best, highest-impact {max_items} items. "
        "Prefer practical AI-agent, automation, orchestration, evals, observability, "
        "developer productivity, and production delivery news. Use emoji, concrete "
        "summaries, clear categories, and role-specific impact. "
        "For every selected item, rewrite the summary into one key idea plus 3-5 specific highlights; "
        "do not repeat the title, and avoid generic claims like useful, important, or relevant unless followed by concrete evidence. "
        "For Forward Deployed Engineer, reject generic AI/model/API/cloud/coding-tool news "
        "unless it changes customer rollout, field delivery, enterprise implementation, "
        "evals, governance, or production risk.\n\n"
        "Return JSON only with this exact shape. Include low-impact items with "
        "should_send=false when they should be filtered out:\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "item_id": 123,\n'
        '      "rank": 1,\n'
        '      "relevance_score": 95,\n'
        '      "category": "ai-engineering",\n'
        '      "topic": "agent-orchestration",\n'
        '      "icon": "🤖",\n'
        '      "summary": "Key idea sentence. Highlight 1 with concrete detail; Highlight 2 with evidence/risk; Highlight 3 with action/use-case.",\n'
        '      "why_it_matters": "Impact: concise role-specific impact.",\n'
        '      "takeaway_vi": "Một ý rút ra ngắn bằng tiếng Việt.",\n'
        '      "should_send": true\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Items:\n{items_json}"
    )


def parse_enrichment_response(text: str, item: CandidateItem, model: str) -> Enrichment:
    try:
        data = json.loads(_extract_json(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return fallback_enrichment(item, "bad-json")

    score = _clamp_int(data.get("relevance_score"), 0, 100, 0)
    summary = clean_text(data.get("summary", "")) or _fallback_summary(item)
    title_vi = clean_text(data.get("title_vi", "")) or _fallback_title_vi(item)
    why = clean_text(data.get("why_it_matters", "")) or "Useful signal for AI-assisted engineering and customer delivery work."
    takeaway = clean_text(data.get("takeaway_vi", "")) or "Nên xem nhanh để cập nhật xu hướng AI thực dụng."
    return Enrichment(
        model=model,
        relevance_score=score,
        category=clean_text(data.get("category", "")) or item.source_category or "general",
        topic=clean_text(data.get("topic", "")) or "ai",
        icon=clean_text(data.get("icon", "")) or "AI",
        title_vi=title_vi,
        summary=summary,
        why_it_matters=why,
        takeaway_vi=takeaway,
        should_send=bool(data.get("should_send", score >= 65)),
    )


def parse_digest_review_response(
    text: str,
    candidates: list[DigestCandidate],
    model: str,
) -> dict[int, Enrichment]:
    try:
        data = json.loads(_extract_json(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}

    by_id = {candidate.item_id: candidate for candidate in candidates}
    reviewed: dict[int, Enrichment] = {}
    for row in data.get("items", []):
        item_id = _clamp_int(row.get("item_id"), 0, 10_000_000_000, 0)
        candidate = by_id.get(item_id)
        if candidate is None:
            continue
        original = candidate.enrichment
        score = _clamp_int(row.get("relevance_score"), 0, 100, original.relevance_score)
        summary = clean_text(row.get("summary", "")) or original.summary
        why = clean_text(row.get("why_it_matters", "")) or original.why_it_matters
        takeaway = clean_text(row.get("takeaway_vi", "")) or original.takeaway_vi
        reviewed[item_id] = replace(
            original,
            model=model,
            relevance_score=score,
            category=clean_text(row.get("category", "")) or original.category,
            topic=clean_text(row.get("topic", "")) or original.topic,
            icon=clean_text(row.get("icon", "")) or original.icon,
            summary=summary,
            why_it_matters=why,
            takeaway_vi=takeaway,
            should_send=bool(row.get("should_send", score >= 65)),
        )
    return reviewed


def fallback_enrichment(item: CandidateItem, reason: str = "fallback") -> Enrichment:
    return Enrichment(
        model=f"fallback:{reason}",
        relevance_score=65,
        category=item.source_category or "general",
        topic=_guess_topic(item),
        icon=_guess_icon(item),
        title_vi=_fallback_title_vi(item),
        summary=_fallback_summary(item),
        why_it_matters=_fallback_why(item),
        takeaway_vi=_fallback_takeaway_vi(item),
        should_send=True,
    )


class GeminiClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def enrich(self, item: CandidateItem) -> Enrichment:
        if not self.settings.gemini_api_key:
            return fallback_enrichment(item, "no-key")

        for model in [self.settings.gemini_model, self.settings.gemini_fallback_model]:
            if not model:
                continue
            try:
                text = self._call_model(model, item)
                enrichment = parse_enrichment_response(text, item, model)
                if enrichment.model.startswith("fallback:"):
                    continue
                return enrichment
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, TypeError):
                continue
        return fallback_enrichment(item, "gemini-error")

    def review_digest_candidates(
        self,
        slot: str,
        candidates: list[DigestCandidate],
        max_items: int,
    ) -> dict[int, Enrichment]:
        if not self.settings.gemini_api_key or not candidates:
            return {}

        prompt = build_digest_review_prompt(slot, candidates, max_items)
        for model in [self.settings.gemini_model, self.settings.gemini_fallback_model]:
            if not model:
                continue
            try:
                text = self._call_prompt(model, prompt, max_output_tokens=3200)
                reviewed = parse_digest_review_response(text, candidates, model)
                if reviewed:
                    return reviewed
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, TypeError):
                continue
        return {}

    def review_interview_guideline(self, card: Mapping[str, str]) -> dict[str, str]:
        if not self.settings.gemini_api_key:
            return {}

        prompt = (
            "You are editing one Telegram message for Forward Deployed Engineer interview prep. "
            "Keep it compact and practical. Return JSON only with icon, category, title, summary, drill, source_label.\n"
            "Rules: summary is one short sentence, drill is one concrete practice action, no more than 22 words per field.\n\n"
            f"Card:\n{json.dumps(dict(card), ensure_ascii=False)}"
        )
        for model in [self.settings.gemini_model, self.settings.gemini_fallback_model]:
            if not model:
                continue
            try:
                text = self._call_prompt(model, prompt, max_output_tokens=400)
                data = json.loads(_extract_json(text))
                return {
                    key: clean_text(data.get(key, ""))
                    for key in ("icon", "category", "title", "summary", "drill", "source_label")
                    if clean_text(data.get(key, ""))
                }
            except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, KeyError, ValueError, TypeError):
                continue
        return {}

    def _call_model(self, model: str, item: CandidateItem) -> str:
        return self._call_prompt(model, build_prompt(item), max_output_tokens=600)

    def _call_prompt(self, model: str, prompt: str, max_output_tokens: int) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.settings.gemini_api_key}"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_output_tokens, "topP": 0.9},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)


def _extract_json(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found")
    return value[start:end + 1]


def _clamp_int(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _fallback_summary(item: CandidateItem) -> str:
    return clean_text(item.summary or item.content or item.title)[:600]


def _fallback_title_vi(item: CandidateItem) -> str:
    return f"{item.title} (bản dịch tự động chưa có)"


def _guess_topic(item: CandidateItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    if "forward deployed" in text or "customer" in text or "deployment" in text:
        return "enterprise-rollout"
    if "agent" in text:
        return "coding-agents"
    if "rag" in text:
        return "rag"
    if "mcp" in text:
        return "mcp"
    if "tool" in text:
        return "ai-tools"
    return "ai"


def _guess_icon(item: CandidateItem) -> str:
    text = f"{item.title} {item.summary} {item.source_category}".lower()
    if "forward deployed" in text or "deployment" in text or "customer" in text:
        return "🧭"
    if "eval" in text or "benchmark" in text:
        return "📊"
    if "rag" in text or "knowledge" in text:
        return "📚"
    if "agent" in text:
        return "🤖"
    return "🧠"


def _fallback_why(item: CandidateItem) -> str:
    text = f"{item.title} {item.summary} {item.source_category}".lower()
    if "enterprise" in text or "customer" in text or "deployment" in text:
        return "Shows a concrete signal for moving AI from demo to customer-facing production workflow."
    if "eval" in text or "guardrail" in text:
        return "Useful for deciding whether an AI workflow is safe enough to launch and maintain."
    if "agent" in text:
        return "Relevant to how engineering teams design, supervise, and operationalize agent workflows."
    return "Worth scanning for architecture, delivery, or productization impact."


def _fallback_takeaway_vi(item: CandidateItem) -> str:
    text = f"{item.title} {item.summary} {item.source_category}".lower()
    if "deployment" in text or "customer" in text:
        return "Tập trung vào cách đưa AI vào workflow khách hàng thật, không chỉ demo."
    if "eval" in text or "guardrail" in text:
        return "Chú ý phần đo chất lượng và guardrail trước khi rollout."
    return "Đọc nhanh để lấy ý chính và cân nhắc áp dụng vào delivery."
