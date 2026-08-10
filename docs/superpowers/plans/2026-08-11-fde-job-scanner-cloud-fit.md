# FDE Job Scanner Cloud-Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing `fde-jobs` profile so it considers LinkedIn Posts before Jobs, ranks FDE first, filters mandatory cloud work, preserves optional-cloud stretch roles, verifies links conservatively, and sends one detailed Telegram alert per opportunity.

**Architecture:** Extend the versioned job-search policy with deterministic cloud and source-stage rules, then make candidate selection, Gemini/fallback classification, persistence, verification, and pending-alert ordering consume that shared contract. Keep the current scheduler, endpoints, database, three-alert flood-control limit, and Telegram delivery flow; add only an isolated link-verification helper and additive database columns.

**Tech Stack:** Python 3.11+, standard-library dataclasses/json/re/urllib/concurrent.futures/datetime, unittest, SQLite/Turso through the existing database abstraction, Gemini REST, Telegram Bot API, and JSON-configured RSS/HTML/API sources.

## Global Constraints

- Keep the existing `fde-jobs` profile, 30-minute schedule, endpoints, Telegram destination, force mode, and dry-run behavior backward compatible.
- Keep Forward Deployed Engineering first while retaining Solutions Engineering/Architecture, AI Consulting, Technical Presales, and Technical Account Management.
- Add the seven approved aliases exactly as specified in the design.
- Reject mandatory core AWS, GCP, Azure, Kubernetes, Terraform, DevOps, SRE, and MLOps requirements.
- Keep `nice_to_have` and `exposure` cloud roles and label them `Stretch`.
- Treat a bare cloud technology mention as `unclear`, not mandatory.
- Process and queue LinkedIn Posts before LinkedIn Jobs; keep FDE first inside each source stage.
- Keep confirmed Vietnam roles above uncertain APAC/global roles and APAC country-locked auxiliary roles.
- Reject non-APAC country locks without explicit relocation evidence.
- Do not infer open status, posting dates, Vietnam eligibility, contacts, compensation, or official apply links.
- Do not bypass LinkedIn login walls, bot challenges, or rate limits.
- Do not auto-apply or contact recruiters.
- Keep `MAX_LLM_ITEMS_PER_RUN` as the total candidate-classification ceiling.
- Send at most three individual Telegram alerts per scan; leave the rest pending.
- Add no third-party runtime dependency and perform no destructive database migration.
- Use test-first implementation and commit after every task.
- Do not deploy as part of this plan.

---

## File Structure

- Modify `config/job_search_policy.json`: policy version 2, requested title aliases, source-stage order, and cloud evidence vocabulary.
- Modify `news_keep_up/job_search_policy.py`: policy validation, deterministic cloud assessment, source-type inference, and source-stage priority.
- Modify `news_keep_up/models.py`: persisted cloud assessment fields and material alert fingerprint.
- Modify `news_keep_up/db.py`: additive cloud columns, round-trip persistence/search, and source-first pending ordering.
- Modify `news_keep_up/job_alerts.py`: staged source fetching, fair candidate allocation, reconciliation/verification integration, and Telegram formatting.
- Create `news_keep_up/job_verification.py`: bounded direct-link status checking, freshness enforcement, and conservative cross-source reconciliation.
- Modify `news_keep_up/job_filters.py`: APAC country-lock auxiliary behavior.
- Modify `news_keep_up/gemini.py`: structured cloud/source contract, local hard-rule validation, and fallback parity.
- Modify `config/fde_job_sources.json`: focused LinkedIn Post and LinkedIn Job queries for every requested alias.
- Modify `config/fde_job_source_discovery_sources.json`: corresponding discovery queries.
- Modify `docs/prompts/tech-job-headhunter-master-prompt.md`: manual prompt parity with the automated policy.
- Modify `README.md`: user-visible scanner behavior and alert fields.
- Modify `tests/test_job_search_policy.py`, `tests/test_db.py`, `tests/test_job_alerts.py`, `tests/test_gemini.py`, and `tests/test_config.py`: unit and integration regressions.
- Create `tests/test_job_verification.py`: isolated link, freshness, and reconciliation tests.

### Task 1: Policy Version 2, Aliases, and Deterministic Cloud Assessment

**Files:**
- Modify: `config/job_search_policy.json`
- Modify: `news_keep_up/job_search_policy.py`
- Test: `tests/test_job_search_policy.py`

**Interfaces:**
- Produces: `CloudPolicy`
- Produces: `CloudAssessment(requirement: str, evidence: tuple[str, ...])`
- Produces: `assess_cloud_text(text: str, policy: JobSearchPolicy | None = None) -> CloudAssessment`
- Produces: `assess_cloud_candidate(candidate: CandidateItem, policy: JobSearchPolicy | None = None) -> CloudAssessment`
- Extends: `JobPolicyMatch.cloud_requirement` and `JobPolicyMatch.cloud_evidence`
- Consumed later by: candidate prefiltering, Gemini validation/fallback, persistence, ordering, and Telegram formatting.

- [ ] **Step 1: Write failing policy, alias, and cloud-assessment tests**

Add these imports and tests to `tests/test_job_search_policy.py`:

```python
from news_keep_up.job_search_policy import (
    assess_cloud_text,
    evaluate_job_text,
    load_job_search_policy,
    policy_prompt_fragment,
)


def test_policy_v2_has_source_stages_and_cloud_contract(self):
    policy = load_job_search_policy()

    self.assertEqual(policy.version, 2)
    self.assertEqual(
        policy.source_stage_order,
        (
            "LinkedIn_post",
            "LinkedIn_job",
            "official_career_page",
            "ATS",
            "job_board",
            "community",
            "aggregator",
        ),
    )
    self.assertIn("kubernetes", policy.cloud.technologies)
    self.assertIn("nice to have", policy.cloud.optional_markers)


def test_requested_aliases_map_to_approved_families(self):
    cases = {
        "Senior Forward Deployed Software Engineer": "Forward Deployed Engineering",
        "Senior AI Implementation Engineer": "Forward Deployed Engineering",
        "Senior AI Deployment Engineer": "Forward Deployed Engineering",
        "Senior AI Solutions Engineer": "Solutions Engineering and Architecture",
        "Senior Technical Solutions Engineer": "Solutions Engineering and Architecture",
        "Senior Integration Engineer": "Solutions Engineering and Architecture",
        "Senior AI Transformation Consultant": "AI Consulting",
    }
    body = (
        "Enterprise AI agents and RAG customer implementation with API integration, "
        "technical discovery, solution design, and production deployment."
    )

    for title, family in cases.items():
        with self.subTest(title=title):
            match = evaluate_job_text(title, body)
            self.assertTrue(match.is_eligible, match.reject_reason)
            self.assertEqual(match.role_family_label, family)


def test_generic_integration_engineer_still_requires_approved_domain(self):
    match = evaluate_job_text(
        "Senior Integration Engineer",
        "Integrate warehouse conveyors and industrial PLC controllers.",
    )

    self.assertEqual(match.reject_reason, "outside-domain-scope")


def test_cloud_requirement_uses_context_not_bare_keywords(self):
    cases = {
        "Must have hands-on Kubernetes and Terraform production experience.": "required_core",
        "AWS experience is preferred but not required.": "nice_to_have",
        "Exposure to Azure is useful for customer conversations.": "exposure",
        "The product can integrate with AWS data sources.": "unclear",
        "Build Python APIs and AI agent workflows for customers.": "not_mentioned",
        "Own the Kubernetes clusters and Terraform infrastructure.": "required_core",
    }

    for text, expected in cases.items():
        with self.subTest(text=text):
            self.assertEqual(assess_cloud_text(text).requirement, expected)


def test_required_cloud_makes_an_otherwise_valid_role_ineligible(self):
    match = evaluate_job_text(
        "Senior Forward Deployed Engineer",
        "Enterprise AI customer deployment. Must operate Kubernetes clusters "
        "and own Terraform infrastructure in production.",
    )

    self.assertEqual(match.reject_reason, "cloud-required-core")
    self.assertEqual(match.cloud_requirement, "required_core")
```

- [ ] **Step 2: Run the policy tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
```

Expected: FAIL because policy version 2 fields, the seven aliases, and cloud-assessment interfaces do not exist.

- [ ] **Step 3: Extend the JSON policy and implement cloud assessment**

Change the top-level version and add these exact policy sections to `config/job_search_policy.json`:

```json
{
  "version": 2,
  "source_stage_order": [
    "LinkedIn_post",
    "LinkedIn_job",
    "official_career_page",
    "ATS",
    "job_board",
    "community",
    "aggregator"
  ],
  "cloud": {
    "requirements": [
      "required_core",
      "nice_to_have",
      "exposure",
      "not_mentioned",
      "unclear"
    ],
    "technologies": [
      "aws",
      "amazon web services",
      "gcp",
      "google cloud",
      "azure",
      "kubernetes",
      "k8s",
      "terraform",
      "infrastructure as code",
      "devops",
      "sre",
      "site reliability",
      "mlops"
    ],
    "mandatory_markers": [
      "required",
      "must have",
      "you must",
      "essential",
      "minimum qualification",
      "proficiency",
      "strong expertise",
      "deep expertise",
      "production experience",
      "hands-on experience"
    ],
    "optional_markers": [
      "preferred",
      "desirable",
      "bonus",
      "plus",
      "nice to have",
      "optional",
      "not required"
    ],
    "exposure_markers": [
      "exposure",
      "familiarity",
      "awareness",
      "working knowledge",
      "willingness to learn"
    ],
    "core_responsibility_signals": [
      "own cloud infrastructure",
      "own the kubernetes clusters",
      "operate kubernetes clusters",
      "build terraform infrastructure",
      "own terraform infrastructure",
      "production cloud architecture",
      "ci/cd platform ownership",
      "reliability on-call ownership",
      "mlops platform operations"
    ]
  }
}
```

Ensure the aliases occur exactly once in the existing role-family arrays with these exact mappings; do not duplicate `ai deployment engineer` if it is already present:

```json
{
  "forward_deployed_engineering": [
    "forward deployed software engineer",
    "ai implementation engineer",
    "ai deployment engineer"
  ],
  "solutions_engineering_architecture": [
    "ai solutions engineer",
    "technical solutions engineer",
    "integration engineer"
  ],
  "ai_consulting": [
    "ai transformation consultant"
  ]
}
```

Do not create the mapping object above as a new JSON key; append each array's values to the matching existing `title_aliases` list.

Implement these dataclasses and functions in `news_keep_up/job_search_policy.py`:

```python
CLOUD_REQUIREMENTS = (
    "required_core",
    "nice_to_have",
    "exposure",
    "not_mentioned",
    "unclear",
)


