from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import CandidateItem


DEFAULT_JOB_SEARCH_POLICY_PATH = Path("config/job_search_policy.json")
EXPECTED_DECISIONS = ("APPLY_NOW", "VERIFY_FIRST", "DM_FIRST", "WATCH", "REJECT")


@dataclass(frozen=True)
class RoleFamilyPolicy:
    id: str
    label: str
    priority: int
    title_aliases: tuple[str, ...]
    technical_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    requires_technical_evidence: bool


@dataclass(frozen=True)
class JobSearchPolicy:
    version: int
    base_location: str
    decisions: tuple[str, ...]
    source_trust_order: tuple[str, ...]
    seniority_accept_terms: tuple[str, ...]
    seniority_reject_terms: tuple[str, ...]
    lead_management_terms: tuple[str, ...]
    domain_terms: tuple[str, ...]
    vietnam_terms: tuple[str, ...]
    regional_remote_terms: tuple[str, ...]
    relocation_terms: tuple[str, ...]
    explicit_remote_exclusions: tuple[str, ...]
    disallowed_employment_terms: tuple[str, ...]
    search_noise_terms: tuple[str, ...]
    offtopic_title_terms: tuple[str, ...]
    hidden_hiring_terms: tuple[str, ...]
    role_families: tuple[RoleFamilyPolicy, ...]


@dataclass(frozen=True)
class JobPolicyMatch:
    role_family_id: str = ""
    role_family_label: str = ""
    role_priority: int = 999
    technical_evidence: tuple[str, ...] = ()
    negative_evidence: tuple[str, ...] = ()
    domain_evidence: tuple[str, ...] = ()
    seniority: str = "unknown"
    hidden_hiring: bool = False
    reject_reason: str = ""

    @property
    def is_eligible(self) -> bool:
        return not self.reject_reason and bool(self.role_family_id)


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    values = tuple(str(item).strip() for item in value if str(item).strip())
    if not values:
        raise ValueError(f"{field} must contain at least one string")
    return values


