from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


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