@dataclass(frozen=True)
class CloudPolicy:
    requirements: tuple[str, ...]
    technologies: tuple[str, ...]
    mandatory_markers: tuple[str, ...]
    optional_markers: tuple[str, ...]
    exposure_markers: tuple[str, ...]
    core_responsibility_signals: tuple[str, ...]


@dataclass(frozen=True)
class CloudAssessment:
    requirement: str
    evidence: tuple[str, ...] = ()


def _cloud_policy(raw: object) -> CloudPolicy:
    if not isinstance(raw, dict):
        raise ValueError("cloud must be an object")
    required = {
        "requirements",
        "technologies",
        "mandatory_markers",
        "optional_markers",
        "exposure_markers",
        "core_responsibility_signals",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(f"missing cloud keys: {', '.join(missing)}")
    requirements = _strings(raw["requirements"], "cloud.requirements")
    if requirements != CLOUD_REQUIREMENTS:
        raise ValueError("cloud.requirements must match the supported order")
    return CloudPolicy(
        requirements=requirements,
        technologies=_strings(raw["technologies"], "cloud.technologies"),
        mandatory_markers=_strings(
            raw["mandatory_markers"], "cloud.mandatory_markers"
        ),
        optional_markers=_strings(
            raw["optional_markers"], "cloud.optional_markers"
        ),
        exposure_markers=_strings(
            raw["exposure_markers"], "cloud.exposure_markers"
        ),
        core_responsibility_signals=_strings(
            raw["core_responsibility_signals"],
            "cloud.core_responsibility_signals",
        ),
    )


def assess_cloud_text(
    text: str,
    policy: JobSearchPolicy | None = None,
) -> CloudAssessment:
    active = policy or load_job_search_policy()
    normalized = _normalize(text)
    technologies = _matching_terms(normalized, active.cloud.technologies)
    core = _matching_terms(normalized, active.cloud.core_responsibility_signals)
    if core:
        return CloudAssessment("required_core", core)
    if not technologies:
        return CloudAssessment("not_mentioned")

    sentences = [
        _normalize(part)
        for part in re.split(r"(?<=[.!?;])\s+|\n+", str(text or ""))
        if _normalize(part)
    ]
    optional: list[str] = []
    exposure: list[str] = []
    for sentence in sentences:
        sentence_technologies = _matching_terms(
            sentence, active.cloud.technologies
        )
        if not sentence_technologies:
            continue
        mandatory = _matching_terms(
            sentence, active.cloud.mandatory_markers
        )
        soft = _matching_terms(sentence, active.cloud.optional_markers)
        familiar = _matching_terms(
            sentence, active.cloud.exposure_markers
        )
        if mandatory and not soft:
            return CloudAssessment(
                "required_core",
                tuple(dict.fromkeys((*sentence_technologies, *mandatory))),
            )
        if soft:
            optional.extend((*sentence_technologies, *soft))
        elif familiar:
            exposure.extend((*sentence_technologies, *familiar))

    if optional:
        return CloudAssessment("nice_to_have", tuple(dict.fromkeys(optional)))
    if exposure:
        return CloudAssessment("exposure", tuple(dict.fromkeys(exposure)))
    return CloudAssessment("unclear", technologies)


def assess_cloud_candidate(
    candidate: CandidateItem,
    policy: JobSearchPolicy | None = None,
) -> CloudAssessment:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    text = " ".join(
        [
            candidate.title,
            candidate.summary,
            candidate.content,
            str(raw.get("required_skills") or ""),
            str(raw.get("requirements") or ""),
        ]
    )
    return assess_cloud_text(text, policy)
```

Extend `JobSearchPolicy`, its loader, and its required-key validation with `source_stage_order` and `cloud`. Extend `JobPolicyMatch` with defaulted `cloud_requirement` and `cloud_evidence` fields. In `evaluate_job_text`, assess cloud after role/domain evidence is established and return `reject_reason="cloud-required-core"` when the assessment is `required_core`; preserve the cloud fields on both accepted and rejected matches. Add the cloud rules to `policy_prompt_fragment`.

- [ ] **Step 4: Run policy tests and verify they pass**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
```

Expected: PASS, including the original policy validation and standalone-prompt assertions.

- [ ] **Step 5: Commit the policy slice**

```bash
git add config/job_search_policy.json news_keep_up/job_search_policy.py tests/test_job_search_policy.py
git commit -m "feat(jobs): classify mandatory and optional cloud work"
```

### Task 2: Persist Cloud Assessment Additively

**Files:**
- Modify: `news_keep_up/models.py`
- Modify: `news_keep_up/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: Task 1 cloud requirement enum values.
- Extends: `JobOpportunity.cloud_requirement: str = "unclear"`
- Extends: `JobOpportunity.cloud_evidence: list[str]`
- Preserves: existing constructor call sites through default values.
- Produces: SQLite/Turso additive columns and round-trip database support.

- [ ] **Step 1: Write failing model and database tests**

Add these tests to `tests/test_db.py` and import `sqlite3`, `_ensure_columns`, and `_job_opportunity_from_row` only if required by the test module:

```python
def test_cloud_requirement_is_material_but_evidence_wording_is_not(self):
    original = JobOpportunity(
        **{
            **make_job_opportunity().__dict__,
            "cloud_requirement": "unclear",
            "cloud_evidence": ["AWS"],
        }
    )
    optional = JobOpportunity(
        **{
            **original.__dict__,
            "cloud_requirement": "nice_to_have",
            "cloud_evidence": ["AWS", "preferred"],
        }
    )
    reworded = JobOpportunity(
        **{
            **optional.__dict__,
            "cloud_evidence": ["Amazon Web Services", "preferred"],
        }
    )

    self.assertNotEqual(original.alert_fingerprint, optional.alert_fingerprint)
    self.assertEqual(optional.alert_fingerprint, reworded.alert_fingerprint)


def test_job_opportunity_cloud_fields_round_trip(self):
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
        init_db(conn)
        item_id, _ = upsert_item(conn, make_item())
        opportunity = JobOpportunity(
            **{
                **make_job_opportunity().__dict__,
                "source_item_id": item_id,
                "cloud_requirement": "exposure",
                "cloud_evidence": ["azure", "familiarity"],
            }
        )
        upsert_job_opportunity(conn, opportunity)

        loaded = list_pending_job_alerts(conn)[0]
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(job_opportunities)"
            ).fetchall()
        }
        conn.close()

    self.assertEqual(loaded.cloud_requirement, "exposure")
    self.assertEqual(loaded.cloud_evidence, ["azure", "familiarity"])
    self.assertIn("cloud_requirement", columns)
    self.assertIn("cloud_evidence", columns)
```

- [ ] **Step 2: Run database tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_db.py' -v
```

Expected: FAIL because `JobOpportunity` and the database schema do not contain cloud fields.

- [ ] **Step 3: Add model fields and database migration/read/write support**

Append these defaulted fields to `JobOpportunity` in `news_keep_up/models.py`:

```python
cloud_requirement: str = "unclear"
cloud_evidence: list[str] = field(default_factory=list)
```

Add this material part to `alert_fingerprint` and deliberately omit evidence text:

```python
f"cloud={self.cloud_requirement}",
```

Add columns to the `CREATE TABLE` statement and `_ensure_columns` map in `news_keep_up/db.py`:

```python
"cloud_requirement": "TEXT NOT NULL DEFAULT 'unclear'",
"cloud_evidence": "TEXT NOT NULL DEFAULT '[]'",
```

Update every `job_opportunities` insert, update, select, search, row-index mapping, and raw JSON dictionary consistently. Serialize evidence with:

```python
json.dumps(opportunity.cloud_evidence, ensure_ascii=True)
```

Deserialize it with the existing `_json_list` helper. Include both fields in job search; add two matching `lower(...) LIKE ?` clauses and two corresponding patterns. Keep the new columns adjacent after `domain` in SQL select lists and use the same ordering in `_job_opportunity_from_row`.

