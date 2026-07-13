from __future__ import annotations

import json
import urllib.error
import urllib.request

from .models import CandidateItem, Enrichment, Settings
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
        "engineering or enterprise deployment work.\n\n"
        "Write for a Telegram scan: concrete, opinionated, and non-generic.\n"
        "- summary must start with the key idea, then include 1-2 specific highlights.\n"
        "- why_it_matters must explain the importance for SWE/FDE/solution architect work.\n"
        "- relevance_score is the importance score.\n"
        "- use category/topic that can be displayed beside popularity and importance.\n"
        "- icon should be a short emoji-like signal or compact label for the item.\n\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "relevance_score": 0,\n'
        '  "category": "ai-engineering",\n'
        '  "topic": "coding-agents",\n'
        '  "icon": "🤖",\n'
        '  "title_vi": "Vietnamese title translation",\n'
        '  "summary": "Key idea sentence. Highlight sentence with concrete detail. Optional second highlight.",\n'
        '  "why_it_matters": "Importance: why this matters for SWE/FDE/solution architect work.",\n'
        '  "takeaway_vi": "One short Vietnamese takeaway.",\n'
        '  "should_send": true\n'
        "}\n\n"
        f"Item:\n{item_json}"
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

    def _call_model(self, model: str, item: CandidateItem) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.settings.gemini_api_key}"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": build_prompt(item)}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600, "topP": 0.9},
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
