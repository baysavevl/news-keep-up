from __future__ import annotations

from .job_search_policy import load_job_search_policy
from .models import CandidateItem, JobOpportunity


KNOWN_NON_VIETNAM_LOCATION_TERMS = (
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
    "latam",
    "latin america",
    "brazil",
    "portugal",
    "sweden",
)


def vietnam_workability_for_candidate(candidate: CandidateItem) -> str:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    return _vietnam_workability(
        location=str(raw.get("location") or ""),
        remote_policy=str(raw.get("remote_policy") or ""),
        text=" ".join(
            [candidate.title, candidate.summary, candidate.content, candidate.url]
        ),
        stated_eligibility="",
    )


def vietnam_workability_for_opportunity(opportunity: JobOpportunity) -> str:
    return _vietnam_workability(
        location=opportunity.location,
        remote_policy=opportunity.remote_policy,
        text=" ".join(
            [
                opportunity.role_title,
                opportunity.company,
                opportunity.source_url,
                opportunity.apply_url,
            ]
        ),
        stated_eligibility=opportunity.vietnam_eligibility,
    )


def _vietnam_workability(
    *,
    location: str,
    remote_policy: str,
    text: str,
    stated_eligibility: str,
) -> str:
    policy = load_job_search_policy()
    combined = " ".join([location, remote_policy, text]).lower()
    normalized_location = " ".join(location.lower().split())

    if any(term in combined for term in policy.explicit_remote_exclusions):
        return "no"
    if any(term in combined for term in policy.disallowed_employment_terms):
        return "no"
    if stated_eligibility in {"no", "unlikely"}:
        return "no"
    if stated_eligibility == "explicit_yes" or any(
        term in combined for term in policy.vietnam_terms
    ):
        return "explicit_yes"
    if any(term in combined for term in policy.relocation_terms):
        return "likely_possible"
    if any(term in combined for term in policy.regional_remote_terms):
        return "likely_possible"
    if stated_eligibility == "likely_possible":
        return "likely_possible"
    if any(term in normalized_location for term in KNOWN_NON_VIETNAM_LOCATION_TERMS):
        return "no"
    if (
        not location.strip()
        or "remote" in combined
        or stated_eligibility == "verify"
        or "verify" in normalized_location
    ):
        return "verify"
    return "no"


def is_workable_from_vietnam_candidate(candidate: CandidateItem) -> bool:
    return vietnam_workability_for_candidate(candidate) != "no"


def is_workable_from_vietnam_opportunity(opportunity: JobOpportunity) -> bool:
    return vietnam_workability_for_opportunity(opportunity) != "no"