- [ ] **Step 4: Run database and direct dependent tests**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_db.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
```

Expected: PASS. Existing constructors continue working because both new fields have defaults.

- [ ] **Step 5: Commit the persistence slice**

```bash
git add news_keep_up/models.py news_keep_up/db.py tests/test_db.py
git commit -m "feat(jobs): persist cloud-fit assessment"
```

### Task 3: Source Identity, Staged Fetching, and Fair Candidate Allocation

**Files:**
- Modify: `news_keep_up/job_search_policy.py`
- Modify: `news_keep_up/job_alerts.py`
- Modify: `news_keep_up/gemini.py`
- Test: `tests/test_job_search_policy.py`
- Test: `tests/test_job_alerts.py`
- Test: `tests/test_gemini.py`

**Interfaces:**
- Produces: `job_source_type(candidate: CandidateItem) -> str`
- Produces: `configured_source_stage(source: Source) -> int`
- Produces: `source_stage_priority(source_type: str, policy: JobSearchPolicy | None = None) -> int`
- Produces: `_allocate_job_candidates(candidates: list[tuple[int, CandidateItem]], limit: int) -> list[tuple[int, CandidateItem]]`
- Replaces: Gemini's independent `_source_type_hint` logic with the shared policy function.

- [ ] **Step 1: Write failing source-type and allocation tests**

Add to `tests/test_job_search_policy.py`:

```python
from news_keep_up.job_search_policy import (
    configured_source_stage,
    job_source_type,
    source_stage_priority,
)
from news_keep_up.models import CandidateItem, Source


def test_linkedin_candidate_url_overrides_aggregator_metadata(self):
    post = CandidateItem(
        source_name="Bing LinkedIn Search",
        source_kind="rss",
        source_category="linkedin-hidden-hiring-search",
        title="We are hiring a Forward Deployed Engineer",
        url="https://www.linkedin.com/posts/recruiter_fde-hiring-activity-1",
        canonical_url="https://www.linkedin.com/posts/recruiter_fde-hiring-activity-1",
        raw={"source_type": "aggregator"},
    )
    job = CandidateItem(
        source_name="Bing LinkedIn Search",
        source_kind="rss",
        source_category="linkedin-job-search",
        title="Forward Deployed Engineer",
        url="https://www.linkedin.com/jobs/view/1234567890/",
        canonical_url="https://www.linkedin.com/jobs/view/1234567890/",
        raw={"source_type": "aggregator"},
    )

    self.assertEqual(job_source_type(post), "LinkedIn_post")
    self.assertEqual(job_source_type(job), "LinkedIn_job")
    self.assertLess(
        source_stage_priority("LinkedIn_post"),
        source_stage_priority("LinkedIn_job"),
    )


def test_encoded_linkedin_query_is_fetched_in_the_correct_stage(self):
    source = Source(
        "Bing LinkedIn Expanded Posts",
        "rss",
        "https://www.bing.com/search?q=site%3Alinkedin.com%2Fposts+FDE&format=rss",
        "linkedin-hidden-hiring-search",
        metadata={"source_type": "aggregator"},
    )

    self.assertEqual(configured_source_stage(source), 0)
```

Add this helper and test to `tests/test_job_alerts.py`:

```python
from news_keep_up.job_alerts import _allocate_job_candidates


def staged_candidate(index: int, source_type: str) -> tuple[int, CandidateItem]:
    if source_type == "LinkedIn_post":
        url = f"https://www.linkedin.com/posts/fixture-{index}"
    elif source_type == "LinkedIn_job":
        url = f"https://www.linkedin.com/jobs/view/fixture-{index}"
    else:
        url = f"https://jobs.ashbyhq.com/example/fixture-{index}"
    return (
        index,
        CandidateItem(
            source_name=f"Fixture {source_type}",
            source_kind="rss",
            source_category="fde-job-search",
            title=f"Senior Forward Deployed Engineer {index}",
            url=url,
            canonical_url=url,
            summary="Enterprise AI customer deployment in Remote APAC.",
            fingerprint=f"fixture-{index}",
            raw={"source_type": source_type, "location": "Remote APAC"},
        ),
    )


def test_candidate_allocation_reserves_posts_jobs_and_other_sources(self):
    candidates = [
        *(staged_candidate(index, "LinkedIn_post") for index in range(1, 11)),
        *(staged_candidate(index, "LinkedIn_job") for index in range(11, 21)),
        *(staged_candidate(index, "ATS") for index in range(21, 31)),
    ]

    selected = _allocate_job_candidates(candidates, limit=10)
    selected_types = [job_source_type(candidate) for _, candidate in selected]

    self.assertEqual(selected_types.count("LinkedIn_post"), 4)
    self.assertEqual(selected_types.count("LinkedIn_job"), 3)
    self.assertEqual(len(selected_types), 10)
    self.assertEqual(selected_types[0], "LinkedIn_post")


def test_new_job_candidates_fetches_post_stage_before_job_stage(self):
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            db_path=Path(tmp) / "test.db",
            max_source_workers=1,
            max_llm_items_per_run=3,
        )
        conn = connect_database(settings)
        init_db(conn)
        sources = [
            Source(
                "LinkedIn Jobs Query",
                "rss",
                "https://www.bing.com/search?q=site%3Alinkedin.com%2Fjobs+FDE",
                "linkedin-job-search",
                metadata={"source_type": "LinkedIn_job"},
            ),
            Source(
                "LinkedIn Posts Query",
                "rss",
                "https://www.bing.com/search?q=site%3Alinkedin.com%2Fposts+FDE",
                "linkedin-hidden-hiring-search",
                metadata={"source_type": "LinkedIn_post"},
            ),
        ]
        seen: list[str] = []

        def fetch_in_order(source, user_agent, timeout_seconds):
            seen.append(source.name)
            return []

        with patch("news_keep_up.job_alerts.fetch_source", side_effect=fetch_in_order):
            _new_job_candidates(conn, settings, sources)
        conn.close()

    self.assertEqual(seen, ["LinkedIn Posts Query", "LinkedIn Jobs Query"])
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
```

Expected: FAIL because shared source-stage and candidate-allocation functions do not exist.

- [ ] **Step 3: Implement shared source identity and staged allocation**

Add these functions to `news_keep_up/job_search_policy.py`:

```python
def _source_type_from_url(url: str) -> str:
    lowered = str(url or "").lower()
    if "linkedin.com/posts" in lowered:
        return "LinkedIn_post"
    if "linkedin.com/jobs" in lowered:
        return "LinkedIn_job"
    if any(
        host in lowered
        for host in (
            "ashbyhq.com",
            "greenhouse.io",
            "lever.co",
            "workable.com",
            "teamtailor.com",
            "recruitee.com",
        )
    ):
        return "ATS"
    return ""


def job_source_type(candidate: CandidateItem) -> str:
    url_type = _source_type_from_url(
        candidate.canonical_url or candidate.url
    )
    if url_type:
        return url_type
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    configured = str(raw.get("source_type") or "").strip()
    if configured:
        return configured
    combined = f"{candidate.source_name} {candidate.source_category}".lower()
    if "linkedin" in combined and "post" in combined:
        return "LinkedIn_post"
    if "linkedin" in combined and "job" in combined:
        return "LinkedIn_job"
    if "career" in combined:
        return "official_career_page"
    return "job_board"


def source_stage_priority(
    source_type: str,
    policy: JobSearchPolicy | None = None,
) -> int:
    order = (policy or load_job_search_policy()).source_stage_order
    try:
        return order.index(source_type)
    except ValueError:
        return len(order)


def configured_source_stage(source: Source) -> int:
    raw_type = str((source.metadata or {}).get("source_type") or "")
    decoded = unquote(source.url).lower()
    combined = f"{source.name} {source.category} {decoded}".lower()
    if "linkedin.com/posts" in combined or (
        "linkedin" in combined and "post" in combined
    ):
        return source_stage_priority("LinkedIn_post")
    if "linkedin.com/jobs" in combined or (
        "linkedin" in combined and "job" in combined
    ):
        return source_stage_priority("LinkedIn_job")
    return source_stage_priority(raw_type or "aggregator")
```

Import `unquote`, `Source`, and `CandidateItem` as needed. Make Gemini's `_source_type_hint` return `job_source_type(item)` so the model and local ordering share one answer.

Refactor `_new_job_candidates` in `news_keep_up/job_alerts.py` to collect all eligible, URL-deduped candidates before applying the global cap. Fetch configured source-stage groups in ascending stage order, retaining concurrency inside each call to `_fetch_candidates`.

Implement exact 40/30/30 allocation with unused-slot reclamation:

```python
def _allocate_job_candidates(
    candidates: list[tuple[int, CandidateItem]],
    limit: int,
) -> list[tuple[int, CandidateItem]]:
    bounded = max(1, limit)
    ordered = sorted(
        candidates,
        key=lambda pair: (
            source_stage_priority(job_source_type(pair[1])),
            -_job_candidate_score(pair[1]),
        ),
    )
    buckets = {
        "posts": [
            pair for pair in ordered
            if job_source_type(pair[1]) == "LinkedIn_post"
        ],
        "jobs": [
            pair for pair in ordered
            if job_source_type(pair[1]) == "LinkedIn_job"
        ],
        "other": [
            pair for pair in ordered
            if job_source_type(pair[1])
            not in {"LinkedIn_post", "LinkedIn_job"}
        ],
    }
    targets = {
        "posts": int(bounded * 0.4),
        "jobs": int(bounded * 0.3),
    }
    targets["other"] = bounded - targets["posts"] - targets["jobs"]
    populated = [name for name, rows in buckets.items() if rows]
    if bounded >= len(populated):
        for name in populated:
            if targets[name] > 0:
                continue
            donor = max(targets, key=targets.get)
            targets[donor] -= 1
            targets[name] = 1

    quotas = {
        name: min(targets[name], len(buckets[name]))
        for name in buckets
    }
    remaining = bounded - sum(quotas.values())
    while remaining > 0:
        advanced = False
        for name in ("posts", "jobs", "other"):
            if quotas[name] >= len(buckets[name]):
                continue
            quotas[name] += 1
            remaining -= 1
            advanced = True
            if remaining == 0:
                break
        if not advanced:
            break

    selected: list[tuple[int, CandidateItem]] = []
    selected_keys: set[str] = set()
    for name in ("posts", "jobs", "other"):
        for pair in buckets[name][:quotas[name]]:
            selected.append(pair)
            selected_keys.add(pair[1].canonical_url or pair[1].url)
    if len(selected) < bounded:
        for pair in ordered:
            key = pair[1].canonical_url or pair[1].url
            if key in selected_keys:
                continue
            selected.append(pair)
            selected_keys.add(key)
            if len(selected) == bounded:
                break
    return sorted(
        selected,
        key=lambda pair: (
            source_stage_priority(job_source_type(pair[1])),
            -_job_candidate_score(pair[1]),
        ),
    )
