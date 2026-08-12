from __future__ import annotations

from urllib.parse import unquote, urlsplit

from .job_search_policy import load_job_search_policy
from .job_links import is_specific_job_opportunity
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
    "czechia",
    "prague",
    "praha",
    "europe",
    "emea",
    "north america",
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
    url_text = _url_path_text(candidate.canonical_url or candidate.url)
    return _vietnam_workability(
        location=str(raw.get("location") or ""),
        remote_policy=str(raw.get("remote_policy") or ""),
        country=str(raw.get("country") or ""),
        text=" ".join(
            [candidate.title, candidate.summary, candidate.content, url_text]
        ),
        geographic_text=" ".join([candidate.title, url_text]),
        stated_eligibility="",
    )


def vietnam_workability_for_opportunity(opportunity: JobOpportunity) -> str:
    url_text = _url_path_text(opportunity.apply_url or opportunity.source_url)
    return _vietnam_workability(
        location=opportunity.location,
        remote_policy=opportunity.remote_policy,
        country=opportunity.country,
        text=" ".join([opportunity.role_title, url_text]),
        geographic_text=" ".join([opportunity.role_title, url_text]),
        stated_eligibility=opportunity.vietnam_eligibility,
    )


def _vietnam_workability(
    *,
    location: str,
    remote_policy: str,
    country: str,
    text: str,
    geographic_text: str,
    stated_eligibility: str,
) -> str:
    policy = load_job_search_policy()
    combined = _normalize(" ".join([location, remote_policy, country, text]))
    positive_scope = _normalize(" ".join([location, remote_policy, country, text]))
    foreign_scope = _normalize(" ".join([location, country, geographic_text]))

    if any(term in combined for term in policy.explicit_remote_exclusions):
        return "no"
    if any(term in combined for term in policy.disallowed_employment_terms):
        return "no"
    if stated_eligibility in {"no", "unlikely"}:
        return "no"
    if any(term in positive_scope for term in policy.vietnam_terms):
        return "explicit_yes"
    if any(term in combined for term in policy.relocation_terms):
        return "verify"
    if any(term in foreign_scope for term in KNOWN_NON_VIETNAM_LOCATION_TERMS):
        return "no"
    if any(term in combined for term in policy.regional_remote_terms):
        return "likely_possible"
    if (
        not location.strip()
        or "remote" in combined
        or stated_eligibility == "verify"
        or "verify" in _normalize(location)
    ):
        return "verify"
    return "no"


def is_workable_from_vietnam_candidate(candidate: CandidateItem) -> bool:
    return vietnam_workability_for_candidate(candidate) != "no"


def is_workable_from_vietnam_opportunity(opportunity: JobOpportunity) -> bool:
    return vietnam_workability_for_opportunity(opportunity) != "no"


def has_confident_remote_scope_candidate(candidate: CandidateItem) -> bool:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    return _has_confident_remote_scope(
        " ".join(
            [
                str(raw.get("location") or ""),
                str(raw.get("remote_policy") or ""),
                str(raw.get("country") or ""),
                candidate.title,
                candidate.summary,
                candidate.content,
                _url_path_text(candidate.canonical_url or candidate.url),
            ]
        )
    )


def has_confident_remote_scope_opportunity(opportunity: JobOpportunity) -> bool:
    return _has_confident_remote_scope(
        " ".join(
            [
                opportunity.location,
                opportunity.remote_policy,
                opportunity.country,
                opportunity.role_title,
                _url_path_text(opportunity.apply_url or opportunity.source_url),
            ]
        )
    )


def is_auto_alertable_from_vietnam_opportunity(
    opportunity: JobOpportunity,
) -> bool:
    workability = vietnam_workability_for_opportunity(opportunity)
    return (
        is_specific_job_opportunity(opportunity)
        and opportunity.status != "closed"
        and opportunity.evidence_type.lower() != "weak"
        and (
            workability == "explicit_yes"
            or (
                workability == "likely_possible"
                and has_confident_remote_scope_opportunity(opportunity)
            )
        )
    )


def is_manual_verification_opportunity(opportunity: JobOpportunity) -> bool:
    return (
        is_specific_job_opportunity(opportunity)
        and opportunity.status != "closed"
        and vietnam_workability_for_opportunity(opportunity) == "verify"
    )


def _has_confident_remote_scope(text: str) -> bool:
    normalized = _normalize(text)
    policy = load_job_search_policy()
    if any(term in normalized for term in policy.explicit_remote_exclusions):
        return False
    return any(term in normalized for term in policy.regional_remote_terms)


def _url_path_text(url: str) -> str:
    try:
        path = unquote(urlsplit(str(url or "")).path)
    except ValueError:
        return ""
    return path.replace("-", " ").replace("_", " ").replace("/", " ")


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())