def _role_family(raw: object) -> RoleFamilyPolicy:
    if not isinstance(raw, dict):
        raise ValueError("each role family must be an object")
    required = {
        "id",
        "label",
        "priority",
        "title_aliases",
        "technical_signals",
        "negative_signals",
        "requires_technical_evidence",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(f"missing role family keys: {', '.join(missing)}")
    priority = int(raw["priority"])
    if priority <= 0:
        raise ValueError("role family priority must be positive")
    role_id = str(raw["id"]).strip()
    label = str(raw["label"]).strip()
    if not role_id or not label:
        raise ValueError("role family id and label must not be empty")
    return RoleFamilyPolicy(
        id=role_id,
        label=label,
        priority=priority,
        title_aliases=_strings(raw["title_aliases"], f"{role_id}.title_aliases"),
        technical_signals=_strings(
            raw["technical_signals"], f"{role_id}.technical_signals"
        ),
        negative_signals=_strings(
            raw["negative_signals"], f"{role_id}.negative_signals"
        ),
        requires_technical_evidence=bool(raw["requires_technical_evidence"]),
    )


def load_job_search_policy(
    path: Path | str = DEFAULT_JOB_SEARCH_POLICY_PATH,
) -> JobSearchPolicy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "version",
        "base_location",
        "decisions",
        "source_trust_order",
        "seniority",
        "domain_terms",
        "location",
        "search_noise_terms",
        "offtopic_title_terms",
        "hidden_hiring_terms",
        "role_families",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(f"missing policy keys: {', '.join(missing)}")

    families = tuple(_role_family(row) for row in raw["role_families"])
    ids = [family.id for family in families]
    priorities = [family.priority for family in families]
    if len(ids) != len(set(ids)) or len(priorities) != len(set(priorities)):
        raise ValueError("role ids and priorities must be unique")

    decisions = _strings(raw["decisions"], "decisions")
    if decisions != EXPECTED_DECISIONS:
        raise ValueError(f"decisions must equal {EXPECTED_DECISIONS}")

    seniority = raw["seniority"]
    location = raw["location"]
    return JobSearchPolicy(
        version=int(raw["version"]),
        base_location=str(raw["base_location"]).strip(),
        decisions=decisions,
        source_trust_order=_strings(
            raw["source_trust_order"], "source_trust_order"
        ),
        seniority_accept_terms=_strings(
            seniority["accept_terms"], "seniority.accept_terms"
        ),
        seniority_reject_terms=_strings(
            seniority["reject_terms"], "seniority.reject_terms"
        ),
        lead_management_terms=_strings(
            seniority["lead_management_terms"], "seniority.lead_management_terms"
        ),
        domain_terms=_strings(raw["domain_terms"], "domain_terms"),
        vietnam_terms=_strings(location["vietnam_terms"], "location.vietnam_terms"),
        regional_remote_terms=_strings(
            location["regional_remote_terms"], "location.regional_remote_terms"
        ),
        relocation_terms=_strings(
            location["relocation_terms"], "location.relocation_terms"
        ),
        explicit_remote_exclusions=_strings(
            location["explicit_remote_exclusions"],
            "location.explicit_remote_exclusions",
        ),
        disallowed_employment_terms=_strings(
            location["disallowed_employment_terms"],
            "location.disallowed_employment_terms",
        ),
        search_noise_terms=_strings(raw["search_noise_terms"], "search_noise_terms"),
        offtopic_title_terms=_strings(
            raw["offtopic_title_terms"], "offtopic_title_terms"
        ),
        hidden_hiring_terms=_strings(
            raw["hidden_hiring_terms"], "hidden_hiring_terms"
        ),
        role_families=tuple(sorted(families, key=lambda family: family.priority)),
    )


def role_terms(policy: JobSearchPolicy | None = None) -> tuple[str, ...]:
    active = policy or load_job_search_policy()
    return tuple(
        dict.fromkeys(
            alias for family in active.role_families for alias in family.title_aliases
        )
    )


def domain_terms(policy: JobSearchPolicy | None = None) -> tuple[str, ...]:
    return (policy or load_job_search_policy()).domain_terms


def policy_prompt_fragment(policy: JobSearchPolicy | None = None) -> str:
    active = policy or load_job_search_policy()
    role_lines = []
    for family in active.role_families:
        role_lines.append(
            f"{family.priority}. {family.label}; "
            f"titles={', '.join(family.title_aliases)}; "
            f"technical evidence={', '.join(family.technical_signals)}; "
            f"negative signals={', '.join(family.negative_signals)}; "
            "technical evidence required="
            f"{str(family.requires_technical_evidence).lower()}"
        )
    return "\n".join(
        [
            f"Base location: {active.base_location}.",
            "No CV matching. Alert every valid opportunity.",
            "Role families:",
            *role_lines,
            f"Accepted domains: {', '.join(active.domain_terms)}.",
            f"Accepted seniority: {', '.join(active.seniority_accept_terms)}.",
            f"Rejected seniority: {', '.join(active.seniority_reject_terms)}.",
            "Never assume remote/APAC/SEA/global accepts Vietnam.",
            "Unknown but not explicitly incompatible evidence maps to VERIFY_FIRST.",
            f"Decisions: {', '.join(active.decisions)}.",
            "REJECT only for closed/expired, wrong role/domain/seniority, "
            "insufficient technical scope, or explicit Vietnam incompatibility "
            "without relocation.",
        ]
    )


def evaluate_job_text(
    title: str,
    body: str,
    policy: JobSearchPolicy | None = None,
) -> JobPolicyMatch:
    active = policy or load_job_search_policy()
    normalized_title = _normalize(title)
    combined = _normalize(f"{title} {body}")

    if _matches_any(combined, active.search_noise_terms):
        return JobPolicyMatch(reject_reason="search-noise")
    if _matches_any(normalized_title, active.offtopic_title_terms):
        return JobPolicyMatch(reject_reason="offtopic-title")
    if _matches_any(combined, active.disallowed_employment_terms):
        return JobPolicyMatch(reject_reason="disallowed-employment")

    family = _matching_family(normalized_title, combined, active)
    if family is None:
        return JobPolicyMatch(reject_reason="outside-role-scope")

    rejected_seniority = _matching_terms(
        normalized_title, active.seniority_reject_terms
    )
    tam_manager_exception = (
        family.id == "technical_account_management"
        and set(rejected_seniority).issubset({"manager"})
    )
    if rejected_seniority and not tam_manager_exception:
        return JobPolicyMatch(reject_reason="disallowed-seniority")
    if family.id == "technical_account_management" and _matches_any(
        combined, active.lead_management_terms
    ):
        return JobPolicyMatch(reject_reason="disallowed-seniority")
    if "lead" in normalized_title and _matches_any(
        combined, active.lead_management_terms
    ):
        return JobPolicyMatch(reject_reason="management-lead")

    domains = _matching_terms(combined, active.domain_terms)
    if not domains:
        return JobPolicyMatch(reject_reason="outside-domain-scope")

    technical = _matching_terms(combined, family.technical_signals)
    negative = _matching_terms(combined, family.negative_signals)
    if (family.requires_technical_evidence or negative) and not technical:
        return JobPolicyMatch(reject_reason="insufficient-technical-evidence")

    seniority = next(
        (
            term
            for term in active.seniority_accept_terms
            if _has_term(normalized_title, term)
        ),
        "unknown",
    )
    return JobPolicyMatch(
        role_family_id=family.id,
        role_family_label=family.label,
        role_priority=family.priority,
        technical_evidence=technical,
        negative_evidence=negative,
        domain_evidence=domains,
        seniority=seniority,
        hidden_hiring=_matches_any(combined, active.hidden_hiring_terms),
    )


def evaluate_job_candidate(
    candidate: CandidateItem,
    policy: JobSearchPolicy | None = None,
) -> JobPolicyMatch:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    body = " ".join(
        [
            candidate.summary,
            candidate.content,
            candidate.author,
            candidate.source_category,
            str(raw.get("company") or ""),
            str(raw.get("location") or ""),
            str(raw.get("remote_policy") or ""),
        ]
    )
    return evaluate_job_text(candidate.title, body, policy)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _has_term(text: str, term: str) -> bool:
    normalized = _normalize(term)
    if normalized.isalnum() and len(normalized) <= 3:
        return re.search(rf"\b{re.escape(normalized)}\b", text) is not None
    return normalized in text


def _matches_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_has_term(text, term) for term in terms)


def _matching_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if _has_term(text, term))


def _matching_family(
    normalized_title: str,
    combined: str,
    policy: JobSearchPolicy,
) -> RoleFamilyPolicy | None:
    for family in policy.role_families:
        if _matches_any(normalized_title, family.title_aliases):
            return family
    for family in policy.role_families:
        if _matches_any(combined, family.title_aliases):
            return family
    return None