```

- [ ] **Step 4: Run source, Gemini, and alert tests**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
```

Expected: PASS. Existing URL deduplication and per-source limits remain intact.

- [ ] **Step 5: Commit the source-staging slice**

```bash
git add news_keep_up/job_search_policy.py news_keep_up/job_alerts.py news_keep_up/gemini.py tests/test_job_search_policy.py tests/test_job_alerts.py tests/test_gemini.py
git commit -m "feat(jobs): prioritize LinkedIn posts before jobs"
```

### Task 4: Link Status, Freshness, and Cross-Source Reconciliation

**Files:**
- Create: `news_keep_up/job_verification.py`
- Create: `tests/test_job_verification.py`

**Interfaces:**
- Consumes: `JobOpportunity`, `job_source_type`, and source-type ordering from Tasks 2 and 3.
- Produces: `LinkVerification(state: str, final_url: str, target_source_type: str, reason: str)`
- Produces: `verify_opportunity_link(opportunity: JobOpportunity, user_agent: str, timeout_seconds: int, opener=urlopen) -> LinkVerification`
- Produces: `apply_link_and_freshness(opportunity: JobOpportunity, verification: LinkVerification, current: datetime) -> JobOpportunity | None`
- Produces: `reconcile_job_opportunities(opportunities: list[JobOpportunity]) -> list[JobOpportunity]`

- [ ] **Step 1: Write failing isolated verification tests**

Create `tests/test_job_verification.py` with deterministic fake responses:

```python
import unittest
from datetime import datetime
from io import BytesIO
from urllib.error import HTTPError, URLError

from news_keep_up.job_verification import (
    LinkVerification,
    apply_link_and_freshness,
    reconcile_job_opportunities,
    verify_opportunity_link,
)
from news_keep_up.models import JobOpportunity
from news_keep_up.utils import ICT


def make_opportunity(**overrides) -> JobOpportunity:
    values = {
        "id": "example-fde",
        "source_item_id": 1,
        "source_fingerprint": "fp-1",
        "crawled_at": "2026-08-11",
        "priority": "High",
        "company": "Example",
        "role_title": "Forward Deployed Engineer",
        "category": "Forward Deployed Engineering",
        "location": "Remote APAC",
        "remote_policy": "Remote",
        "vietnam_eligibility": "verify",
        "evidence_type": "Medium",
        "status": "uncertain",
        "posted_date": "2026-08-10T00:00:00+00:00",
        "source_type": "LinkedIn_post",
        "source_url": "https://www.linkedin.com/posts/recruiter_fde-1",
        "apply_url": "",
        "contact_person": "",
        "contact_url": "",
        "why_it_fits": "Customer AI deployment.",
        "recommended_action": "dm_first",
        "confidence_score": 80,
        "should_alert": True,
    }
    values.update(overrides)
    return JobOpportunity(**values)


class FakeResponse:
    def __init__(self, body: str, url: str, status: int = 200):
        self._body = BytesIO(body.encode("utf-8"))
        self._url = url
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1):
        return self._body.read(size)

    def geturl(self):
        return self._url


class JobVerificationTest(unittest.TestCase):
    def test_official_open_closed_and_login_wall_states(self):
        open_job = make_opportunity(
            apply_url="https://jobs.ashbyhq.com/example/123"
        )
        open_result = verify_opportunity_link(
            open_job,
            "test-agent",
            1,
            opener=lambda request, timeout: FakeResponse(
                "Job details Apply for this job",
                "https://jobs.ashbyhq.com/example/123",
            ),
        )
        closed_result = verify_opportunity_link(
            open_job,
            "test-agent",
            1,
            opener=lambda request, timeout: FakeResponse(
                "This job is no longer accepting applications",
                "https://jobs.ashbyhq.com/example/123",
            ),
        )
        linkedin = make_opportunity()
        blocked_result = verify_opportunity_link(
            linkedin,
            "test-agent",
            1,
            opener=lambda request, timeout: FakeResponse(
                "Sign in to LinkedIn authwall",
                linkedin.source_url,
            ),
        )

        self.assertEqual(open_result.state, "open")
        self.assertEqual(closed_result.state, "closed")
        self.assertEqual(blocked_result.state, "uncertain")

    def test_http_404_is_closed_but_network_failure_is_uncertain(self):
        opportunity = make_opportunity()

        def not_found(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)

        def network_error(request, timeout):
            raise URLError("timed out")

        self.assertEqual(
            verify_opportunity_link(
                opportunity, "test-agent", 1, opener=not_found
            ).state,
            "closed",
        )
        self.assertEqual(
            verify_opportunity_link(
                opportunity, "test-agent", 1, opener=network_error
            ).state,
            "uncertain",
        )

    def test_old_linkedin_post_requires_live_official_apply_url(self):
        current = datetime(2026, 8, 11, 9, 0, tzinfo=ICT)
        old_post = make_opportunity(posted_date="2026-06-01")
        blocked = LinkVerification(
            "uncertain", old_post.source_url, "LinkedIn_post", "authwall"
        )
        official = LinkVerification(
            "open",
            "https://jobs.ashbyhq.com/example/123",
            "ATS",
            "explicit-open-marker",
        )

        self.assertIsNone(
            apply_link_and_freshness(old_post, blocked, current)
        )
        retained = apply_link_and_freshness(
            JobOpportunity(
                **{
                    **old_post.__dict__,
                    "apply_url": official.final_url,
                }
            ),
            official,
            current,
        )
        self.assertIsNotNone(retained)
        self.assertEqual(retained.status, "open")

    def test_reconciliation_preserves_post_and_prefers_official_apply_url(self):
        post = make_opportunity(linkedin_post_signal="Recruiter is hiring")
        official = make_opportunity(
            id="example-fde-official",
            source_item_id=2,
            source_type="ATS",
            source_url="https://jobs.ashbyhq.com/example/123",
            apply_url="https://jobs.ashbyhq.com/example/123",
            status="likely_open",
            recommended_action="verify_first",
        )

        merged = reconcile_job_opportunities([official, post])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_type, "LinkedIn_post")
        self.assertEqual(merged[0].source_url, post.source_url)
        self.assertEqual(merged[0].apply_url, official.apply_url)
```

- [ ] **Step 2: Run the new verification test and verify it fails**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_verification.py' -v
```

Expected: FAIL because `news_keep_up.job_verification` does not exist.

- [ ] **Step 3: Implement bounded link verification, freshness, and reconciliation**

Create `news_keep_up/job_verification.py` with these constants and interfaces:

```python
from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError

from .job_search_policy import source_stage_priority
from .models import JobOpportunity
from .utils import clean_text


CLOSED_MARKERS = (
    "job is no longer accepting applications",
    "position has been filled",
    "job has expired",
    "job is closed",
    "no longer available",
)
OPEN_MARKERS = (
    "apply for this job",
    "apply now",
    "submit application",
)
ACCESS_MARKERS = (
    "sign in to linkedin",
    "authwall",
    "captcha",
    "verify you are human",
    "too many requests",
)
ATS_HOSTS = (
    "ashbyhq.com",
    "greenhouse.io",
    "lever.co",
    "workable.com",
    "teamtailor.com",
    "recruitee.com",
)


@dataclass(frozen=True)
class LinkVerification:
    state: str
    final_url: str
    target_source_type: str
    reason: str


def _url_source_type(url: str, fallback: str) -> str:
    lowered = str(url or "").lower()
    if "linkedin.com/posts" in lowered:
        return "LinkedIn_post"
    if "linkedin.com/jobs" in lowered:
        return "LinkedIn_job"
    if any(host in lowered for host in ATS_HOSTS):
        return "ATS"
    if "/career" in lowered or "/jobs" in lowered:
        return "official_career_page"
    return fallback


def verify_opportunity_link(
    opportunity: JobOpportunity,
    user_agent: str,
    timeout_seconds: int,
    opener=urllib.request.urlopen,
) -> LinkVerification:
    target = opportunity.apply_url or opportunity.source_url
    request = urllib.request.Request(target, headers={"User-Agent": user_agent})
    try:
        with opener(request, timeout=max(1, timeout_seconds)) as response:
            final_url = response.geturl() or target
            body = response.read(262_144).decode("utf-8", errors="replace")
    except HTTPError as exc:
        state = "closed" if exc.code in {404, 410} else "uncertain"
        return LinkVerification(
            state, target, _url_source_type(target, opportunity.source_type),
            f"http-{exc.code}",
        )
    except (URLError, TimeoutError, OSError) as exc:
        return LinkVerification(
            "uncertain",
            target,
            _url_source_type(target, opportunity.source_type),
            type(exc).__name__,
        )

    lowered = clean_text(body).lower()
    target_type = _url_source_type(final_url, opportunity.source_type)
    if any(marker in lowered for marker in CLOSED_MARKERS):
        return LinkVerification("closed", final_url, target_type, "closed-marker")
    if any(marker in lowered for marker in ACCESS_MARKERS):
        return LinkVerification("uncertain", final_url, target_type, "access-wall")
    if target_type in {"ATS", "official_career_page"}:
        if any(marker in lowered for marker in OPEN_MARKERS):
            return LinkVerification("open", final_url, target_type, "open-marker")
        return LinkVerification(
            "likely_open", final_url, target_type, "live-job-page"
        )
    return LinkVerification("uncertain", final_url, target_type, "no-open-proof")
