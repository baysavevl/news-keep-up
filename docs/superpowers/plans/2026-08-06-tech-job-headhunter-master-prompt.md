# Technical Job Headhunter Master Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone technical-headhunter master prompt and make the existing fde-jobs pipeline use the same policy for FDE, Solutions Engineering/Architecture, AI Consulting, Technical Presales, and Technical Account Management opportunities.

**Architecture:** A versioned JSON policy becomes the single machine-readable source for role aliases, technical gates, seniority, domains, location evidence, decisions, and source trust. A focused Python policy module validates and evaluates candidates; Gemini, local fallback, source discovery, database ordering, and Telegram formatting consume its results while retaining the current JobOpportunity schema and fde-jobs endpoints.

**Tech Stack:** Python 3.11+, standard-library dataclasses/json/re/pathlib, unittest, SQLite/Turso through the existing DB abstraction, Gemini REST, Telegram Bot API, and JSON-configured RSS/HTML/API sources.

## Global Constraints

- Do not add a runtime dependency or database migration.
- Keep fde-jobs, fde-job-sources, scheduler slots, Telegram commands, Vercel endpoints, and existing environment variables backward compatible.
- FDE ranks first; the other four approved role families remain alertable.
- Accept Mid, Senior, Staff, and hands-on Lead individual contributors.
- Reject explicit Intern, Graduate, Entry-level, Junior, Manager, Director, Head, and Executive roles.
- Accept AI/GenAI/agent/LLM/RAG/enterprise automation and enterprise SaaS domains.
- Technical Presales, AI Consulting, and Technical Account Management require direct technical evidence.
- Do not ask for or score against a CV.
- Every non-rejected opportunity is queued; priority changes order only.
- Preserve the three-alert-per-scan flood-control limit and leave remaining alerts pending.
- Unknown but not explicitly incompatible location or seniority becomes VERIFY_FIRST.
- Never infer Vietnam eligibility, status, dates, compensation, benefits, or contacts without source evidence.
- Do not auto-apply or contact anyone.
- Continue without one failed source and fall back locally when Gemini fails.
- Use unittest and test-first implementation for every task.
- Before a Vercel deploy, upgrade the local CLI from 58.5.1 with npm i -g vercel@latest or pnpm add -g vercel@latest; the upgrade is an operator step, not a repository change.

---

## File Structure

- Create config/job_search_policy.json: versioned source of truth for job-search scope and evidence rules.
- Create news_keep_up/job_search_policy.py: policy dataclasses, validation, deterministic matching, flattened prompt/source terms, and policy prompt rendering.
- Create tests/test_job_search_policy.py: isolated policy-loading and matching tests.
- Create docs/prompts/tech-job-headhunter-master-prompt.md: standalone browsing-agent prompt.
- Modify news_keep_up/job_alerts.py: policy-backed prefilter, candidate ranking, action labels, and Telegram format.
- Modify news_keep_up/job_filters.py: evidence-based Vietnam/remote/relocation workability with unknown-as-verify behavior.
- Modify news_keep_up/gemini.py: compact shared-policy prompt, response mapping, deterministic post-validation, and policy-backed fallback.
- Modify news_keep_up/source_intelligence.py: shared role/domain signals for source discovery.
- Modify news_keep_up/models.py: normalized material-change alert fingerprint without changing stored columns.
- Modify news_keep_up/db.py: action/role-aware pending ordering and material-update-safe URL deduplication.
- Modify config/fde_job_sources.json: focused AI Consultant and enterprise SaaS searches.
- Modify config/fde_job_source_discovery_sources.json: discovery searches for the new approved scope.
- Modify tests/test_job_alerts.py, tests/test_gemini.py, tests/test_source_intelligence.py, tests/test_db.py, and tests/test_config.py: regression and new-scope coverage.
- Modify README.md: explain the shared policy, standalone prompt, role families, and decisions.

---

### Task 1: Add and Validate the Shared Job Search Policy

**Files:**
- Create: config/job_search_policy.json
- Create: news_keep_up/job_search_policy.py
- Create: tests/test_job_search_policy.py

**Interfaces:**
- Produces: RoleFamilyPolicy
- Produces: JobSearchPolicy
- Produces: load_job_search_policy(path: Path | str = DEFAULT_JOB_SEARCH_POLICY_PATH) -> JobSearchPolicy
- Produces: role_terms(policy: JobSearchPolicy | None = None) -> tuple[str, ...]
- Produces: domain_terms(policy: JobSearchPolicy | None = None) -> tuple[str, ...]

- [ ] **Step 1: Write failing policy-load and validation tests.**

~~~python
import json
import tempfile
import unittest
from pathlib import Path

from news_keep_up.job_search_policy import load_job_search_policy


