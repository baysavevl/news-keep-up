from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

from .models import CandidateItem, JobOpportunity


_COLLECTION_SEGMENTS = {
    "career",
    "careers",
    "job",
    "jobs",
    "opening",
    "openings",
    "opportunities",
    "position",
    "positions",
    "remote-jobs",
    "search",
    "vacancies",
    "vacancy",
}

_DETAIL_PARENT_SEGMENTS = _COLLECTION_SEGMENTS | {
    "j",
    "job-detail",
    "job-details",
    "job-openings",
    "o",
    "view",
}

_DIRECT_ATS_HOST_TERMS = (
    "ashbyhq.com",
    "bamboohr.com",
    "greenhouse.io",
    "jobs.lever.co",
    "jobs.smartrecruiters.com",
    "jobs.workable.com",
    "myworkdayjobs.com",
    "recruitee.com",
    "rippling-ats.com",
    "teamtailor.com",
)


def is_specific_job_url(url: str, source_type: str = "") -> bool:
    """Return whether *url* identifies a vacancy or a specific hiring post."""

    try:
        parsed = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    host = parsed.hostname.lower() if parsed.hostname else ""
    segments = [
        unquote(segment).strip().lower()
        for segment in parsed.path.split("/")
        if unquote(segment).strip()
    ]
    if not segments:
        return False

    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return _is_specific_linkedin_path(segments)

    if segments[-1] in _COLLECTION_SEGMENTS:
        return False

    if segments[-1] == "viewjob":
        return bool(parse_qs(parsed.query).get("jk"))

    if _has_detail_path(segments):
        return True

    if any(term in host for term in _DIRECT_ATS_HOST_TERMS):
        return _has_direct_ats_path(host, segments)

    normalized_source_type = str(source_type or "").strip().lower()
    if normalized_source_type in {"linkedin_job", "linkedin_post"}:
        return False
    return False


def is_specific_job_candidate(candidate: CandidateItem) -> bool:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    return is_specific_job_url(
        candidate.canonical_url or candidate.url,
        str(raw.get("source_type") or candidate.source_category),
    )


def is_specific_job_opportunity(opportunity: JobOpportunity) -> bool:
    return is_specific_job_url(
        opportunity.apply_url or opportunity.source_url,
        opportunity.source_type,
    )


def _is_specific_linkedin_path(segments: list[str]) -> bool:
    if len(segments) >= 3 and segments[:2] == ["jobs", "view"]:
        return True
    if len(segments) >= 2 and segments[0] == "posts":
        return True
    return len(segments) >= 3 and segments[:2] == ["feed", "update"]


def _has_detail_path(segments: list[str]) -> bool:
    for index, segment in enumerate(segments[:-1]):
        if segment not in _DETAIL_PARENT_SEGMENTS:
            continue
        child = segments[index + 1]
        if child and child not in _COLLECTION_SEGMENTS:
            return True
    return False


def _has_direct_ats_path(host: str, segments: list[str]) -> bool:
    if "ashbyhq.com" in host or "jobs.lever.co" in host:
        return len(segments) >= 2
    if "recruitee.com" in host:
        return len(segments) >= 2 and "o" in segments[:-1]
    if "myworkdayjobs.com" in host:
        return "job" in segments[:-1]
    return _has_detail_path(segments)