```

Implement date parsing with ISO-8601 first and RFC-2822 second. `apply_link_and_freshness` must:

- return `None` for `closed`;
- append missing posting date, uncertain status, and cloud/location verification without duplicates;
- force `recommended_action="verify_first"` for uncertain links unless the item is a post-only `dm_first` signal;
- reject a LinkedIn Post older than 30 days unless `verification.target_source_type` is `ATS` or `official_career_page` and state is `open` or `likely_open`;
- retain an old Job only under the same live official-source condition;
- preserve the original `posted_date` and set status from verified evidence.

Use this exact helper for age calculation:

```python
def _posted_age_days(value: str, current: datetime) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=current.tzinfo)
    return max(0, (current - parsed.astimezone(current.tzinfo)).days)
```

Implement freshness and conservative action downgrades with this shape:

```python
def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def apply_link_and_freshness(
    opportunity: JobOpportunity,
    verification: LinkVerification,
    current: datetime,
) -> JobOpportunity | None:
    if verification.state == "closed":
        return None
    age = _posted_age_days(opportunity.posted_date, current)
    official_live = (
        verification.target_source_type in {"ATS", "official_career_page"}
        and verification.state in {"open", "likely_open"}
    )
    if age is not None and age > 30 and not official_live:
        return None

    verify = list(opportunity.what_to_verify)
    if not opportunity.posted_date:
        verify.append("Posting date")
    if verification.state == "uncertain":
        verify.append("Open/closing status")
    action = opportunity.recommended_action
    if verification.state == "uncertain" and action == "apply_now":
        action = "verify_first"
    status = (
        verification.state
        if verification.state in {"open", "likely_open"}
        else "uncertain"
    )
    apply_url = opportunity.apply_url
    if verification.target_source_type in {"ATS", "official_career_page"}:
        apply_url = verification.final_url
    return replace(
        opportunity,
        apply_url=apply_url,
        status=status,
        recommended_action=action,
        what_to_verify=_unique(verify),
    )
```

Implement `reconcile_job_opportunities` with a conservative entity key consisting of normalized non-empty company, title, and location. For each group, choose a LinkedIn Post as the base when present, otherwise the lowest source-stage item; copy the best ATS/official URL to `apply_url`; union verification lists, skills, domain, and cloud evidence without reordering the base's source URL. Items missing any entity-key component remain separate. Use these exact normalization and merge helpers:

```python
def _entity_key(opportunity: JobOpportunity) -> str:
    company = " ".join(opportunity.company.casefold().split())
    title = " ".join(
        opportunity.role_title.casefold().replace("sr.", "senior").split()
    )
    location = " ".join(opportunity.location.casefold().split())
    if not company or not title or not location:
        return ""
    return f"{company}|{title}|{location}"


def _merge_group(group: list[JobOpportunity]) -> JobOpportunity:
    base = min(
        group,
        key=lambda item: (
            0 if item.source_type == "LinkedIn_post" else 1,
            source_stage_priority(item.source_type),
            -item.confidence_score,
        ),
    )
    post = next(
        (item for item in group if item.source_type == "LinkedIn_post"),
        None,
    )
    official_rows = [
        item for item in group
        if item.source_type in {"ATS", "official_career_page"}
    ]
    official = min(
        official_rows,
        key=lambda item: (
            source_stage_priority(item.source_type),
            -item.confidence_score,
        ),
        default=None,
    )
    cloud = max(
        group,
        key=lambda item: {
            "required_core": 4,
            "unclear": 3,
            "nice_to_have": 2,
            "exposure": 2,
            "not_mentioned": 1,
        }.get(item.cloud_requirement, 3),
    )
    eligibility = min(
        group,
        key=lambda item: {
            "explicit_yes": 0,
            "likely_possible": 1,
            "verify": 2,
            "unlikely": 3,
            "no": 4,
        }.get(item.vietnam_eligibility, 2),
    )
    return replace(
        base,
        source_type="LinkedIn_post" if post else base.source_type,
        source_url=post.source_url if post else base.source_url,
        apply_url=(
            (official.apply_url or official.source_url)
            if official
            else base.apply_url
        ),
        linkedin_post_signal=(
            post.linkedin_post_signal if post else base.linkedin_post_signal
        ),
        vietnam_eligibility=eligibility.vietnam_eligibility,
        cloud_requirement=cloud.cloud_requirement,
        what_to_verify=_unique(
            [value for item in group for value in item.what_to_verify]
        ),
        required_skills=_unique(
            [value for item in group for value in item.required_skills]
        ),
        domain=_unique([value for item in group for value in item.domain]),
        cloud_evidence=_unique(
            [value for item in group for value in item.cloud_evidence]
        ),
        confidence_score=max(item.confidence_score for item in group),
    )


def reconcile_job_opportunities(
    opportunities: list[JobOpportunity],
) -> list[JobOpportunity]:
    groups: dict[str, list[JobOpportunity]] = {}
    separate: list[JobOpportunity] = []
    for opportunity in opportunities:
        key = _entity_key(opportunity)
        if not key:
            separate.append(opportunity)
            continue
        groups.setdefault(key, []).append(opportunity)
    merged = [*separate, *(_merge_group(group) for group in groups.values())]
    return sorted(
        merged,
        key=lambda item: (
            source_stage_priority(item.source_type),
            -item.confidence_score,
        ),
    )
```

- [ ] **Step 4: Run verification tests and static syntax checks**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_verification.py' -v
python3 -m compileall -q news_keep_up
```

Expected: PASS with no network access because tests inject an opener.

- [ ] **Step 5: Commit the verification slice**

```bash
git add news_keep_up/job_verification.py tests/test_job_verification.py
git commit -m "feat(jobs): verify job links and freshness"
```

### Task 5: APAC Country-Locked Auxiliary Opportunities

**Files:**
- Modify: `news_keep_up/job_filters.py`
- Test: `tests/test_job_alerts.py`

**Interfaces:**
- Produces: `is_apac_country_locked_candidate(candidate: CandidateItem) -> bool`
- Produces: `is_apac_country_locked_opportunity(opportunity: JobOpportunity) -> bool`
- Changes: Vietnam workability returns `unlikely` for explicit APAC country locks and `no` for non-APAC locks.
- Consumed later by: Gemini post-validation and database ordering.

- [ ] **Step 1: Write failing APAC and non-APAC location tests**

Add these tests to `tests/test_job_alerts.py` and import the new helpers:

```python
def test_apac_country_lock_is_auxiliary_but_non_apac_lock_is_rejected(self):
    singapore = CandidateItem(
        source_name="LinkedIn Jobs",
        source_kind="rss",
        source_category="linkedin-job-search",
        title="Senior Forward Deployed Engineer",
        url="https://www.linkedin.com/jobs/view/100/",
        canonical_url="https://www.linkedin.com/jobs/view/100/",
        summary="Enterprise AI customer deployment. Remote within Singapore only.",
        raw={"location": "Singapore", "remote_policy": "Remote Singapore only"},
    )
    united_states = CandidateItem(
        source_name="LinkedIn Jobs",
        source_kind="rss",
        source_category="linkedin-job-search",
        title="Senior Forward Deployed Engineer",
        url="https://www.linkedin.com/jobs/view/200/",
        canonical_url="https://www.linkedin.com/jobs/view/200/",
        summary="Enterprise AI customer deployment. Remote US only.",
        raw={"location": "United States", "remote_policy": "Remote US only"},
    )

    self.assertEqual(vietnam_workability_for_candidate(singapore), "unlikely")
    self.assertTrue(is_workable_from_vietnam_candidate(singapore))
    self.assertEqual(vietnam_workability_for_candidate(united_states), "no")
    self.assertFalse(is_workable_from_vietnam_candidate(united_states))


def test_apac_country_lock_with_relocation_remains_likely_possible(self):
    singapore = CandidateItem(
        source_name="Official Careers",
        source_kind="html",
        source_category="company-careers",
        title="Senior AI Deployment Engineer",
        url="https://example.com/careers/ai-deployment",
        canonical_url="https://example.com/careers/ai-deployment",
        summary="Onsite Singapore with visa sponsorship and relocation assistance. "
        "Enterprise AI customer implementation.",
        raw={"location": "Singapore", "remote_policy": "Onsite"},
    )

    self.assertEqual(
        vietnam_workability_for_candidate(singapore), "likely_possible"
    )
```

- [ ] **Step 2: Run alert tests and verify the APAC case fails**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
```

Expected: FAIL because Singapore currently maps directly to `no`.

- [ ] **Step 3: Implement explicit APAC country-lock detection**

Split current location terms into exact regional tuples in `news_keep_up/job_filters.py`:

```python
APAC_COUNTRY_TERMS = (
    "singapore",
    "malaysia",
    "thailand",
    "indonesia",
    "philippines",
    "hong kong",
    "taiwan",
    "japan",
    "korea",
    "australia",
    "india",
)

NON_APAC_COUNTRY_TERMS = (
    "united states",
    "usa",
    "u.s.",
    "canada",
    "united kingdom",
    "germany",
    "france",
    "serbia",
    "poland",
    "czech",
    "europe",
    "emea",
    "latam",
    "latin america",
    "brazil",
    "portugal",
    "sweden",
)
```

Detect explicit country lock only when a country term appears with `only`, `must be based`, `based in`, `residents`, `work authorization`, `onsite`, or a non-regional location without Vietnam/global/relocation evidence. Apply checks in this order: explicit remote exclusion, disallowed employment, explicit Vietnam, relocation, regional remote, APAC country lock, non-APAC country lock, unknown remote.

Return `unlikely` for APAC country lock. Update `is_workable_from_vietnam_candidate` and `is_workable_from_vietnam_opportunity` to accept `unlikely` and reject only `no`. Add exact public helpers that reuse the normalized text and return true when the workability result is `unlikely`.

- [ ] **Step 4: Run location and alert regressions**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
```