class JobSearchPolicyTest(unittest.TestCase):
    def test_default_policy_has_approved_role_order_and_decisions(self):
        policy = load_job_search_policy()

        self.assertEqual(
            [family.id for family in policy.role_families],
            [
                "forward_deployed_engineering",
                "solutions_engineering_architecture",
                "ai_consulting",
                "technical_presales",
                "technical_account_management",
            ],
        )
        self.assertEqual(
            policy.decisions,
            ("APPLY_NOW", "VERIFY_FIRST", "DM_FIRST", "WATCH", "REJECT"),
        )
        self.assertIn("enterprise saas", policy.domain_terms)
        self.assertEqual(policy.base_location, "Ho Chi Minh City, Vietnam")

    def test_policy_rejects_missing_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-policy.json"
            path.write_text(json.dumps({"version": 1}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing policy keys"):
                load_job_search_policy(path)

    def test_policy_rejects_duplicate_role_ids_and_priorities(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = json.loads(Path("config/job_search_policy.json").read_text(encoding="utf-8"))
            raw["role_families"][1]["id"] = raw["role_families"][0]["id"]
            raw["role_families"][1]["priority"] = raw["role_families"][0]["priority"]
            path = Path(tmp) / "duplicate-policy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unique"):
                load_job_search_policy(path)
~~~

- [ ] **Step 2: Run the new test and verify it fails before the module exists.**

Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
~~~

Expected: FAIL with ModuleNotFoundError for news_keep_up.job_search_policy.

- [ ] **Step 3: Create the versioned JSON policy with all approved values.**

Create config/job_search_policy.json with this exact top-level structure and five role objects:

~~~json
{
  "version": 1,
  "base_location": "Ho Chi Minh City, Vietnam",
  "decisions": [
    "APPLY_NOW",
    "VERIFY_FIRST",
    "DM_FIRST",
    "WATCH",
    "REJECT"
  ],
  "source_trust_order": [
    "official_career_page",
    "ATS",
    "LinkedIn_job",
    "LinkedIn_post",
    "company_blog",
    "job_board",
    "community",
    "aggregator"
  ],
  "seniority": {
    "accept_terms": [
      "mid-level",
      "mid level",
      "senior",
      "sr.",
      "staff",
      "lead"
    ],
    "reject_terms": [
      "intern",
      "internship",
      "graduate",
      "entry-level",
      "entry level",
      "junior",
      "manager",
      "director",
      "head of",
      "vice president",
      "vp ",
      "chief "
    ],
    "lead_management_terms": [
      "people manager",
      "manage a team",
      "direct reports",
      "hiring and performance management"
    ]
  },
  "domain_terms": [
    "ai",
    "artificial intelligence",
    "enterprise ai",
    "generative ai",
    "genai",
    "ai agent",
    "agentic ai",
    "llm",
    "rag",
    "machine learning",
    "enterprise automation",
    "workflow automation",
    "enterprise saas",
    "b2b saas",
    "enterprise software",
    "saas platform",
    "enterprise platform"
  ],
  "location": {
    "vietnam_terms": [
      "vietnam",
      "viet nam",
      "ho chi minh",
      "hcmc",
      "saigon",
      "hanoi"
    ],
    "regional_remote_terms": [
      "remote apac",
      "remote asia",
      "remote southeast asia",
      "remote south east asia",
      "remote asean",
      "global remote",
      "remote global",
      "worldwide",
      "anywhere"
    ],
    "relocation_terms": [
      "relocation",
      "relocation assistance",
      "visa sponsorship",
      "work visa",
      "sponsor visa",
      "mobility package"
    ],
    "explicit_remote_exclusions": [
      "remote us",
      "remote-us",
      "remote usa",
      "remote united states",
      "us only",
      "united states only",
      "remote canada",
      "canada only",
      "remote emea",
      "emea only",
      "remote europe",
      "europe only"
    ],
    "disallowed_employment_terms": [
      "part-time",
      "part time",
      "temporary"
    ]
  },
  "search_noise_terms": [
    "dictionary",
    "wikipedia",
    "cambridge dictionary",
    "translation",
    "stock price",
    "course syllabus"
  ],
  "offtopic_title_terms": [
    "account executive",
    "sales representative",
    "marketing manager",
    "designer",
    "creative director",
    "backend engineer",
    "frontend engineer",
    "full stack engineer",
    "devops engineer",
    "site reliability engineer",
    "mobile engineer",
    "data engineer",
    "qa engineer"
  ],
  "hidden_hiring_terms": [
    "we are hiring",
    "we're hiring",
    "hiring",
    "join our team",
    "dm me",
    "reach out",
    "building the team",
    "expanding our team"
  ],
  "role_families": [
    {
      "id": "forward_deployed_engineering",
      "label": "Forward Deployed Engineering",
      "priority": 1,
      "title_aliases": [
        "forward deployed engineer",
        "forward-deployed engineer",
        "forward deployment engineer",
        "deployed engineer",
        "deployment strategist",
        "ai deployment engineer",
        "fde"
      ],
      "technical_signals": [
        "customer deployment",
        "implementation",
        "integration",
        "production rollout",
        "solution design",
        "technical discovery",
        "api"
      ],
      "negative_signals": [
        "forward deployed designer",
        "creative ads"
      ],
      "requires_technical_evidence": false
    },
    {
      "id": "solutions_engineering_architecture",
      "label": "Solutions Engineering and Architecture",
      "priority": 2,
      "title_aliases": [
        "solution engineer",
        "solutions engineer",
        "customer engineer",
        "field engineer",
        "solution architect",
        "solutions architect",
        "customer success architect",
        "delivery solutions architect"
      ],
      "technical_signals": [
        "demo",
        "proof of concept",
        "poc",
        "architecture",
        "system design",
        "api",
        "integration",
        "troubleshooting",
        "technical discovery",
        "implementation",
        "deployment"
      ],
      "negative_signals": [
        "cold calling",
        "pipeline generation",
        "customer service only"
      ],
      "requires_technical_evidence": false
    },
    {
      "id": "ai_consulting",
      "label": "AI Consulting",
      "priority": 3,
      "title_aliases": [
        "ai consultant",
        "genai consultant",
        "technical consultant",
        "implementation consultant",
        "ai implementation specialist",
        "ai automation specialist",
        "freelance"
      ],
      "technical_signals": [
        "ai implementation",
        "workflow design",
        "llm",
        "rag",
        "ai agent",
        "architecture",
        "integration",
        "productionize",
        "build",
        "implement"
      ],
      "negative_signals": [
        "strategy only",
        "management consulting",
        "market research"
      ],
      "requires_technical_evidence": true
    },
    {
      "id": "technical_presales",
      "label": "Technical Presales",
      "priority": 4,
      "title_aliases": [
        "presales engineer",
        "pre-sales engineer",
        "sales engineer",
        "solutions consultant",
        "solution consultant"
      ],
      "technical_signals": [
        "demo",
        "proof of concept",
        "poc",
        "solutioning",
        "technical discovery",
        "api",
        "integration",
        "architecture",
        "security review"
      ],
      "negative_signals": [
        "cold calling",
        "prospecting",
        "quota carrying",
        "pipeline ownership",
        "renewals"
      ],
      "requires_technical_evidence": true
    },
    {
      "id": "technical_account_management",
      "label": "Technical Account Management",
      "priority": 5,
      "title_aliases": [
        "technical account manager",
        "technical success manager",
        "customer success engineer"
      ],
      "technical_signals": [
        "technical adoption",
        "troubleshooting",
        "architecture",
        "api",
        "integration",
        "incident escalation",
        "implementation guidance"
      ],
      "negative_signals": [
        "renewals",
        "upsell",
        "relationship management",
        "quota carrying"
      ],
      "requires_technical_evidence": true
    }
  ]
}
~~~

- [ ] **Step 4: Implement dataclasses and strict loader validation.**

Implement the loader with these public shapes:

~~~python
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
        source_trust_order=_strings(raw["source_trust_order"], "source_trust_order"),
        seniority_accept_terms=_strings(seniority["accept_terms"], "seniority.accept_terms"),
        seniority_reject_terms=_strings(seniority["reject_terms"], "seniority.reject_terms"),
        lead_management_terms=_strings(seniority["lead_management_terms"], "seniority.lead_management_terms"),
        domain_terms=_strings(raw["domain_terms"], "domain_terms"),
        vietnam_terms=_strings(location["vietnam_terms"], "location.vietnam_terms"),
        regional_remote_terms=_strings(location["regional_remote_terms"], "location.regional_remote_terms"),
        relocation_terms=_strings(location["relocation_terms"], "location.relocation_terms"),
        explicit_remote_exclusions=_strings(
            location["explicit_remote_exclusions"],
            "location.explicit_remote_exclusions",
        ),
        disallowed_employment_terms=_strings(
            location["disallowed_employment_terms"],
            "location.disallowed_employment_terms",
        ),
        search_noise_terms=_strings(raw["search_noise_terms"], "search_noise_terms"),
        offtopic_title_terms=_strings(raw["offtopic_title_terms"], "offtopic_title_terms"),
        hidden_hiring_terms=_strings(raw["hidden_hiring_terms"], "hidden_hiring_terms"),
        role_families=tuple(sorted(families, key=lambda family: family.priority)),
    )


def role_terms(policy: JobSearchPolicy | None = None) -> tuple[str, ...]:
    active = policy or load_job_search_policy()
    return tuple(dict.fromkeys(
        alias for family in active.role_families for alias in family.title_aliases
    ))


def domain_terms(policy: JobSearchPolicy | None = None) -> tuple[str, ...]:
    return (policy or load_job_search_policy()).domain_terms
~~~

Use these validation helpers so malformed policy files fail with a field-specific error:

~~~python
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
        technical_signals=_strings(raw["technical_signals"], f"{role_id}.technical_signals"),
        negative_signals=_strings(raw["negative_signals"], f"{role_id}.negative_signals"),
        requires_technical_evidence=bool(raw["requires_technical_evidence"]),
    )
~~~

- [ ] **Step 5: Run the policy test and the existing config test.**

Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
python3 -m unittest discover -s tests -p 'test_config.py' -v
~~~

Expected: both commands PASS.

- [ ] **Step 6: Commit the policy foundation.**

~~~bash
git add config/job_search_policy.json news_keep_up/job_search_policy.py tests/test_job_search_policy.py
git diff --cached --check
git commit -m "feat(jobs): add shared search policy"
~~~

---

### Task 2: Add Deterministic Role, Technical, Seniority, Domain, and Location Evaluation

**Files:**
- Modify: news_keep_up/job_search_policy.py
- Modify: news_keep_up/job_alerts.py:40-196,334-478
- Modify: news_keep_up/job_filters.py:1-171
- Modify: tests/test_job_search_policy.py
- Modify: tests/test_job_alerts.py:88-386

**Interfaces:**
- Consumes: JobSearchPolicy and RoleFamilyPolicy from Task 1.
- Produces: JobPolicyMatch
- Produces: evaluate_job_text(title: str, body: str, policy: JobSearchPolicy | None = None) -> JobPolicyMatch
- Produces: evaluate_job_candidate(candidate: CandidateItem, policy: JobSearchPolicy | None = None) -> JobPolicyMatch
- Produces: is_target_job_candidate(candidate: CandidateItem) -> bool
- Preserves: is_fde_job_candidate(candidate: CandidateItem) -> bool as a compatibility wrapper.
- Produces: vietnam_workability_for_candidate(candidate: CandidateItem) -> str
- Produces: vietnam_workability_for_opportunity(opportunity: JobOpportunity) -> str
- Preserves: is_workable_from_vietnam_candidate and is_workable_from_vietnam_opportunity.

- [ ] **Step 1: Add failing matcher and workability tests.**

Add tests with these exact expectations:

~~~python
from news_keep_up.job_search_policy import evaluate_job_text


def test_all_approved_role_families_match():
    cases = {
        "Senior Forward Deployed Engineer": "Forward Deployed Engineering",
        "Staff Solutions Architect": "Solutions Engineering and Architecture",
        "Senior AI Implementation Consultant": "AI Consulting",
        "Lead Presales Engineer": "Technical Presales",
        "Senior Technical Account Manager": "Technical Account Management",
    }
    for title, expected in cases.items():
        match = evaluate_job_text(
            title,
            "Enterprise SaaS customer work with architecture, API integration, demo, PoC, "
            "implementation guidance, troubleshooting, and production deployment.",
        )
        assert match.is_eligible, match.reject_reason
        assert match.role_family_label == expected


