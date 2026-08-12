from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Mapping

from .job_filters import (
    is_auto_alertable_from_vietnam_opportunity,
    vietnam_workability_for_candidate,
)
from .job_search_policy import (
    evaluate_job_candidate,
    load_job_search_policy,
    policy_prompt_fragment,
)
from .models import CandidateItem, DigestCandidate, Enrichment, JobOpportunity, Settings
from .utils import canonicalize_url, clean_text


DECISION_TO_ACTION = {
    "APPLY_NOW": "apply_now",
    "VERIFY_FIRST": "verify_first",
    "DM_FIRST": "dm_first",
    "WATCH": "watch",
    "REJECT": "ignore",
}


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
    if slot == "fde":
        focus_instruction = (
            "Prefer customer rollout, field delivery, enterprise implementation, evals, "
            "governance, observability, stakeholder handoff, and production risk. "
            "Before marking should_send=true, analyze whether the item materially helps a "
            "Forward Deployed Engineer deliver, govern, integrate, or roll out software in "
            "a customer/enterprise environment. "
            "Reject generic AI/model/API/cloud/coding-tool news unless it changes a real "
            "customer deployment or field-delivery workflow. "
            "Reject personal research triage, arXiv/news digest tools, paper recommendation "
            "workflows, and individual productivity tools unless they include a concrete "
            "customer deployment, enterprise integration, production governance, or field "
            "delivery lesson. "
            "For every selected FDE item, rewrite the summary as exactly 5 specific highlights "
            "separated by semicolons or short sentences, with no separate key idea sentence "
            "and no 'key idea' prefix. "
        )
        summary_example = (
            "Highlight 1 with the rollout change; Highlight 2 with customer or stakeholder signal; "
            "Highlight 3 with eval/governance risk; Highlight 4 with integration or observability detail; "
            "Highlight 5 with the action an FDE should take."
        )
    else:
        focus_instruction = (
            "Prefer practical AI-agent, automation, orchestration, evals, observability, "
            "developer productivity, and production delivery news. "
            "For every selected item, rewrite the summary into one key idea plus 3-5 specific highlights; "
        )
        summary_example = (
            "Key idea sentence. Highlight 1 with concrete detail; Highlight 2 with evidence/risk; "
            "Highlight 3 with action/use-case."
        )
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
        f"{focus_instruction}"
        "Use emoji, concrete summaries, clear categories, and role-specific impact. "
        "do not repeat the title, and avoid generic claims like useful, important, or relevant unless followed by concrete evidence. "
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
        f'      "summary": "{summary_example}",\n'
        '      "why_it_matters": "Impact: concise role-specific impact.",\n'
        '      "takeaway_vi": "Một ý rút ra ngắn bằng tiếng Việt.",\n'
        '      "should_send": true\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Items:\n{items_json}"
    )