Expected: PASS. Existing US, EMEA, LATAM, part-time, Vietnam, APAC-wide, and relocation cases retain their original decisions except for the newly approved APAC country-lock auxiliary state.

- [ ] **Step 5: Commit the location slice**

```bash
git add news_keep_up/job_filters.py tests/test_job_alerts.py
git commit -m "feat(jobs): retain APAC country-locked leads"
```

### Task 6: Gemini Contract and Deterministic Fallback Parity

**Files:**
- Modify: `news_keep_up/gemini.py`
- Test: `tests/test_gemini.py`

**Interfaces:**
- Consumes: Task 1 `assess_cloud_candidate`, Task 2 model fields, Task 3 source identity, and Task 5 workability.
- Extends: `build_job_classification_prompt` with cloud and source-stage evidence.
- Extends: `_job_opportunity_from_row` cloud parsing.
- Enforces: `validate_job_opportunity(opportunity, candidate) -> JobOpportunity | None` local hard rules.
- Preserves: `fallback_job_opportunities` behavior while adding cloud/source/location parity.

- [ ] **Step 1: Write failing Gemini prompt, parse, validation, and fallback tests**

Add `validate_job_opportunity` to the existing `news_keep_up.gemini` imports, add `JobOpportunity` to the existing model imports, then add this exact helper and the focused tests to `tests/test_gemini.py`:

```python
def make_job_opportunity(**overrides) -> JobOpportunity:
    values = {
        "id": "example-forward-deployed-engineer",
        "source_item_id": 1,
        "source_fingerprint": "example-fingerprint",
        "crawled_at": "2026-08-11",
        "priority": "High",
        "company": "Example",
        "role_title": "Senior Forward Deployed Engineer",
        "category": "Forward Deployed Engineering",
        "location": "Vietnam",
        "remote_policy": "Remote Vietnam",
        "vietnam_eligibility": "explicit_yes",
        "evidence_type": "Hard",
        "status": "open",
        "posted_date": "2026-08-10",
        "source_type": "official_career_page",
        "source_url": "https://example.com/jobs/fde",
        "apply_url": "https://example.com/jobs/fde",
        "contact_person": "",
        "contact_url": "",
        "why_it_fits": "Enterprise AI customer deployment and API integration.",
        "what_to_verify": [],
        "required_seniority": "Senior",
        "required_skills": ["Python", "APIs"],
        "domain": ["enterprise ai"],
        "recommended_action": "apply_now",
        "confidence_score": 90,
        "should_alert": True,
    }
    values.update(overrides)
    return JobOpportunity(**values)


def test_job_prompt_requests_cloud_contract_and_post_first_source_type(self):
    candidate = CandidateItem(
        source_name="Bing LinkedIn",
        source_kind="rss",
        source_category="linkedin-hidden-hiring-search",
        title="Forward Deployed Software Engineer",
        url="https://www.linkedin.com/posts/recruiter_hiring-1",
        canonical_url="https://www.linkedin.com/posts/recruiter_hiring-1",
        summary="Enterprise AI customer implementation. AWS is preferred.",
        raw={"source_type": "aggregator"},
    )

    prompt = build_job_classification_prompt([(7, candidate)], "2026-08-11")

    self.assertIn("cloud_requirement", prompt)
    self.assertIn("cloud_evidence", prompt)
    self.assertIn("required_core", prompt)
    self.assertIn('"source_type_hint": "LinkedIn_post"', prompt)


def test_local_validation_rejects_mandatory_cloud_even_if_model_accepts(self):
    candidate = CandidateItem(
        source_name="LinkedIn Jobs",
        source_kind="rss",
        source_category="linkedin-job-search",
        title="Senior Forward Deployed Engineer",
        url="https://www.linkedin.com/jobs/view/123/",
        canonical_url="https://www.linkedin.com/jobs/view/123/",
        summary="Enterprise AI deployment. Must operate Kubernetes clusters.",
        raw={"location": "Vietnam", "source_type": "LinkedIn_job"},
    )
    accepted = make_job_opportunity(
        cloud_requirement="not_mentioned",
        cloud_evidence=[],
    )

    self.assertIsNone(validate_job_opportunity(accepted, candidate))


def test_optional_cloud_is_locally_corrected_and_remains_alertable(self):
    candidate = CandidateItem(
        source_name="Official Careers",
        source_kind="html",
        source_category="company-careers",
        title="Senior AI Deployment Engineer",
        url="https://example.com/jobs/ai-deployment",
        canonical_url="https://example.com/jobs/ai-deployment",
        summary="Enterprise AI customer deployment in Vietnam. AWS is preferred.",
        raw={"location": "Vietnam", "source_type": "official_career_page"},
    )
    model_row = make_job_opportunity(
        cloud_requirement="unclear",
        cloud_evidence=[],
    )

    validated = validate_job_opportunity(model_row, candidate)

    self.assertIsNotNone(validated)
    self.assertEqual(validated.cloud_requirement, "nice_to_have")
    self.assertIn("aws", validated.cloud_evidence)
    self.assertTrue(validated.should_alert)


def test_fallback_marks_unclear_cloud_and_apac_country_lock_conservatively(self):
    candidate = CandidateItem(
        source_name="LinkedIn Jobs",
        source_kind="rss",
        source_category="linkedin-job-search",
        title="Senior AI Solutions Engineer",
        url="https://www.linkedin.com/jobs/view/321/",
        canonical_url="https://www.linkedin.com/jobs/view/321/",
        summary="Enterprise AI API integration. Uses Azure. Remote Singapore only.",
        raw={
            "location": "Singapore",
            "remote_policy": "Remote Singapore only",
            "source_type": "LinkedIn_job",
        },
    )

    opportunity = fallback_job_opportunities(
        [(9, candidate)], "2026-08-11"
    )[0]

    self.assertEqual(opportunity.cloud_requirement, "unclear")
    self.assertEqual(opportunity.vietnam_eligibility, "unlikely")
    self.assertEqual(opportunity.priority, "Low")
    self.assertEqual(opportunity.recommended_action, "verify_first")
```

- [ ] **Step 2: Run Gemini tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
```

Expected: FAIL because the prompt, parser, validator, and fallback do not yet carry cloud evidence or APAC auxiliary semantics.

- [ ] **Step 3: Implement structured extraction and local authority**

Add `cloud_requirement` and `cloud_evidence` to the JSON-only field list in `build_job_classification_prompt`. Include this exact instruction:

```python
"Classify cloud_requirement as required_core|nice_to_have|exposure|"
"not_mentioned|unclear. required_core must be REJECT. A bare cloud "
"technology mention is unclear; preferred/desirable/bonus is nice_to_have; "
"familiarity/exposure is exposure.\n"
```

In `_job_opportunity_from_row`, normalize the model enum and parse evidence:

```python
cloud_requirement=_enum_value(
    row.get("cloud_requirement"),
    {
        "required_core",
        "nice_to_have",
        "exposure",
        "not_mentioned",
        "unclear",
    },
    "unclear",
),
cloud_evidence=_string_list(row.get("cloud_evidence")),
```

In `validate_job_opportunity`, compute `cloud = assess_cloud_candidate(candidate)` before trusting the model. Return `None` for `required_core`. Otherwise overwrite both cloud fields with local evidence. If cloud is `unclear`, append `Cloud requirement` to `what_to_verify` and downgrade `apply_now` to `verify_first`. For `vietnam_eligibility == "unlikely"`, force `priority="Low"`, `recommended_action="verify_first"`, evidence no stronger than `Weak`, and append the country restriction to `what_to_verify`.

Use `job_source_type(candidate)` as the final source type whenever URL evidence yields LinkedIn Post, LinkedIn Job, or ATS. Update `fallback_job_opportunities` with the same cloud assessment and country-lock downgrade. Do not fabricate link status or posting dates.

- [ ] **Step 4: Run Gemini, policy, and location tests**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_gemini.py' -v
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
```

Expected: PASS with model and fallback paths producing the same local hard-rule outcomes.

- [ ] **Step 5: Commit the classifier slice**

```bash
git add news_keep_up/gemini.py tests/test_gemini.py
git commit -m "feat(jobs): enforce cloud fit after classification"
```

### Task 7: Focused LinkedIn Post and Job Query Coverage

**Files:**
- Modify: `config/fde_job_sources.json`
- Modify: `config/fde_job_source_discovery_sources.json`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Task 1 title aliases and Task 3 source types.
- Produces: six direct scan queries and two discovery queries.
- Preserves: unique source names/URLs and enabled HTTPS source validation.

- [ ] **Step 1: Write failing source-catalog coverage tests**

Replace the exact 340-row assertion with 346 and add this test in `tests/test_config.py`:

```python
def test_fde_job_sources_have_expanded_linkedin_posts_and_jobs(self):
    sources = load_sources("config/fde_job_sources.json")
    by_name = {source.name: source for source in sources}
    expected = {
        "Bing LinkedIn FDE Expanded Posts": "LinkedIn_post",
        "Bing LinkedIn Solutions Integration Posts": "LinkedIn_post",
        "Bing LinkedIn AI Transformation Posts": "LinkedIn_post",
        "Bing LinkedIn FDE Expanded Jobs": "LinkedIn_job",
        "Bing LinkedIn Solutions Integration Jobs": "LinkedIn_job",
        "Bing LinkedIn AI Transformation Jobs": "LinkedIn_job",
    }

    self.assertEqual(set(by_name).intersection(expected), set(expected))
    for name, source_type in expected.items():
        source = by_name[name]
        self.assertEqual(source.kind, "rss")
        self.assertEqual(source.metadata["source_type"], source_type)
        self.assertIn("linkedin.com", source.metadata["url_include_any"][0])

    combined_urls = " ".join(source.url.lower() for source in sources)
    for encoded_term in (
        "forward%20deployed%20software%20engineer",
        "ai%20implementation%20engineer",
        "ai%20deployment%20engineer",
        "ai%20solutions%20engineer",
        "technical%20solutions%20engineer",
        "integration%20engineer",
        "ai%20transformation%20consultant",
    ):
        self.assertIn(encoded_term, combined_urls)
```

Add `"LinkedIn_job"` to the allowed source types in the catalog validation test and add `"linkedin-job-search"` to the hidden-hiring/community category coverage set.

- [ ] **Step 2: Run config tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_config.py' -v
```

Expected: FAIL because the six named sources and `LinkedIn_job` catalog type are absent.

- [ ] **Step 3: Add six scan queries and two discovery queries**

Append six enabled RSS sources to `config/fde_job_sources.json`. Use these exact decoded query expressions and URL-encode them with spaces as `%20`, quotes as `%22`, parentheses as `%28`/`%29`, and slashes as `%2F`:

```text
site:linkedin.com/posts ("Forward Deployed Software Engineer" OR "AI Implementation Engineer" OR "AI Deployment Engineer") (Vietnam OR APAC OR "Southeast Asia" OR remote) hiring
site:linkedin.com/posts ("AI Solutions Engineer" OR "Technical Solutions Engineer" OR "Integration Engineer") (Vietnam OR APAC OR "Southeast Asia" OR remote) hiring
site:linkedin.com/posts "AI Transformation Consultant" (Vietnam OR APAC OR "Southeast Asia" OR remote) hiring
site:linkedin.com/jobs ("Forward Deployed Software Engineer" OR "AI Implementation Engineer" OR "AI Deployment Engineer") (Vietnam OR APAC OR "Southeast Asia" OR remote)
site:linkedin.com/jobs ("AI Solutions Engineer" OR "Technical Solutions Engineer" OR "Integration Engineer") (Vietnam OR APAC OR "Southeast Asia" OR remote)
site:linkedin.com/jobs "AI Transformation Consultant" (Vietnam OR APAC OR "Southeast Asia" OR remote)
```

Each Post entry must use:

```json
{
  "type": "rss",
  "category": "linkedin-hidden-hiring-search",
  "source_type": "LinkedIn_post",
  "url_include_any": ["linkedin.com/posts"],
  "enabled": true
}
```

Each Job entry must use:

```json
{
  "type": "rss",
  "category": "linkedin-job-search",
  "source_type": "LinkedIn_job",
  "url_include_any": ["linkedin.com/jobs"],
  "enabled": true
}
```

Use the six exact names asserted by the test and append `&format=rss` to each Bing search URL. Add two discovery sources that combine all seven aliases, one restricted to `linkedin.com/posts` and one to `linkedin.com/jobs`, using category `source-discovery-search` and source type `aggregator`.

- [ ] **Step 4: Validate JSON and run catalog tests**

Run:

```bash
python3 -m json.tool config/fde_job_sources.json >/dev/null
python3 -m json.tool config/fde_job_source_discovery_sources.json >/dev/null
python3 -m unittest discover -s tests -p 'test_config.py' -v
```

Expected: PASS with exactly 346 unique enabled job sources.

- [ ] **Step 5: Commit the query slice**

```bash
git add config/fde_job_sources.json config/fde_job_source_discovery_sources.json tests/test_config.py
git commit -m "feat(jobs): add expanded LinkedIn FDE searches"
```

### Task 8: Integrate Verification, Pending Ordering, Deduplication, and Telegram Format

**Files:**
- Modify: `news_keep_up/job_alerts.py`
- Modify: `news_keep_up/db.py`
- Test: `tests/test_job_alerts.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: Tasks 2-6 persistence, source stages, verification, cloud assessment, and APAC workability.
- Produces: `_verify_opportunities(opportunities: list[JobOpportunity], settings: Settings, current: datetime | None) -> list[JobOpportunity]`
- Produces: source-first pending queue and entity-aware in-batch alert deduplication.
- Extends: `format_job_alert` with posting-date and cloud labels.
- Preserves: three-alert delivery cap and pending-drain behavior.

- [ ] **Step 1: Write failing ordering, formatting, and flow tests**

Add to `tests/test_job_alerts.py`:

```python
def test_format_job_alert_shows_posted_date_and_optional_cloud_stretch(self):
    opportunity = JobOpportunity(
        **{
            **make_opportunity(1).__dict__,
            "posted_date": "2026-08-10",
            "cloud_requirement": "nice_to_have",
            "cloud_evidence": ["aws", "preferred"],
        }
    )

    message = format_job_alert(
        opportunity,
        current=datetime(2026, 8, 11, 9, 0, tzinfo=ICT),
    )

    self.assertIn("📅 Ngày đăng: 2026-08-10", message)
    self.assertIn("☁️ Cloud: Nice-to-have · Stretch", message)


def test_format_job_alert_marks_missing_and_unclear_cloud_for_verification(self):
    opportunity = JobOpportunity(
        **{
            **make_opportunity(1).__dict__,
            "posted_date": "",
            "cloud_requirement": "unclear",
            "cloud_evidence": ["azure"],
            "what_to_verify": ["Cloud requirement"],
        }
    )

    message = format_job_alert(opportunity)

    self.assertIn("📅 Ngày đăng: Chưa thấy trong source", message)
    self.assertIn("☁️ Cloud: Chưa rõ", message)
    self.assertIn("Cloud requirement", message)


def test_format_job_alert_labels_apac_country_lock_explicitly(self):
    opportunity = JobOpportunity(
        **{
            **make_opportunity(1).__dict__,
            "location": "Singapore",
            "remote_policy": "Remote Singapore only",
            "vietnam_eligibility": "unlikely",
            "priority": "Low",
            "recommended_action": "verify_first",
        }
    )

    message = format_job_alert(opportunity)

    self.assertIn("APAC country-locked", message)
    self.assertIn("Remote Singapore only", message)


def test_run_reconciles_then_verifies_before_persisting(self):
    with tempfile.TemporaryDirectory() as tmp:
        sources_path = Path(tmp) / "sources.json"
        sources_path.write_text("[]", encoding="utf-8")
        settings = Settings(db_path=Path(tmp) / "test.db")
        post = make_opportunity(1)
        official = JobOpportunity(
            **{
                **post.__dict__,
                "id": "official-copy",
                "source_item_id": 2,
                "source_type": "ATS",
                "source_url": "https://jobs.ashbyhq.com/example/123",
                "apply_url": "https://jobs.ashbyhq.com/example/123",
            }
        )

        with (
            patch("news_keep_up.job_alerts._new_job_candidates", return_value=[
                (1, make_job_candidate()),
            ]),
            patch(
                "news_keep_up.job_alerts.GeminiClient.classify_job_candidates",
                return_value=[official, post],
            ),
            patch(
                "news_keep_up.job_alerts._verify_opportunities",
                return_value=[post],
            ) as verify,
            patch(
                "news_keep_up.job_alerts.upsert_job_opportunity"
            ) as upsert,
        ):
            run_fde_job_alerts(settings, dry_run=True, sources_path=sources_path)

        verify.assert_called_once()
        upsert.assert_called_once()
        self.assertIs(upsert.call_args.args[1], post)
```

Add to `tests/test_db.py`:

```python
def test_pending_order_is_posts_then_jobs_with_fde_first_inside_stage(self):
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
        init_db(conn)
        fixtures = [
            ("official-fde", "ATS", "Forward Deployed Engineering"),
            ("post-solutions", "LinkedIn_post", "Solutions Engineering and Architecture"),
            ("job-fde", "LinkedIn_job", "Forward Deployed Engineering"),
            ("post-fde", "LinkedIn_post", "Forward Deployed Engineering"),
        ]
        for index, (opportunity_id, source_type, category) in enumerate(fixtures):
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name=opportunity_id,
                source_kind="rss",
                source_category="job-board",
                title=opportunity_id,
                url=f"https://example.com/{opportunity_id}",
                canonical_url=f"https://example.com/{opportunity_id}",
                fingerprint=opportunity_id,
            ))
            base = make_job_opportunity(opportunity_id)
            upsert_job_opportunity(conn, JobOpportunity(**{
                **base.__dict__,
                "source_item_id": item_id,
                "source_type": source_type,
                "category": category,
                "source_url": f"https://example.com/{opportunity_id}",
                "apply_url": f"https://example.com/{opportunity_id}",
            }))

        pending = list_pending_job_alerts(conn)
        conn.close()

    self.assertEqual(
        [item.id for item in pending],
        ["post-fde", "post-solutions", "job-fde", "official-fde"],
    )


def test_pending_order_prefers_fresh_date_within_the_same_tier(self):
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
        init_db(conn)
        for index, posted_date in enumerate(("2026-08-01", "2026-08-10")):
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name=f"LinkedIn Job {index}",
                source_kind="rss",
                source_category="linkedin-job-search",
                title=f"Senior Forward Deployed Engineer {index}",
                url=f"https://example.com/freshness-{index}",
                canonical_url=f"https://example.com/freshness-{index}",
                fingerprint=f"freshness-{index}",
            ))
            base = make_job_opportunity(f"freshness-{index}")
            upsert_job_opportunity(conn, JobOpportunity(**{
                **base.__dict__,
                "source_item_id": item_id,
                "company": f"Example {index}",
                "source_type": "LinkedIn_job",
                "category": "Forward Deployed Engineering",
                "posted_date": posted_date,
                "source_url": f"https://example.com/freshness-{index}",
                "apply_url": f"https://example.com/freshness-{index}",
            }))

        pending = list_pending_job_alerts(conn)
        conn.close()

    self.assertEqual(
        [item.posted_date for item in pending],
        ["2026-08-10", "2026-08-01"],
    )
```