def test_pure_quota_presales_and_tam_are_rejected_without_technical_evidence():
    presales = evaluate_job_text(
        "Senior Presales Engineer",
        "Enterprise SaaS quota carrying, cold calling, prospecting, and pipeline ownership.",
    )
    tam = evaluate_job_text(
        "Technical Account Manager",
        "Enterprise SaaS renewals, upsell, relationship management, and quota carrying.",
    )
    assert presales.reject_reason == "insufficient-technical-evidence"
    assert tam.reject_reason == "insufficient-technical-evidence"


def test_unknown_seniority_is_verify_not_reject():
    match = evaluate_job_text(
        "Solutions Engineer",
        "Enterprise SaaS architecture, demo, API integration, and customer implementation.",
    )
    assert match.is_eligible
    assert match.seniority == "unknown"


def test_junior_manager_and_non_target_engineering_roles_are_rejected():
    assert evaluate_job_text(
        "Junior Solutions Engineer",
        "Enterprise SaaS API integration and demos.",
    ).reject_reason == "disallowed-seniority"
    assert evaluate_job_text(
        "Solutions Engineering Manager",
        "Enterprise SaaS API integration and demos.",
    ).reject_reason == "disallowed-seniority"
    assert evaluate_job_text(
        "Senior Backend Engineer",
        "Enterprise AI platform APIs.",
    ).reject_reason == "offtopic-title"
~~~

Add location tests to tests/test_job_alerts.py:

~~~python
def test_workability_accepts_unknown_as_verify_and_apac_relocation():
    unknown = CandidateItem(
        source_name="Company Careers",
        source_kind="html",
        source_category="job-board",
        title="Senior Solutions Engineer",
        url="https://example.com/jobs/se",
        canonical_url="https://example.com/jobs/se",
        summary="Enterprise SaaS architecture and API integration.",
    )
    relocation = CandidateItem(
        source_name="Company Careers",
        source_kind="html",
        source_category="job-board",
        title="Staff Solution Architect",
        url="https://example.com/jobs/sa-singapore",
        canonical_url="https://example.com/jobs/sa-singapore",
        summary="Onsite Singapore with visa sponsorship and relocation assistance.",
        raw={"location": "Singapore", "remote_policy": "Onsite"},
    )
    self.assertEqual(vietnam_workability_for_candidate(unknown), "verify")
    self.assertEqual(vietnam_workability_for_candidate(relocation), "likely_possible")
    self.assertTrue(is_workable_from_vietnam_candidate(unknown))
    self.assertTrue(is_workable_from_vietnam_candidate(relocation))
~~~

Update the existing remote ML test to use the in-scope title Senior AI Solutions Engineer. Change the old unknown-location rejection test to expect VERIFY_FIRST-compatible workability. Replace the two “workability rejects nontechnical role” tests with is_target_job_candidate or evaluate_job_candidate assertions because technical scope no longer belongs to job_filters.py. Keep explicit Remote-US and onsite-non-Vietnam-without-relocation tests as rejections.

- [ ] **Step 2: Run the focused tests and verify the new assertions fail.**

~~~bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
~~~

Expected: FAIL because JobPolicyMatch, evaluate_job_text, is_target_job_candidate, and workability status functions do not exist.

- [ ] **Step 3: Implement the deterministic policy match.**

Add this data contract and evaluation flow:

~~~python
import re
from dataclasses import dataclass

from .models import CandidateItem


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

    rejected_seniority = _matching_terms(normalized_title, active.seniority_reject_terms)
    tam_manager_exception = (
        family.id == "technical_account_management"
        and set(rejected_seniority).issubset({"manager"})
    )
    if rejected_seniority and not tam_manager_exception:
        return JobPolicyMatch(reject_reason="disallowed-seniority")
    if (
        family.id == "technical_account_management"
        and _matches_any(combined, active.lead_management_terms)
    ):
        return JobPolicyMatch(reject_reason="disallowed-seniority")
    if "lead" in normalized_title and _matches_any(combined, active.lead_management_terms):
        return JobPolicyMatch(reject_reason="management-lead")

    domains = _matching_terms(combined, active.domain_terms)
    if not domains:
        return JobPolicyMatch(reject_reason="outside-domain-scope")

    technical = _matching_terms(combined, family.technical_signals)
    negative = _matching_terms(combined, family.negative_signals)
    if (family.requires_technical_evidence or negative) and not technical:
        return JobPolicyMatch(reject_reason="insufficient-technical-evidence")

    seniority = next(
        (term for term in active.seniority_accept_terms if _has_term(normalized_title, term)),
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
    body = " ".join([
        candidate.summary,
        candidate.content,
        candidate.author,
        candidate.source_category,
        str(raw.get("company") or ""),
        str(raw.get("location") or ""),
        str(raw.get("remote_policy") or ""),
    ])
    return evaluate_job_text(candidate.title, body, policy)


def _has_term(text: str, term: str) -> bool:
    normalized = _normalize(term)
    if normalized.isalnum() and len(normalized) <= 3:
        return re.search(rf"\b{re.escape(normalized)}\b", text) is not None
    return normalized in text
~~~

Use these deterministic helpers. Family matching checks the title before the combined evidence, so a hidden-hiring post titled “We are hiring” can still map from its body while an explicit title wins:

~~~python
def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())


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
~~~

- [ ] **Step 4: Replace the job prefilter constants with the shared evaluator.**

In news_keep_up/job_alerts.py:

~~~python
def is_target_job_candidate(candidate: CandidateItem) -> bool:
    return evaluate_job_candidate(candidate).is_eligible


def is_fde_job_candidate(candidate: CandidateItem) -> bool:
    return is_target_job_candidate(candidate)


def _job_candidate_score(candidate: CandidateItem) -> int:
    match = evaluate_job_candidate(candidate)
    if not match.is_eligible:
        return -1000
    text = " ".join([candidate.title, candidate.summary, candidate.content]).lower()
    score = 140 - (match.role_priority * 15)
    score += min(30, len(match.technical_evidence) * 5)
    score += min(20, len(match.domain_evidence) * 5)
    if any(term in text for term in ("vietnam", "ho chi minh", "hanoi", "remote vietnam")):
        score += 60
    elif any(term in text for term in ("apac", "southeast asia", "asean", "remote")):
        score += 30
    return score
~~~

Remove JOB_TITLE_TERMS and JOB_DOMAIN_TERMS after all callers use the policy. Preserve freelance source handling only through the AI Consulting “freelance” alias plus domain and technical evidence, so a generic freelance listing does not bypass the shared policy.

- [ ] **Step 5: Make location evidence return explicit_yes, likely_possible, verify, or no.**

In news_keep_up/job_filters.py, load the shared policy and make explicit exclusions win before ambiguous evidence:

~~~python
def vietnam_workability_for_candidate(candidate: CandidateItem) -> str:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    return _vietnam_workability(
        location=str(raw.get("location") or ""),
        remote_policy=str(raw.get("remote_policy") or ""),
        text=" ".join([candidate.title, candidate.summary, candidate.content, candidate.url]),
        stated_eligibility="",
    )


