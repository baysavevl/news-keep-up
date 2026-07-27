from __future__ import annotations

from .models import CandidateItem, JobOpportunity

VIETNAM_TERMS = (
    "vietnam",
    "viet nam",
    "ho chi minh",
    "hcmc",
    "saigon",
    "hanoi",
)

REMOTE_SCOPE_TERMS = (
    "remote apac",
    "remote asia",
    "remote southeast asia",
    "remote south east asia",
    "remote asean",
    "global remote",
    "remote global",
    "worldwide",
    "anywhere",
)

NON_VIETNAM_LOCATION_TERMS = (
    "united states",
    "usa",
    "u.s.",
    "india",
    "japan",
    "korea",
    "australia",
    "germany",
    "france",
    "serbia",
    "poland",
    "czech",
    "europe",
    "emea",
    "canada",
    "united kingdom",
    "uk",
    "singapore",
    "philippines",
    "malaysia",
    "thailand",
    "indonesia",
    "hong kong",
    "taiwan",
)

NON_FULL_TIME_TERMS = (
    "part-time",
    "part time",
    "internship",
    "intern ",
    "temporary",
)

NON_TECHNICAL_ROLE_TERMS = (
    "designer",
    "creative",
    "ads",
    "account executive",
    "sales representative",
    "marketing",
)


def is_workable_from_vietnam_candidate(candidate: CandidateItem) -> bool:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    return _is_workable_from_vietnam(
        location=str(raw.get("location") or ""),
        remote_policy=str(raw.get("remote_policy") or ""),
        text=" ".join([
            candidate.title,
            candidate.summary,
            candidate.content,
            candidate.url,
        ]),
        vietnam_eligibility="",
    )


def is_workable_from_vietnam_opportunity(opportunity: JobOpportunity) -> bool:
    return _is_workable_from_vietnam(
        location=opportunity.location,
        remote_policy=opportunity.remote_policy,
        text=" ".join([
            opportunity.role_title,
            opportunity.company,
            opportunity.why_it_fits,
            opportunity.source_url,
            opportunity.apply_url,
        ]),
        vietnam_eligibility=opportunity.vietnam_eligibility,
    )


def _is_workable_from_vietnam(
    *,
    location: str,
    remote_policy: str,
    text: str,
    vietnam_eligibility: str,
) -> bool:
    combined = " ".join([location, remote_policy, text]).lower()
    location_text = location.lower()
    remote_text = " ".join([location, remote_policy]).lower()

    if any(term in combined for term in NON_TECHNICAL_ROLE_TERMS):
        return False

    if any(term in combined for term in NON_FULL_TIME_TERMS):
        return False

    if vietnam_eligibility == "explicit_yes":
        return True
    if any(term in combined for term in VIETNAM_TERMS):
        return True

    has_remote_or_hybrid = "remote" in remote_text or "hybrid" in remote_text
    if not has_remote_or_hybrid:
        return False

    if any(term in combined for term in REMOTE_SCOPE_TERMS):
        return True

    if _remote_scope_is_unspecified(location_text, remote_policy.lower()):
        return True

    if any(term in location_text for term in NON_VIETNAM_LOCATION_TERMS):
        return False

    return False


def _remote_scope_is_unspecified(location: str, remote_policy: str) -> bool:
    normalized_location = " ".join(location.split())
    normalized_policy = " ".join(remote_policy.split())
    return normalized_location in {"", "remote", "hybrid"} or (
        normalized_policy in {"remote", "hybrid"} and not normalized_location
    )