- [ ] **Step 2: Run alert and database tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_db.py' -v
```

Expected: FAIL because formatting lacks posting/cloud lines, run integration lacks verification, and SQL still orders decisions before source stages.

- [ ] **Step 3: Wire verification and implement exact queue/alert behavior**

In `run_fde_job_alerts`, transform classifier results in this order before upsert:

```python
classified = GeminiClient(settings).classify_job_candidates(
    candidates, crawled_at
)
reconciled = reconcile_job_opportunities(classified)
opportunities = _verify_opportunities(
    reconciled, settings, current
)
for opportunity in opportunities:
    upsert_job_opportunity(conn, opportunity)
```

Implement `_verify_opportunities` with a `ThreadPoolExecutor` bounded by `min(settings.max_source_workers, len(opportunities))`. Resolve `verification_time = current or now_ict()`, call `verify_opportunity_link` for each item, then call `apply_link_and_freshness(opportunity, result, verification_time)`. Catch an unexpected worker exception and conservatively apply an `uncertain` `LinkVerification` instead of dropping the whole scan.

Replace URL-only final deduplication with a conservative key:

```python
def _opportunity_dedupe_key(opportunity: JobOpportunity) -> str:
    company = " ".join(opportunity.company.casefold().split())
    title = " ".join(
        opportunity.role_title.casefold().replace("sr.", "senior").split()
    )
    location = " ".join(opportunity.location.casefold().split())
    if company and title and location:
        return f"entity:{company}|{title}|{location}"
    return opportunity.apply_url or opportunity.source_url or opportunity.id
```

Update `list_pending_job_alerts` SQL ordering to use this exact hierarchy before confidence and update time:

```sql
CASE source_type
  WHEN 'LinkedIn_post' THEN 0
  WHEN 'LinkedIn_job' THEN 1
  WHEN 'official_career_page' THEN 2
  WHEN 'ATS' THEN 2
  WHEN 'job_board' THEN 3
  WHEN 'community' THEN 4
  WHEN 'aggregator' THEN 5
  ELSE 6
END,
CASE category
  WHEN 'Forward Deployed Engineering' THEN 0
  WHEN 'Exact FDE Role' THEN 0
  WHEN 'Solutions Engineering and Architecture' THEN 1
  WHEN 'AI Consulting' THEN 2
  WHEN 'Technical Presales' THEN 3
  WHEN 'Technical Account Management' THEN 4
  ELSE 5
END,
CASE vietnam_eligibility
  WHEN 'explicit_yes' THEN 0
  WHEN 'likely_possible' THEN 1
  WHEN 'verify' THEN 2
  WHEN 'unlikely' THEN 3
  ELSE 4
END,
CASE cloud_requirement
  WHEN 'not_mentioned' THEN 0
  WHEN 'nice_to_have' THEN 1
  WHEN 'exposure' THEN 1
  WHEN 'unclear' THEN 2
  ELSE 3
END,
CASE
  WHEN posted_date IS NULL OR posted_date = '' THEN 1
  ELSE 0
END,
posted_date DESC,
CASE evidence_type
  WHEN 'Hard' THEN 0
  WHEN 'Medium' THEN 1
  ELSE 2
END,
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
confidence_score DESC,
updated_at DESC
```

Add these format helpers and lines in `format_job_alert`:

```python
def _cloud_label(opportunity: JobOpportunity) -> str:
    return {
        "nice_to_have": "Nice-to-have · Stretch",
        "exposure": "Exposure · Stretch",
        "not_mentioned": "Không đề cập",
        "unclear": "Chưa rõ",
    }.get(opportunity.cloud_requirement, "Chưa rõ")


def _vietnam_label(opportunity: JobOpportunity) -> str:
    if is_apac_country_locked_opportunity(opportunity):
        return f"APAC country-locked · {opportunity.vietnam_eligibility}"
    return opportunity.vietnam_eligibility


posted_date = opportunity.posted_date or "Chưa thấy trong source"
lines.insert(7, f"📅 Ngày đăng: {escape(posted_date)}")
lines.insert(11, f"☁️ Cloud: {escape(_cloud_label(opportunity))}")
```

Use `_vietnam_label(opportunity)` in the existing Vietnam line. Calculate insertion positions against the final list so the date appears after role-family/seniority context and cloud appears after technical focus, before Vietnam eligibility. Keep all existing salary, benefits, footprint, outreach, action, and link lines. `required_core` must already be filtered; map it to `Chưa rõ` defensively rather than exposing a misleading accepted label.

Patch existing `run_fde_job_alerts` tests to mock `_verify_opportunities` with identity behavior:

```python
patch(
    "news_keep_up.job_alerts._verify_opportunities",
    side_effect=lambda opportunities, settings, current: opportunities,
)
```

- [ ] **Step 4: Run all pipeline-facing tests**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_alerts.py' -v
python3 -m unittest discover -s tests -p 'test_db.py' -v
python3 -m unittest discover -s tests -p 'test_job_verification.py' -v
python3 -m unittest discover -s tests -p 'test_scheduler.py' -v
python3 -m unittest discover -s tests -p 'test_vercel_deploy.py' -v
```

Expected: PASS with three-alert draining, deduplication, force, dry-run, scheduler, and endpoint behavior unchanged.

- [ ] **Step 5: Commit the delivery slice**

```bash
git add news_keep_up/job_alerts.py news_keep_up/db.py tests/test_job_alerts.py tests/test_db.py
git commit -m "feat(jobs): deliver verified cloud-fit alerts"
```

### Task 9: Prompt/README Parity and Full Regression Gate

**Files:**
- Modify: `docs/prompts/tech-job-headhunter-master-prompt.md`
- Modify: `README.md`
- Modify: `tests/test_job_search_policy.py`

**Interfaces:**
- Consumes: all implemented policy names and alert behavior.
- Produces: user-facing documentation and standalone browsing-agent parity.
- Release gate: full unittest suite plus JSON and diff validation.

- [ ] **Step 1: Write failing documentation-contract assertions**

Extend `test_standalone_prompt_matches_policy_and_has_no_template_tokens` in `tests/test_job_search_policy.py` with:

```python
for title in (
    "Forward Deployed Software Engineer",
    "AI Solutions Engineer",
    "AI Implementation Engineer",
    "AI Deployment Engineer",
    "Technical Solutions Engineer",
    "Integration Engineer",
    "AI Transformation Consultant",
):
    self.assertIn(title, prompt)
self.assertLess(prompt.index("LinkedIn Posts"), prompt.index("LinkedIn Jobs"))
self.assertIn("required_core", prompt)
self.assertIn("nice_to_have", prompt)
self.assertIn("exposure", prompt)
self.assertIn("country-locked", prompt)
self.assertIn("cloud_requirement", prompt)
self.assertIn("cloud_evidence", prompt)
```

- [ ] **Step 2: Run prompt tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_job_search_policy.py' -v
```

Expected: FAIL because the standalone prompt does not yet include the new source order and cloud contract.

- [ ] **Step 3: Update the standalone prompt and README**

Update `docs/prompts/tech-job-headhunter-master-prompt.md` with these exact policy statements:

```text
Search order: LinkedIn Posts -> LinkedIn Jobs -> official career/ATS -> other direct job sources -> aggregators.
Within every source group, rank Forward Deployed Engineering first.
Cloud requirement values: required_core, nice_to_have, exposure, not_mentioned, unclear.
Reject required_core. Keep nice_to_have and exposure as Stretch. A bare cloud keyword is unclear and must be verified.
Keep APAC country-locked opportunities only as Low-priority auxiliary results; never mark them APPLY_NOW.
```

Add the seven exact titles to the search profile and query pack. Add `cloud_requirement` and `cloud_evidence` to the required JSON output and sample object. Reorder the search playbook so the first occurrence of `LinkedIn Posts` precedes the first occurrence of `LinkedIn Jobs`.

Update README's Technical Job Headhunter Policy and Message Format sections to state:

- Posts are considered before Jobs.
- FDE is first inside each source stage.
- mandatory core cloud roles are filtered;
- optional/exposure cloud roles show `Stretch`;
- APAC country locks are low-priority auxiliary leads;
- alerts show posting date and cloud assessment;
- each scan still sends at most three individual alerts.

Do not document deployment as completed.

- [ ] **Step 4: Run the full release gate**

Run:

```bash
python3 -m json.tool config/job_search_policy.json >/dev/null
python3 -m json.tool config/fde_job_sources.json >/dev/null
python3 -m json.tool config/fde_job_source_discovery_sources.json >/dev/null
python3 -m compileall -q news_keep_up
python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: all JSON parses, Python compiles, the complete test suite passes, `git diff --check` is silent, and status lists only the intended implementation/documentation files before the final commit.

- [ ] **Step 5: Commit the documentation and verified feature**

```bash
git add README.md docs/prompts/tech-job-headhunter-master-prompt.md tests/test_job_search_policy.py
git commit -m "docs(jobs): document LinkedIn-first cloud-fit scanning"
```

After the commit, run once more:

```bash
python3 -m unittest discover -s tests -v
git status --short
```

Expected: full suite PASS and a clean worktree.