def vietnam_workability_for_opportunity(opportunity: JobOpportunity) -> str:
    return _vietnam_workability(
        location=opportunity.location,
        remote_policy=opportunity.remote_policy,
        text=" ".join([opportunity.role_title, opportunity.company, opportunity.source_url]),
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
    if any(term in combined for term in policy.explicit_remote_exclusions):
        return "no"
    if any(term in combined for term in policy.disallowed_employment_terms):
        return "no"
    if stated_eligibility in {"no", "unlikely"}:
        return "no"
    if stated_eligibility == "explicit_yes" or any(term in combined for term in policy.vietnam_terms):
        return "explicit_yes"
    if any(term in combined for term in policy.relocation_terms):
        return "likely_possible"
    if any(term in combined for term in policy.regional_remote_terms):
        return "likely_possible"
    if stated_eligibility == "likely_possible":
        return "likely_possible"
    if not location.strip() or "remote" in combined or stated_eligibility == "verify":
        return "verify"
    return "no"


def is_workable_from_vietnam_candidate(candidate: CandidateItem) -> bool:
    return vietnam_workability_for_candidate(candidate) != "no"


def is_workable_from_vietnam_opportunity(opportunity: JobOpportunity) -> bool:
    return vietnam_workability_for_opportunity(opportunity) != "no"
~~~

Remove technical-role filtering from job_filters.py; job_search_policy.py owns that concern.

- [ ] **Step 6: Run focused and adjacent regression tests.**

~~~bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_telegram_commands.py' -v
~~~

Expected: all commands PASS.

- [ ] **Step 7: Commit the deterministic evaluator.**

~~~bash
git add news_keep_up/job_search_policy.py news_keep_up/job_alerts.py news_keep_up/job_filters.py tests/test_job_search_policy.py tests/test_job_alerts.py
git diff --cached --check
git commit -m "feat(jobs): centralize target matching"
~~~

---

### Task 3: Create the Standalone Master Prompt and Shared Prompt Fragment

**Files:**
- Create: docs/prompts/tech-job-headhunter-master-prompt.md
- Modify: news_keep_up/job_search_policy.py
- Modify: tests/test_job_search_policy.py

**Interfaces:**
- Consumes: JobSearchPolicy from Task 1.
- Produces: policy_prompt_fragment(policy: JobSearchPolicy | None = None) -> str
- Produces: a copy-paste browsing prompt with no unresolved template tokens.

- [ ] **Step 1: Write failing prompt-alignment tests.**

~~~python
def test_standalone_prompt_matches_policy_and_has_no_template_tokens():
    policy = load_job_search_policy()
    prompt = Path("docs/prompts/tech-job-headhunter-master-prompt.md").read_text(encoding="utf-8")

    for family in policy.role_families:
        self.assertIn(family.label, prompt)
    for decision in policy.decisions:
        self.assertIn(decision, prompt)
    self.assertIn("enterprise SaaS", prompt)
    self.assertIn("không yêu cầu CV", prompt)
    self.assertIn("LinkedIn Posts", prompt)
    self.assertIn("official ATS", prompt)
    self.assertNotIn("{{", prompt)
    self.assertNotIn("}}", prompt)


def test_policy_prompt_fragment_is_compact_and_complete():
    fragment = policy_prompt_fragment()

    self.assertIn("Forward Deployed Engineering", fragment)
    self.assertIn("Technical Account Management", fragment)
    self.assertIn("APPLY_NOW", fragment)
    self.assertIn("REJECT", fragment)
    self.assertIn("enterprise saas", fragment.lower())
    self.assertLess(len(fragment), 6500)
~~~

- [ ] **Step 2: Run the prompt test and verify the artifact/function are missing.**

~~~bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
~~~

Expected: FAIL for missing docs/prompts/tech-job-headhunter-master-prompt.md or policy_prompt_fragment.

- [ ] **Step 3: Create the standalone Vietnamese master prompt.**

The file must be directly copyable and contain these instructions as final content, with the full JSON keys shown below:

~~~markdown
# Master Prompt — Technical Job Headhunter

Bạn là technical headhunter có 20 năm kinh nghiệm tìm kiếm nhân sự công nghệ và consulting. Hãy chủ động tìm, xác minh, loại trùng và xếp hạng cơ hội; không yêu cầu CV và không chấm ứng viên theo hồ sơ cá nhân.

## Search profile cố định

Thứ tự vai trò: Forward Deployed Engineering; Solutions Engineering and Architecture; AI Consulting; Technical Presales; Technical Account Management.
Seniority: Mid, Senior, Staff và hands-on Lead individual contributor.
Domain: AI/GenAI, AI agents, LLM/RAG, enterprise automation và enterprise SaaS.
Địa lý: Remote Vietnam; Remote APAC/SEA/Asia/global cần xác minh; hybrid/onsite Vietnam; APAC relocation có bằng chứng.

## Hard rules

- Loại Intern, Graduate, Entry-level, Junior, Manager, Director, Head và Executive.
- AI Consulting, Technical Presales và Technical Account Management phải có bằng chứng như demo, PoC, architecture, API, integration, troubleshooting, implementation hoặc production deployment.
- Loại sales/account management thuần quota, cold calling, pipeline, renewals hoặc upsell khi không có bằng chứng kỹ thuật.
- Không suy diễn Remote, APAC, SEA, global hoặc Singapore đồng nghĩa tuyển được người tại Việt Nam.
- Không bịa status, date, location, remote eligibility, salary, benefits, contact hoặc apply link.
- Mọi kết quả hợp lệ đều phải có should_alert=true; độ ưu tiên chỉ thay đổi thứ tự.

## Search playbook

1. Tạo nhiều Boolean query ngắn theo từng role family bằng AND, OR, NOT, dấu ngoặc kép và dấu ngoặc tròn.
2. Tìm official career pages và official ATS trước: Greenhouse, Lever, Ashby, Workable, Workday, SmartRecruiters, Teamtailor và Recruitee.
3. Tìm LinkedIn Jobs, LinkedIn Posts của recruiter/hiring manager/team lead, company pages và company job alerts.
4. Tìm job boards, Hacker News hiring threads, Reddit hiring communities và company expansion signals.
5. Dùng aggregator như lead; cố gắng thay bằng canonical employer/ATS URL.
6. Xác minh job còn mở, ngày đăng, seniority, technical scope, applicant-location restriction và relocation evidence.
7. Chỉ trả public contact có bằng chứng trong source.
8. Dedupe bằng canonical apply URL; fallback bằng normalized company + title + location.

## Query pack tối thiểu

- "Forward Deployed Engineer" AND (Vietnam OR APAC OR remote)
- ("Solutions Engineer" OR "Solution Architect") AND (AI OR GenAI OR "enterprise SaaS") AND (Vietnam OR APAC OR remote)
- ("AI Consultant" OR "Technical Consultant") AND (implementation OR integration OR LLM OR RAG) AND (Vietnam OR APAC OR remote)
- (presales OR "Sales Engineer") AND (demo OR PoC OR architecture OR API OR integration) AND (AI OR "enterprise SaaS") AND (Vietnam OR APAC OR remote)
- "Technical Account Manager" AND (troubleshooting OR architecture OR API OR integration) AND (AI OR "enterprise SaaS") AND (Vietnam OR APAC OR remote)

## Decision

- APPLY_NOW: vacancy đang mở, technical scope rõ, seniority hợp lệ, và Việt Nam/relocation được xác nhận.
- VERIFY_FIRST: vacancy đúng scope nhưng location, eligibility, seniority hoặc status cần xác minh.
- DM_FIRST: recruiter/hiring-manager/team post đáng tin để tiếp cận trực tiếp.
- WATCH: expansion/hiring signal chưa có vacancy cụ thể.
- REJECT: job đóng, sai role/domain/seniority, thiếu technical scope hoặc không khả thi từ Việt Nam và không có relocation.

## Output

Trả một phần tóm tắt ngắn bằng tiếng Việt, sau đó một JSON code block có search_run và items. Mỗi item phải có: id, decision, priority, company, role_family, role_title, required_seniority, technical_evidence, domain, location, remote_policy, vietnam_eligibility, evidence_type, status, posted_date, source_type, source_url, apply_url, contact_person, contact_url, why_it_fits, what_to_verify, compensation, benefits, company_expansion_signal, hidden_hiring_signal, recommended_action, outreach_angle, confidence_score, should_alert.

Nếu không có browsing, nói rõ giới hạn và chỉ trả query pack cùng search plan; không tạo job giả.
~~~

After this instruction body, include this exact JSON contract:

~~~json
{
  "search_run": {
    "searched_at": "ISO-8601 timestamp",
    "queries_used": [],
    "sources_checked": [],
    "limitations": []
  },
  "items": [
    {
      "id": "stable-lowercase-slug",
      "decision": "APPLY_NOW|VERIFY_FIRST|DM_FIRST|WATCH|REJECT",
      "priority": "High|Medium|Low",
      "company": "",
      "role_family": "",
      "role_title": "",
      "required_seniority": "",
      "technical_evidence": [],
      "domain": [],
      "location": "",
      "remote_policy": "",
      "vietnam_eligibility": "explicit_yes|likely_possible|verify|unlikely|no",
      "evidence_type": "HARD|MEDIUM|WEAK",
      "status": "open|likely_open|uncertain|closed|watch",
      "posted_date": "",
      "source_type": "",
      "source_url": "",
      "apply_url": "",
      "contact_person": "",
      "contact_url": "",
      "why_it_fits": "",
      "what_to_verify": [],
      "compensation": "",
      "benefits": "",
      "company_expansion_signal": "",
      "hidden_hiring_signal": "",
      "recommended_action": "apply_now|verify_first|dm_first|watch|ignore",
      "outreach_angle": "",
      "confidence_score": 0,
      "should_alert": true
    }
  ]
}
~~~

- [ ] **Step 4: Render the compact shared policy fragment.**

~~~python
def policy_prompt_fragment(policy: JobSearchPolicy | None = None) -> str:
    active = policy or load_job_search_policy()
    role_lines = []
    for family in active.role_families:
        role_lines.append(
            f"{family.priority}. {family.label}; titles={', '.join(family.title_aliases)}; "
            f"technical evidence={', '.join(family.technical_signals)}; "
            f"negative signals={', '.join(family.negative_signals)}; "
            f"technical evidence required={str(family.requires_technical_evidence).lower()}"
        )
    return "\n".join([
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
        "REJECT only for closed/expired, wrong role/domain/seniority, insufficient "
        "technical scope, or explicit Vietnam incompatibility without relocation.",
    ])
~~~

- [ ] **Step 5: Run prompt and policy tests.**

~~~bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
~~~

Expected: PASS.

- [ ] **Step 6: Commit the standalone prompt.**

~~~bash
git add docs/prompts/tech-job-headhunter-master-prompt.md news_keep_up/job_search_policy.py tests/test_job_search_policy.py
git diff --cached --check
git commit -m "feat(jobs): add headhunter prompt contract"
~~~

---

### Task 4: Make Gemini and Local Fallback Enforce the Shared Policy

**Files:**
- Modify: news_keep_up/gemini.py:138-225,287-316,328-465,662-739,760-916
- Modify: tests/test_gemini.py:165-376

**Interfaces:**
- Consumes: policy_prompt_fragment and evaluate_job_candidate from Tasks 2-3.
- Preserves: build_job_classification_prompt(candidates: list[tuple[int, CandidateItem]], crawled_at: str) -> str
- Preserves: parse_job_classification_response(text: str, candidates_by_id: dict[int, CandidateItem], model: str, crawled_at: str) -> list[JobOpportunity]
- Preserves: fallback_job_opportunities(candidates: list[tuple[int, CandidateItem]], crawled_at: str) -> list[JobOpportunity]
- Produces internally: validate_job_opportunity(opportunity: JobOpportunity, candidate: CandidateItem) -> JobOpportunity | None

- [ ] **Step 1: Add failing Gemini prompt, parsing, and fallback tests.**

Add these behaviors:

~~~python
def test_job_prompt_uses_shared_role_families_and_decisions():
    prompt = build_job_classification_prompt([(7, make_item())], "2026-08-06")
    self.assertIn("Solutions Engineering and Architecture", prompt)
    self.assertIn("Technical Presales", prompt)
    self.assertIn("Technical Account Management", prompt)
    self.assertIn("enterprise saas", prompt.lower())
    self.assertIn("VERIFY_FIRST", prompt)
    self.assertIn("DM_FIRST", prompt)
    self.assertLess(len(prompt), 12000)


def test_parser_overrides_model_for_pure_quota_presales():
    candidate = CandidateItem(
        source_name="LinkedIn Presales",
        source_kind="rss",
        source_category="linkedin-hidden-hiring-search",
        title="Senior Presales Engineer",
        url="https://example.com/presales",
        canonical_url="https://example.com/presales",
        summary="Enterprise SaaS quota carrying, prospecting, cold calling, and pipeline ownership.",
        raw={"location": "Remote Vietnam"},
    )
    response = json.dumps({"items": [{
        "candidate_id": 7,
        "role_title": candidate.title,
        "role_family": "Technical Presales",
        "decision": "APPLY_NOW",
        "category": "Technical Presales",
        "location": "Vietnam",
        "vietnam_eligibility": "explicit_yes",
        "status": "open",
        "recommended_action": "apply_now",
        "should_alert": True
    }]})
    self.assertEqual(
        parse_job_classification_response(response, {7: candidate}, "gemini-test", "2026-08-06"),
        [],
    )


def test_parser_keeps_unknown_location_as_verify_first():
    candidate = CandidateItem(
        source_name="Company Careers",
        source_kind="html",
        source_category="job-board",
        title="Senior Solutions Engineer",
        url="https://example.com/jobs/se",
        canonical_url="https://example.com/jobs/se",
        summary="Enterprise SaaS architecture, PoC, API integration, and implementation.",
    )
    response = json.dumps({"items": [{
        "candidate_id": 9,
        "role_title": candidate.title,
        "role_family": "Solutions Engineering and Architecture",
        "decision": "APPLY_NOW",
        "category": "Solutions Engineering and Architecture",
        "location": "",
        "vietnam_eligibility": "explicit_yes",
        "status": "open",
        "technical_evidence": ["architecture", "poc", "api", "integration"],
        "recommended_action": "apply_now",
        "should_alert": False
    }]})
    opportunity = parse_job_classification_response(
        response,
        {9: candidate},
        "gemini-test",
        "2026-08-06",
    )[0]
    self.assertEqual(opportunity.vietnam_eligibility, "verify")
    self.assertEqual(opportunity.recommended_action, "verify_first")
    self.assertTrue(opportunity.should_alert)


def test_fallback_uses_policy_role_family_and_technical_evidence():
    candidate = CandidateItem(
        source_name="Company Careers",
        source_kind="html",
        source_category="job-board",
        title="Senior Technical Account Manager",
        url="https://example.com/jobs/tam",
        canonical_url="https://example.com/jobs/tam",
        summary="Remote APAC enterprise SaaS architecture, API integration, troubleshooting, and implementation guidance.",
        raw={"location": "Remote APAC", "remote_policy": "Remote"},
    )
    opportunity = fallback_job_opportunities([(11, candidate)], "2026-08-06")[0]
    self.assertEqual(opportunity.category, "Technical Account Management")
    self.assertEqual(opportunity.recommended_action, "verify_first")
    self.assertTrue(opportunity.should_alert)
    self.assertIn("Technical evidence", opportunity.why_it_fits)
~~~

Update prior assertions from Exact FDE Role and FDE-Adjacent Role to the new role-family labels. Preserve tests for bad JSON, closed jobs, explicit Remote-US rejection, stable IDs, and no-key fallback.

- [ ] **Step 2: Run Gemini tests and verify the new policy assertions fail.**

~~~bash
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
~~~

Expected: FAIL because the prompt and parser still use hard-coded FDE categories/actions.

- [ ] **Step 3: Replace the hard-coded classifier instructions with the shared fragment.**

Keep candidate JSON trimming and append this compact contract:

~~~python
policy_text = policy_prompt_fragment()
return (
    "You classify technical job and hidden-hiring candidates.\n"
    f"{policy_text}\n"
    "Use only supplied evidence. Empty unknown fields and add them to what_to_verify.\n"
    "Return JSON only. Each item must include candidate_id, id, decision, priority, "
    "company, role_family, role_title, category, location, remote_policy, "
    "vietnam_eligibility, evidence_type, status, posted_date, source_type, source_url, "
    "apply_url, contact_person, contact_url, technical_evidence, why_it_fits, "
    "what_to_verify, required_seniority, required_skills, domain, country, compensation, "
    "benefits, package, company_size, company_coverage, company_expansion_signal, "
    "linkedin_post_signal, recommended_action, outreach_angle, confidence_score, "
    "and should_alert.\n"
    "Use Hard|Medium|Weak for application evidence_type. should_alert=false only for "
    "REJECT or closed; true otherwise.\n\n"
    f"Crawled at: {crawled_at}\nCandidates:\n{items_json}"
)
~~~

- [ ] **Step 4: Map decisions and preserve technical evidence without a migration.**

Use local policy evaluation as the authority:

~~~python
DECISION_TO_ACTION = {
    "APPLY_NOW": "apply_now",
    "VERIFY_FIRST": "verify_first",
    "DM_FIRST": "dm_first",
    "WATCH": "watch",
    "REJECT": "ignore",
}


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
    if source_workability == "verify":
        eligibility = "verify"
        evidence_type = "Weak"
        if action == "apply_now":
            action = "verify_first"
    elif source_workability == "likely_possible" and eligibility == "explicit_yes":
        eligibility = "likely_possible"
        evidence_type = "Medium"
        if action == "apply_now":
            action = "verify_first"

    technical = ", ".join(match.technical_evidence) or "role title and customer-delivery scope"
    why = opportunity.why_it_fits.strip()
    if not why.lower().startswith("technical evidence:"):
        why = f"Technical evidence: {technical}. {why}".strip()

    return replace(
        opportunity,
        category=match.role_family_label,
        required_seniority=opportunity.required_seniority or match.seniority,
        domain=list(match.domain_evidence) or opportunity.domain,
        vietnam_eligibility=eligibility,
        evidence_type=evidence_type,
        recommended_action=action,
        why_it_fits=why,
        should_alert=True,
    )
~~~

In _job_opportunity_from_row, compute category, action, and technical evidence before constructing JobOpportunity:

~~~python
policy = load_job_search_policy()
source_url = canonicalize_url(
    clean_text(row.get("source_url", ""))
    or candidate.canonical_url
    or candidate.url
)
apply_url = canonicalize_url(clean_text(row.get("apply_url", "")))
allowed_categories = {
    *(family.label for family in policy.role_families),
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
    _enum_value(row.get("recommended_action"), allowed_actions, "verify_first"),
)
technical_evidence = _string_list(row.get("technical_evidence"))
why_it_fits = clean_text(row.get("why_it_fits", "")) or _fallback_job_fit(candidate)
if technical_evidence and not why_it_fits.lower().startswith("technical evidence:"):
    why_it_fits = (
        f"Technical evidence: {', '.join(technical_evidence)}. {why_it_fits}"
    ).strip()
should_alert = status != "closed" and category != "Reject"
~~~

Pass source_url, apply_url, category, recommended_action, why_it_fits, and should_alert into JobOpportunity. Import canonicalize_url from news_keep_up.utils. This accepts new actions while preserving legacy rows and gives deduplication canonical URLs.

In parse_job_classification_response, call validate_job_opportunity and append only a non-None result.

- [ ] **Step 5: Rewrite fallback classification around evaluate_job_candidate.**

Delete _FALLBACK_EXACT_FDE_TITLE_SIGNALS, _FALLBACK_ROLE_TITLE_SIGNALS, _FALLBACK_OFFTOPIC_TITLE_TERMS, _fallback_job_category, and _has_fde_job_signal. Build fallback rows from JobPolicyMatch:

~~~python
match = evaluate_job_candidate(candidate)
if not match.is_eligible:
    continue
workability = vietnam_workability_for_candidate(candidate)
if workability == "no":
    continue
expansion_only = any(
    term in f"{candidate.title} {candidate.summary}".lower()
    for term in ("expanding our team", "building the team", "no exact open role")
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
    "priority": {"apply_now": "High", "watch": "Low"}.get(action, "Medium"),
    "company": company,
    "role_title": role_title,
    "role_family": match.role_family_label,
    "category": match.role_family_label,
    "location": location,
    "remote_policy": remote_policy,
    "vietnam_eligibility": workability,
    "evidence_type": "Hard" if workability == "explicit_yes" else "Medium",
    "status": "watch" if action == "watch" else status,
    "source_type": source_type,
    "source_url": candidate.url,
    "apply_url": candidate.url,
    "technical_evidence": list(match.technical_evidence),
    "why_it_fits": (
        f"Technical evidence: {', '.join(match.technical_evidence) or 'customer-delivery role scope'}. "
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
}
~~~

Pass the resulting opportunity through validate_job_opportunity for parity with Gemini output.

- [ ] **Step 6: Run Gemini, alert, and DB regression tests.**

~~~bash
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_db.py' -v
~~~

Expected: all commands PASS.

- [ ] **Step 7: Commit shared-policy classification.**

~~~bash
git add news_keep_up/gemini.py tests/test_gemini.py
git diff --cached --check
git commit -m "feat(jobs): enforce policy in classification"
~~~

---

### Task 5: Expand Source Discovery for AI Consulting and Enterprise SaaS

**Files:**
- Modify: news_keep_up/source_intelligence.py:26-49,83-172
- Modify: config/fde_job_sources.json
- Modify: config/fde_job_source_discovery_sources.json
- Modify: tests/test_source_intelligence.py
- Modify: tests/test_config.py:141-245

**Interfaces:**
- Consumes: role_terms and domain_terms from Task 1.
- Preserves: is_source_candidate(candidate: CandidateItem) -> bool
- Preserves: run_fde_job_source_intelligence(settings: Settings, dry_run: bool = False, discovery_sources_path: Path | str = DEFAULT_FDE_JOB_SOURCE_DISCOVERY_PATH, active_sources_path: Path | str = DEFAULT_FDE_JOB_ACTIVE_SOURCES_PATH, current: datetime | None = None) -> str

- [ ] **Step 1: Add failing source coverage tests.**

~~~python
def test_fde_job_sources_cover_ai_consulting_and_enterprise_saas():
    sources = load_sources("config/fde_job_sources.json")
    names = {source.name for source in sources}
    self.assertIn("Bing AI Consultant APAC Remote", names)
    self.assertIn("Bing Enterprise SaaS Solutioning APAC", names)
    self.assertIn("Bing LinkedIn Enterprise SaaS Technical Hiring", names)


def test_source_candidate_accepts_enterprise_saas_solutioning_source():
    candidate = CandidateItem(
        source_name="Bing Source Discovery",
        source_kind="rss",
        source_category="source-discovery-search",
        title="Ashby Enterprise SaaS Solutions Engineer APAC jobs",
        url="https://jobs.ashbyhq.com/example",
        canonical_url="https://jobs.ashbyhq.com/example",
        summary="Solutions Engineer and Technical Account Manager openings.",
    )
    self.assertTrue(is_source_candidate(candidate))
~~~

- [ ] **Step 2: Run config and source-intelligence tests and verify the new names fail.**

~~~bash
python3 -m unittest discover -s tests -p 'test_config.py' -v
python3 -m unittest discover -s tests -p 'test_source_intelligence.py' -v
~~~

Expected: FAIL because the new sources are absent and source intelligence still has local scope constants.

- [ ] **Step 3: Make source intelligence consume shared role/domain terms.**

Keep SOURCE_URL_SIGNALS because ATS host detection is infrastructure, not user policy. Replace SOURCE_TEXT_SIGNALS with:

~~~python
def is_source_candidate(candidate: CandidateItem) -> bool:
    text = " ".join([
        candidate.title,
        candidate.summary,
        candidate.url,
        candidate.source_name,
        candidate.source_category,
    ]).lower()
    url_hit = any(signal in text for signal in SOURCE_URL_SIGNALS)
    role_hit = any(signal in text for signal in role_terms())
    domain_hit = any(signal in text for signal in domain_terms())
    region_hit = any(signal in text for signal in ("apac", "asia", "vietnam", "remote"))
    return url_hit and role_hit and (domain_hit or region_hit)
~~~

Use the matched role label in _source_candidate_reason while retaining the existing SourceCandidate schema:

~~~python
def _source_candidate_reason(item: CandidateItem, source_type: str) -> str:
    text = f"{item.title} {item.summary}".lower()
    policy = load_job_search_policy()
    label = next(
        (
            family.label
            for family in policy.role_families
            if any(alias in text for alias in family.title_aliases)
        ),
        "approved technical job scope",
    )
    if source_type == "ATS":
        return f"Indexed ATS/career source with {label} regional keywords."
    return f"Potential job or hiring-signal source with {label} regional keywords."
~~~

- [ ] **Step 4: Add focused active and discovery sources.**

Append these active source objects, URL-encoding spaces and operators consistently with neighboring Bing RSS entries:

~~~json
[
  {
    "name": "Bing AI Consultant APAC Remote",
    "type": "rss",
    "url": "https://www.bing.com/search?q=%28%22AI%20Consultant%22%20OR%20%22GenAI%20Consultant%22%20OR%20%22AI%20Implementation%20Consultant%22%29%20%28APAC%20OR%20Vietnam%20OR%20remote%29%20%28integration%20OR%20implementation%20OR%20LLM%20OR%20RAG%29&format=rss",
    "category": "fde-adjacent-job-search",
    "source_type": "aggregator",
    "enabled": true
  },
  {
    "name": "Bing Enterprise SaaS Solutioning APAC",
    "type": "rss",
    "url": "https://www.bing.com/search?q=%28%22Solutions%20Engineer%22%20OR%20%22Solution%20Architect%22%20OR%20%22Technical%20Account%20Manager%22%29%20%28%22enterprise%20SaaS%22%20OR%20%22B2B%20SaaS%22%29%20%28APAC%20OR%20Vietnam%20OR%20remote%29&format=rss",
    "category": "enterprise-saas-job-search",
    "source_type": "aggregator",
    "enabled": true
  },
  {
    "name": "Bing LinkedIn Enterprise SaaS Technical Hiring",
    "type": "rss",
    "url": "https://www.bing.com/search?q=site%3Alinkedin.com%2Fposts%20%28%22Solutions%20Engineer%22%20OR%20presales%20OR%20%22Technical%20Account%20Manager%22%29%20%28%22enterprise%20SaaS%22%20OR%20AI%29%20%28APAC%20OR%20Vietnam%20OR%20remote%29%20hiring&format=rss",
    "category": "linkedin-hidden-hiring-search",
    "source_type": "LinkedIn_post",
    "url_host_include_any": [
      "linkedin.com"
    ],
    "enabled": true
  }
]
~~~

Append these exact discovery objects:

~~~json
[
  {
    "name": "Bing Source Discovery AI Consultant ATS APAC",
    "type": "rss",
    "url": "https://www.bing.com/search?q=%28site%3Ajobs.ashbyhq.com%20OR%20site%3Ajob-boards.greenhouse.io%20OR%20site%3Ajobs.lever.co%29%20%28%22AI%20Consultant%22%20OR%20%22GenAI%20Consultant%22%20OR%20%22Implementation%20Consultant%22%29%20%28APAC%20OR%20Vietnam%29&format=rss",
    "category": "source-discovery-search",
    "source_type": "aggregator",
    "enabled": true
  },
  {
    "name": "Bing Source Discovery Enterprise SaaS Solutioning",
    "type": "rss",
    "url": "https://www.bing.com/search?q=%28%22jobs.ashbyhq.com%22%20OR%20%22greenhouse.io%22%20OR%20%22jobs.lever.co%22%20OR%20careers%29%20%28%22Solutions%20Engineer%22%20OR%20%22Solution%20Architect%22%20OR%20%22Presales%20Engineer%22%20OR%20%22Technical%20Account%20Manager%22%29%20%22enterprise%20SaaS%22%20%28APAC%20OR%20Vietnam%29&format=rss",
    "category": "source-discovery-search",
    "source_type": "aggregator",
    "enabled": true
  }
]
~~~

- [ ] **Step 5: Validate JSON and run source tests.**

~~~bash
jq empty config/job_search_policy.json
jq empty config/fde_job_sources.json
jq empty config/fde_job_source_discovery_sources.json
python3 -m unittest discover -s tests -p 'test_config.py' -v
python3 -m unittest discover -s tests -p 'test_source_intelligence.py' -v
~~~

Expected: all commands PASS.

- [ ] **Step 6: Commit source coverage.**

~~~bash
git add news_keep_up/source_intelligence.py config/fde_job_sources.json config/fde_job_source_discovery_sources.json tests/test_source_intelligence.py tests/test_config.py
git diff --cached --check
git commit -m "feat(jobs): expand consulting job sources"
~~~

---

### Task 6: Rank, Deduplicate, and Format Every Alertable Decision

**Files:**
- Modify: news_keep_up/models.py:89-139
- Modify: news_keep_up/db.py:588-671
- Modify: news_keep_up/job_alerts.py:194-327,552-585
- Modify: tests/test_db.py:78-270
- Modify: tests/test_job_alerts.py:88-110,520-680

**Interfaces:**
- Consumes: five role-family labels and actions apply_now, verify_first, dm_first, watch, ignore.
- Preserves: JobOpportunity storage columns.
- Preserves: list_pending_job_alerts(conn, limit: int = 20) -> list[JobOpportunity]
- Preserves: format_job_alert(opportunity: JobOpportunity, current: datetime | None = None) -> str
- Preserves: JOB_ALERT_BATCH_LIMIT = 3

- [ ] **Step 1: Add failing ordering, material-update, and formatter tests.**

Add a DB ordering test that inserts one opportunity per action in reverse order and expects:

~~~python
self.assertEqual(
    [item.recommended_action for item in list_pending_job_alerts(conn)],
    ["apply_now", "dm_first", "verify_first", "watch"],
)
~~~

Add a material update test:

~~~python
original = make_job_opportunity()
upsert_job_opportunity(conn, original)
mark_job_alert_delivered(conn, original.id, original.alert_fingerprint)

changed = JobOpportunity(**{
    **original.__dict__,
    "vietnam_eligibility": "explicit_yes",
    "remote_policy": "Remote Vietnam",
    "recommended_action": "apply_now",
})
upsert_job_opportunity(conn, changed)
self.assertEqual([item.id for item in list_pending_job_alerts(conn)], [changed.id])
~~~

Ensure the test starts original with vietnam_eligibility=verify, remote_policy=Remote APAC, and recommended_action=verify_first so the fingerprint changes. Keep the existing corrected-company/same-URL/same-fingerprint test expecting no duplicate.

Update formatter assertions:

~~~python
self.assertIn("APPLY NOW", message)
self.assertIn("🏷 Nhóm: Forward Deployed Engineering", message)
self.assertIn("🪜 Seniority: Senior", message)
self.assertIn("🔧 Tech evidence:", message)
self.assertIn("🇻🇳 Khả năng từ VN:", message)
self.assertIn("🎯 Hành động: Apply now", message)
~~~

- [ ] **Step 2: Run DB and alert tests and verify ordering/material-update assertions fail.**

~~~bash
python3 -m unittest discover -s tests -p 'test_db.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
~~~

Expected: FAIL because pending rows are ordered only by updated_at, URL dedupe suppresses material changes, and the formatter lacks decision/seniority/technical labels.

- [ ] **Step 3: Make alert fingerprints normalize titles and include action.**

In news_keep_up/models.py:

~~~python
@property
def alert_fingerprint(self) -> str:
    parts = [
        f"priority={self.priority}",
        f"status={self.status}",
        f"eligibility={self.vietnam_eligibility}",
        f"location={self.location}",
        f"role={_normalize_job_title(self.role_title)}",
        f"action={self.recommended_action}",
        f"apply={self.apply_url or self.source_url}",
    ]
    return "|".join(_compact_fingerprint_part(part) for part in parts)


def _normalize_job_title(value: str) -> str:
    normalized = " ".join(value.lower().replace("sr.", "senior").split())
    return normalized.replace("sr ", "senior ", 1)
~~~

This keeps existing columns while making Sr. and Senior equivalent.

- [ ] **Step 4: Order pending rows by decision, role family, evidence, and confidence.**

Replace ORDER BY updated_at DESC with:

~~~sql
ORDER BY
  CASE recommended_action
    WHEN 'apply_now' THEN 0
    WHEN 'dm_first' THEN 1
    WHEN 'dm_recruiter_first' THEN 1
    WHEN 'verify_first' THEN 2
    WHEN 'set_alert' THEN 2
    WHEN 'watch' THEN 3
    WHEN 'follow_company' THEN 3
    ELSE 4
  END,
  CASE category
    WHEN 'Forward Deployed Engineering' THEN 0
    WHEN 'Solutions Engineering and Architecture' THEN 1
    WHEN 'AI Consulting' THEN 2
    WHEN 'Technical Presales' THEN 3
    WHEN 'Technical Account Management' THEN 4
    WHEN 'Exact FDE Role' THEN 0
    ELSE 5
  END,
  CASE evidence_type WHEN 'Hard' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,
  CASE source_type
    WHEN 'official_career_page' THEN 0
    WHEN 'ATS' THEN 0
    WHEN 'LinkedIn_job' THEN 1
    WHEN 'LinkedIn_post' THEN 2
    WHEN 'company_blog' THEN 2
    WHEN 'job_board' THEN 3
    WHEN 'community' THEN 4
    WHEN 'aggregator' THEN 5
    ELSE 6
  END,
  confidence_score DESC,
  updated_at DESC
~~~

Change the URL dedupe NOT EXISTS subquery to suppress only an already delivered identical fingerprint:

~~~sql
AND delivered_alert.alert_fingerprint = jo.alert_fingerprint
~~~

The existing first NOT EXISTS still handles the same opportunity ID. This permits a changed eligibility/status/action/apply link to alert again while suppressing a corrected duplicate ID with the same URL and fingerprint.

- [ ] **Step 5: Add explicit decision, role, seniority, and technical evidence to Telegram.**

Use these labels:

~~~python
def _decision_label(action: str) -> str:
    return {
        "apply_now": "APPLY NOW",
        "verify_first": "VERIFY FIRST",
        "dm_first": "DM FIRST",
        "dm_recruiter_first": "DM FIRST",
        "watch": "WATCH",
        "follow_company": "WATCH",
        "set_alert": "VERIFY FIRST",
        "ignore": "REJECT",
    }.get(action, "VERIFY FIRST")


def _action_label(opportunity: JobOpportunity) -> str:
    return {
        "apply_now": "Apply now",
        "verify_first": "Verify eligibility/status first",
        "dm_first": "DM recruiter or hiring manager first",
        "dm_recruiter_first": "DM recruiter or hiring manager first",
        "watch": "Watch company/team",
        "follow_company": "Watch company/team",
        "set_alert": "Track and verify",
        "ignore": "Ignore",
    }.get(opportunity.recommended_action, "Track and verify")
~~~

Replace the formatter line assembly with this structure:

~~~python
decision = _decision_label(opportunity.recommended_action)
seniority = opportunity.required_seniority or "Verify"
technical_evidence = opportunity.why_it_fits or "Verify technical scope"
lines = [
    (
        f"{priority_icon} <b>Tech Job Alert</b> · {escape(decision)} · "
        f"{opportunity.confidence_score}/100"
    ),
    f"Time: {escape(timestamp.strftime('%d %b %H:%M'))} ICT",
    "",
    f"<b>{escape(opportunity.role_title)}</b>",
    f"🏢 Công ty: {escape(opportunity.company)}",
    f"🏷 Nhóm: {escape(opportunity.category)}",
    f"🪜 Seniority: {escape(seniority)}",
    f"🔧 Tech evidence: {escape(technical_evidence)}",
    f"📍 Địa điểm: {escape(location)}",
    f"🌍 Quốc gia: {escape(opportunity.country or _country_from_location(location) or 'Verify')}",
    f"🌐 Remote: {escape(remote_policy)}",
    f"💰 Lương/package: {escape(compensation)}",
    f"🎁 Phúc lợi: {escape(benefits)}",
    f"🏬 Company footprint: {escape(footprint)}",
    (
        f"🇻🇳 Khả năng từ VN: {escape(opportunity.vietnam_eligibility)} · "
        f"{escape(opportunity.evidence_type)} signal"
    ),
    f"📌 Trạng thái: {escape(status_label)} · Nguồn: {escape(source_label)}",
    f"❓ Cần verify: {escape(verify)}",
    f"🎯 Hành động: {escape(action)}",
]
focus = _focus_line(opportunity)
if focus:
    lines.insert(8, focus)
if opportunity.outreach_angle:
    lines.append(f"✉️ Outreach: {escape(opportunity.outreach_angle)}")
lines.append(f'🔗 Link: <a href="{escape(source, quote=True)}">{escape(source)}</a>')
return "\n".join(lines).strip()
~~~

- [ ] **Step 6: Verify three-per-scan queue draining and all alert actions.**

Add this run_fde_job_alerts queue-draining test, adapting make_opportunity only through dataclass copies:

~~~python
def test_run_alerts_drains_five_pending_items_across_two_scans(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        sources_path = Path(tmp) / "sources.json"
        sources_path.write_text("[]", encoding="utf-8")
        settings = Settings(
            db_path=db_path,
            telegram_bot_token="bot-token",
            telegram_chat_id="-100123",
        )
        conn = connect_database(settings)
        init_db(conn)
        actions = ["watch", "verify_first", "dm_first", "apply_now", "verify_first"]
        for index, action in enumerate(actions):
            candidate = CandidateItem(
                source_name="Fixture Careers",
                source_kind="html",
                source_category="job-board",
                title=f"Senior Solutions Engineer {index}",
                url=f"https://example.com/jobs/{index}",
                canonical_url=f"https://example.com/jobs/{index}",
                summary="Remote Vietnam enterprise SaaS architecture and API integration.",
                fingerprint=f"fixture-{index}",
            )
            item_id, _ = upsert_item(conn, candidate)
            base = make_opportunity(item_id)
            opportunity = JobOpportunity(**{
                **base.__dict__,
                "id": f"fixture-job-{index}",
                "role_title": candidate.title,
                "category": "Solutions Engineering and Architecture",
                "source_url": candidate.url,
                "apply_url": candidate.url,
                "recommended_action": action,
                "priority": "Low" if action == "watch" else base.priority,
                "status": "watch" if action == "watch" else "open",
            })
            upsert_job_opportunity(conn, opportunity)
        conn.close()

        with patch("news_keep_up.job_alerts.send_telegram_message") as send:
            run_fde_job_alerts(settings, sources_path=sources_path, force=True)
            self.assertEqual(send.call_count, 3)
            run_fde_job_alerts(settings, sources_path=sources_path, force=True)
            self.assertEqual(send.call_count, 5)

        conn = connect_database(settings)
        init_db(conn)
        self.assertEqual(list_pending_job_alerts(conn), [])
        conn.close()
~~~

The first scan sends three, the second sends two, and Low/WATCH items remain queued rather than dropped.

Add a retry-safety test using one seeded opportunity and:

~~~python
with patch(
    "news_keep_up.job_alerts.send_telegram_message",
    side_effect=RuntimeError("telegram unavailable"),
):
    with self.assertRaisesRegex(RuntimeError, "telegram unavailable"):
        run_fde_job_alerts(settings, sources_path=sources_path, force=True)

conn = connect_database(settings)
init_db(conn)
self.assertEqual(len(list_pending_job_alerts(conn)), 1)
conn.close()
~~~

This proves delivery is marked only after Telegram succeeds.

Run:

~~~bash
python3 -m unittest discover -s tests -p 'test_db.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_telegram_commands.py' -v
~~~

Expected: all commands PASS.

- [ ] **Step 7: Commit queue and alert behavior.**

~~~bash
git add news_keep_up/models.py news_keep_up/db.py news_keep_up/job_alerts.py tests/test_db.py tests/test_job_alerts.py
git diff --cached --check
git commit -m "feat(jobs): rank and format job decisions"
~~~

---

### Task 7: Document and Run Full Verification

**Files:**
- Modify: README.md:9-23,110-151,173-224

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: operator documentation and a fully passing test suite.

- [ ] **Step 1: Update README with the final shared-policy behavior.**

Document:

- fde-jobs now covers the five approved role families with FDE first.
- Mid/Senior/Staff/hands-on Lead scope.
- AI/GenAI/agents/LLM/RAG/automation and enterprise SaaS.
- Technical evidence gate for AI Consulting, Presales, and TAM.
- APPLY_NOW, VERIFY_FIRST, DM_FIRST, WATCH, and REJECT meanings.
- Unknown eligibility is sent as VERIFY_FIRST; explicit incompatibility is rejected.
- No CV matching; every valid opportunity is queued.
- Three alerts per scan, with remaining results pending.
- Shared config path config/job_search_policy.json.
- Standalone prompt path docs/prompts/tech-job-headhunter-master-prompt.md.

Use this concise profile summary:

~~~markdown
- fde-jobs: shared technical-headhunter flow for Forward Deployed Engineering, Solutions Engineering/Architecture, AI Consulting, Technical Presales, and Technical Account Management. It targets Mid through hands-on Lead IC roles in AI and enterprise SaaS, ranks Vietnam-compatible work first, and alerts every qualifying vacancy or hidden-hiring signal without CV matching.
~~~

- [ ] **Step 2: Validate all JSON, imports, and whitespace.**

~~~bash
jq empty config/job_search_policy.json
jq empty config/fde_job_sources.json
jq empty config/fde_job_source_discovery_sources.json
python3 -m compileall -q news_keep_up
git diff --check
~~~

Expected: all commands exit 0 with no output except normal compile progress when the local Python version emits it.

- [ ] **Step 3: Run the focused job pipeline suite.**

~~~bash
python3 -m unittest \
  tests.test_job_search_policy \
  tests.test_job_alerts \
  tests.test_gemini \
  tests.test_source_intelligence \
  tests.test_db \
  tests.test_config \
  tests.test_telegram_commands \
  tests.test_vercel_deploy \
  -v
~~~

Expected: PASS with zero failures and zero errors.

- [ ] **Step 4: Run the full repository suite.**

~~~bash
python3 -m unittest discover -s tests -v
~~~

Expected: PASS with zero failures and zero errors.

- [ ] **Step 5: Inspect the generated standalone prompt and a dry-run alert fixture.**

~~~bash
sed -n '1,260p' docs/prompts/tech-job-headhunter-master-prompt.md
python3 -m unittest tests.test_job_alerts.JobAlertsTest.test_format_job_alert_is_concise_with_analysis_location_and_link -v
~~~

Expected: the prompt contains all five families and JSON contract; the formatter test passes with decision, role family, technical evidence, eligibility, verification, action, and link.

- [ ] **Step 6: Commit the operator documentation.**

~~~bash
git add README.md
git diff --cached --check
git commit -m "docs(jobs): document shared search policy"
~~~

- [ ] **Step 7: Review the complete branch before handoff.**

~~~bash
git status --short
git log --oneline --decorate -8
git diff HEAD~7..HEAD --stat
~~~

Expected: worktree clean; recent commits correspond to the seven task deliverables; no generated cache, local database, environment file, or secret is tracked.