def build_job_classification_prompt(
    candidates: list[tuple[int, CandidateItem]],
    crawled_at: str,
) -> str:
    items_json = json.dumps([
        {
            "candidate_id": item_id,
            "source_name": item.source_name,
            "source_type_hint": _source_type_hint(item),
            "source_category": item.source_category,
            "title": item.title,
            "url": item.url,
            "summary": _trim_for_prompt(item.summary or item.content, 700),
            "parsed_metadata": item.raw if isinstance(item.raw, dict) else {},
            "published_at": item.published_at,
        }
        for item_id, item in candidates
    ], ensure_ascii=False)
    policy_text = policy_prompt_fragment()
    return (
        "You classify technical job and hidden-hiring candidates.\n"
        f"{policy_text}\n"
        "Use only supplied evidence. Empty unknown fields and add them to "
        "what_to_verify.\n"
        "Return JSON only. Each item must include candidate_id, id, decision, "
        "priority, company, role_family, role_title, category, location, "
        "remote_policy, vietnam_eligibility, evidence_type, status, posted_date, "
        "source_type, source_url, apply_url, contact_person, contact_url, "
        "technical_evidence, why_it_fits, what_to_verify, required_seniority, "
        "required_skills, domain, country, compensation, benefits, package, "
        "company_size, company_coverage, company_expansion_signal, "
        "linkedin_post_signal, recommended_action, outreach_angle, "
        "confidence_score, and should_alert.\n"
        "Use Hard|Medium|Weak for application evidence_type. should_alert=false "
        "only for REJECT or closed; true otherwise.\n\n"
        f"Crawled at: {crawled_at}\nCandidates:\n{items_json}"
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


def parse_job_classification_response(
    text: str,
    candidates_by_id: dict[int, CandidateItem],
    model: str,
    crawled_at: str,
) -> list[JobOpportunity]:
    try:
        data = json.loads(_extract_json(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return []

    opportunities: list[JobOpportunity] = []
    for row in data.get("items", []):
        candidate_id = _clamp_int(row.get("candidate_id"), 0, 10_000_000_000, 0)
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            continue
        opportunity = _job_opportunity_from_row(row, candidate_id, candidate, crawled_at)
        validated = validate_job_opportunity(opportunity, candidate)
        if validated is not None:
            opportunities.append(validated)
    return opportunities


def validate_job_opportunity(
    opportunity: JobOpportunity,
    candidate: CandidateItem,
) -> JobOpportunity | None:
    match = evaluate_job_candidate(candidate)
    if not match.is_eligible or opportunity.status == "closed":
        return None

    source_workability = vietnam_workability_for_candidate(candidate)
    if source_workability == "no":
        return None

    action = opportunity.recommended_action
    eligibility = opportunity.vietnam_eligibility
    evidence_type = opportunity.evidence_type
    if action == "ignore":
        action = (
            "apply_now"
            if source_workability == "explicit_yes"
            else "verify_first"
        )
    if source_workability == "verify":
        eligibility = "verify"
        evidence_type = "Weak"
        if action == "apply_now":
            action = "verify_first"
    elif source_workability == "likely_possible":
        eligibility = "likely_possible"
        evidence_type = "Medium"
        if action == "apply_now":
            action = "verify_first"
    elif source_workability == "explicit_yes":
        eligibility = "explicit_yes"
        evidence_type = "Hard"

    technical = ", ".join(match.technical_evidence) or (
        "role title and customer-delivery scope"
    )
    why = opportunity.why_it_fits.strip()
    if not why.lower().startswith("technical evidence:"):
        why = f"Technical evidence: {technical}. {why}".strip()

    validated = replace(
        opportunity,
        category=match.role_family_label,
        required_seniority=opportunity.required_seniority or match.seniority,
        domain=list(match.domain_evidence) or opportunity.domain,
        vietnam_eligibility=eligibility,
        evidence_type=evidence_type,
        recommended_action=action,
        why_it_fits=why,
        should_alert=False,
    )
    return replace(
        validated,
        should_alert=is_auto_alertable_from_vietnam_opportunity(validated),
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


def fallback_job_opportunities(
    candidates: list[tuple[int, CandidateItem]],
    crawled_at: str,
) -> list[JobOpportunity]:
    opportunities: list[JobOpportunity] = []
    for item_id, candidate in candidates:
        match = evaluate_job_candidate(candidate)
        if not match.is_eligible:
            continue
        workability = vietnam_workability_for_candidate(candidate)
        if workability == "no":
            continue
        text = f"{candidate.title} {candidate.summary} {candidate.content}".lower()
        company = _candidate_metadata(candidate, "company") or _company_from_source_name(candidate.source_name)
        role_title = _candidate_metadata(candidate, "role_title") or candidate.title
        location = _candidate_metadata(candidate, "location") or _fallback_location(candidate)
        remote_policy = _candidate_metadata(candidate, "remote_policy") or ("Remote" if "remote" in f"{location} {text}".lower() else "")
        source_type = _source_type_hint(candidate)
        expansion_only = any(
            term in f"{candidate.title} {candidate.summary}".lower()
            for term in (
                "expanding our team",
                "building the team",
                "no exact open role",
            )
        )
        if expansion_only:
            action = "watch"
        elif match.hidden_hiring and source_type == "LinkedIn_post":
            action = "dm_first"
        else:
            action = "apply_now" if workability == "explicit_yes" else "verify_first"
        status = "likely_open" if source_type in {"ATS", "official_career_page", "job_board"} else "uncertain"
        row = {
            "candidate_id": item_id,
            "id": "",
            "priority": {"apply_now": "High", "watch": "Low"}.get(
                action, "Medium"
            ),
            "company": company,
            "role_title": role_title,
            "role_family": match.role_family_label,
            "category": match.role_family_label,
            "location": location,
            "remote_policy": remote_policy,
            "vietnam_eligibility": workability,
            "evidence_type": "Hard" if workability == "explicit_yes" else "Medium",
            "status": "watch" if action == "watch" else status,
            "posted_date": candidate.published_at,
            "source_type": source_type,
            "source_url": candidate.url,
            "apply_url": candidate.url,
            "technical_evidence": list(match.technical_evidence),
            "why_it_fits": (
                "Technical evidence: "
                f"{', '.join(match.technical_evidence) or 'customer-delivery role scope'}. "
                f"Role family: {match.role_family_label}."
            ),
            "what_to_verify": _fallback_job_verify_items(location, remote_policy),
            "required_seniority": match.seniority,
            "domain": list(match.domain_evidence),
            "decision": {
                "apply_now": "APPLY_NOW",
                "verify_first": "VERIFY_FIRST",
                "dm_first": "DM_FIRST",
                "watch": "WATCH",
            }[action],
            "recommended_action": action,
            "confidence_score": 72 if action == "apply_now" else 60,
            "country": _candidate_metadata(candidate, "country") or _country_from_location(location),
            "compensation": _candidate_metadata(candidate, "compensation"),
            "benefits": _candidate_metadata(candidate, "benefits"),
            "package": _candidate_metadata(candidate, "package"),
            "company_size": _candidate_metadata(candidate, "company_size"),
            "company_coverage": _candidate_metadata(candidate, "company_coverage"),
        }
        opportunity = _job_opportunity_from_row(row, item_id, candidate, crawled_at)
        validated = validate_job_opportunity(opportunity, candidate)
        if validated is not None:
            opportunities.append(validated)
    return opportunities


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

    def classify_job_candidates(
        self,
        candidates: list[tuple[int, CandidateItem]],
        crawled_at: str,
    ) -> list[JobOpportunity]:
        if not candidates:
            return []
        if not self.settings.gemini_api_key:
            return fallback_job_opportunities(candidates, crawled_at)

        prompt = build_job_classification_prompt(candidates, crawled_at)
        candidates_by_id = {item_id: item for item_id, item in candidates}
        for model in [self.settings.gemini_model, self.settings.gemini_fallback_model]:
            if not model:
                continue
            try:
                text = self._call_prompt(model, prompt, max_output_tokens=5200)
                opportunities = parse_job_classification_response(text, candidates_by_id, model, crawled_at)
                if opportunities:
                    return opportunities
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, TypeError):
                continue
        return fallback_job_opportunities(candidates, crawled_at)

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


def _job_opportunity_from_row(
    row: Mapping[str, object],
    candidate_id: int,
    candidate: CandidateItem,
    crawled_at: str,
) -> JobOpportunity:
    policy = load_job_search_policy()
    priority = _enum_value(row.get("priority"), {"High", "Medium", "Low"}, "Low")
    status = _enum_value(row.get("status"), {"open", "likely_open", "uncertain", "closed", "watch"}, "uncertain")
    allowed_categories = {family.label for family in policy.role_families} | {
        "Exact FDE Role",
        "FDE-Adjacent Role",
        "Expansion Signal",
        "Hidden Hiring Signal",
        "Watchlist Company",
        "Reject",
    }
    category = _enum_value(
        row.get("role_family") or row.get("category"),
        allowed_categories,
        "Reject",
    )
    decision = _enum_value(row.get("decision"), set(policy.decisions), "")
    allowed_actions = {
        "apply_now",
        "verify_first",
        "dm_first",
        "watch",
        "ignore",
        "dm_recruiter_first",
        "follow_company",
        "set_alert",
    }
    recommended_action = DECISION_TO_ACTION.get(
        decision,
        _enum_value(
            row.get("recommended_action"), allowed_actions, "verify_first"
        ),
    )
    technical_evidence = _string_list(row.get("technical_evidence"))
    confidence = _clamp_int(row.get("confidence_score"), 0, 100, 0)
    company = clean_text(row.get("company", "")) or _candidate_metadata(candidate, "company") or _company_from_source_name(candidate.source_name)
    role_title = clean_text(row.get("role_title", "")) or _candidate_metadata(candidate, "role_title") or candidate.title
    location = clean_text(row.get("location", "")) or _candidate_metadata(candidate, "location")
    source_url = canonicalize_url(
        clean_text(row.get("source_url", ""))
        or candidate.canonical_url
        or candidate.url
    )
    apply_url = canonicalize_url(clean_text(row.get("apply_url", "")))
    why_it_fits = clean_text(row.get("why_it_fits", "")) or _fallback_job_fit(
        candidate
    )
    if technical_evidence and not why_it_fits.lower().startswith(
        "technical evidence:"
    ):
        why_it_fits = (
            f"Technical evidence: {', '.join(technical_evidence)}. {why_it_fits}"
        ).strip()
    should_alert = status != "closed" and category != "Reject"
    return JobOpportunity(
        id=_stable_job_id(clean_text(row.get("id", "")), company, role_title, location, source_url),
        source_item_id=candidate_id,
        source_fingerprint=candidate.fingerprint or _stable_job_id("", candidate.title, candidate.summary, source_url, ""),
        crawled_at=crawled_at,
        priority=priority,
        company=company,
        role_title=role_title,
        category=category,
        location=location,
        remote_policy=clean_text(row.get("remote_policy", "")) or _candidate_metadata(candidate, "remote_policy"),
        vietnam_eligibility=_enum_value(
            row.get("vietnam_eligibility"),
            {"explicit_yes", "likely_possible", "verify", "unlikely", "no"},
            "verify",
        ),
        evidence_type=_enum_value(row.get("evidence_type"), {"Hard", "Medium", "Weak"}, "Weak"),
        status=status,
        posted_date=clean_text(row.get("posted_date", "")) or candidate.published_at,
        source_type=clean_text(row.get("source_type", "")) or _source_type_hint(candidate),
        source_url=source_url,
        apply_url=apply_url,
        contact_person=clean_text(row.get("contact_person", "")),
        contact_url=clean_text(row.get("contact_url", "")),
        why_it_fits=why_it_fits,
        what_to_verify=_string_list(row.get("what_to_verify")),
        required_seniority=clean_text(row.get("required_seniority", "")),
        required_skills=_string_list(row.get("required_skills")),
        domain=_string_list(row.get("domain")),
        country=clean_text(row.get("country", "")) or _candidate_metadata(candidate, "country") or _country_from_location(location),
        compensation=clean_text(row.get("compensation", "")) or _candidate_metadata(candidate, "compensation"),
        benefits=clean_text(row.get("benefits", "")) or _candidate_metadata(candidate, "benefits"),
        package=clean_text(row.get("package", "")) or _candidate_metadata(candidate, "package"),
        company_size=clean_text(row.get("company_size", "")) or _candidate_metadata(candidate, "company_size"),
        company_coverage=clean_text(row.get("company_coverage", "")) or _candidate_metadata(candidate, "company_coverage"),
        company_expansion_signal=clean_text(row.get("company_expansion_signal", "")),
        linkedin_post_signal=clean_text(row.get("linkedin_post_signal", "")),
        recommended_action=recommended_action,
        outreach_angle=clean_text(row.get("outreach_angle", "")),
        confidence_score=confidence,
        should_alert=should_alert,
    )


def _source_type_hint(item: CandidateItem) -> str:
    metadata_type = clean_text(item.raw.get("source_type", "") if isinstance(item.raw, dict) else "")
    if metadata_type:
        return metadata_type
    url = item.url.lower()
    source = f"{item.source_name} {item.source_category}".lower()
    if "linkedin.com/jobs" in url:
        return "LinkedIn_job"
    if "linkedin.com/posts" in url:
        return "LinkedIn_post"
    if any(host in url for host in ("ashbyhq.com", "greenhouse.io", "lever.co", "workable.com", "teamtailor.com")):
        return "ATS"
    if "career" in url or "jobs" in url:
        return "official_career_page"
    if "linkedin" in source:
        return "LinkedIn_post"
    if "vc" in source:
        return "VC_job_board"
    if "bing" in source or "search" in source:
        return "aggregator"
    return "job_board"


def _candidate_metadata(item: CandidateItem, key: str) -> str:
    if not isinstance(item.raw, dict):
        return ""
    return clean_text(item.raw.get(key, ""))


def _company_from_source_name(source_name: str) -> str:
    company = clean_text(source_name)
    replacements = (
        "FDE APAC",
        "Forward-Deployed Engineer",
        "Forward Deployed Engineer",
        "FDE Jobs",
        "FDE Job",
        "Careers",
        "Career",
        "Jobs",
        "Job",
        "All Page 2",
        "All",
        "Remote",
        "APAC",
    )
    for token in replacements:
        company = re.sub(rf"\b{re.escape(token)}\b", " ", company, flags=re.IGNORECASE)
    company = clean_text(company)
    return company or source_name


def _fallback_location(item: CandidateItem) -> str:
    text = f"{item.summary} {item.title}".lower()
    for location in (
        "Remote Vietnam",
        "Ho Chi Minh City",
        "Hanoi",
        "Vietnam",
        "Remote APAC",
        "Remote Asia",
        "Remote United States",
        "Remote Philippines",
        "Remote Singapore",
        "Singapore",
        "Philippines",
        "Japan",
        "India",
        "Australia",
        "Remote",
    ):
        if location.lower() in text:
            return location
    return ""


def _country_from_location(location: str) -> str:
    lowered = location.lower()
    country_terms = [
        ("Vietnam", ("vietnam", "viet nam", "ho chi minh", "hcmc", "hanoi", "saigon")),
        ("United States", ("united states", "usa", "u.s.")),
        ("Singapore", ("singapore",)),
        ("India", ("india", "bengaluru", "bangalore")),
        ("Malaysia", ("malaysia",)),
        ("Thailand", ("thailand",)),
        ("Indonesia", ("indonesia",)),
        ("Philippines", ("philippines",)),
        ("Hong Kong", ("hong kong",)),
        ("Taiwan", ("taiwan",)),
        ("Japan", ("japan",)),
        ("Korea", ("korea",)),
        ("Australia", ("australia",)),
    ]
    for country, terms in country_terms:
        if any(term in lowered for term in terms):
            return country
    return ""


def _fallback_job_verify_items(location: str, remote_policy: str) -> list[str]:
    items = ["Vietnam-based remote eligibility", "Apply link status"]
    combined = f"{location} {remote_policy}".lower()
    if "remote" in combined:
        items.append("APAC timezone expectations")
    if any(term in combined for term in ("singapore", "japan", "india", "australia", "philippines")):
        items.append("Work authorization or contractor/EOR path")
    return items


def _trim_for_prompt(text: str, max_chars: int) -> str:
    normalized = clean_text(text)
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened or normalized[:max_chars]


def _enum_value(value: object, allowed: set[str], default: str) -> str:
    cleaned = clean_text(value)
    return cleaned if cleaned in allowed else default


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if isinstance(value, str) and value.strip():
        return [clean_text(value)]
    return []


def _stable_job_id(raw_id: str, company: str, role_title: str, location: str, source_url: str) -> str:
    if raw_id:
        return _slug(raw_id)[:120]
    base = "-".join(part for part in (company, role_title, location) if part.strip())
    slug = _slug(base)
    if slug:
        return slug[:120]
    return _slug(source_url)[:120] or "job-opportunity"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", slug)


def _fallback_job_fit(item: CandidateItem) -> str:
    return _trim_for_prompt(item.summary or item.title, 240)
