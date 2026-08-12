# FDE Job Eligibility and Telegram Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop non-Vietnam/country-locked and non-vacancy FDE alerts while retaining concrete uncertain jobs in `/verify` and adding fast, policy-correct Telegram job queries.

**Architecture:** Add deterministic direct-link and strong-location predicates ahead of model enrichment, then reuse them at persistence, pending delivery, and Telegram query boundaries. Role matching no longer consumes search-source labels, while uncertain concrete roles stay stored with `should_alert=false` for an explicit manual-review command.

**Tech Stack:** Python 3.11+, standard-library dataclasses/urllib parsing/regex, unittest, SQLite and Turso through the existing database adapter, Telegram webhook commands, JSON source policy.

## Global Constraints

- Auto-send only concrete vacancies or LinkedIn hiring posts with deterministic Vietnam or cross-border SEA/APAC/Asia/global eligibility evidence.
- Bare `Remote`, `verify`, Weak evidence, relocation-only, and foreign country locks never auto-send.
- Generic homepages, search/category pages, and non-job content never appear in job commands.
- Preserve valid uncertain direct vacancies for `/verify`; do not delete historical data.
- Keep `fde-jobs`, its schedule, database, bot destination, and three-message batch limit.
- Do not implement the separate cloud-fit plan in this change.
- Existing news and interview Telegram profiles remain backward compatible.
- Use tests before implementation and conventional commits; push only after the full verification gate.

---

## File Structure

- Create `news_keep_up/job_links.py`: deterministic vacancy/hiring-post URL specificity checks shared by ingestion, alerting, and commands.
- Modify `news_keep_up/job_search_policy.py`: remove configured source category from role evidence.
- Modify `news_keep_up/job_filters.py`: conservative geographic classification plus distinct storable, auto-alertable, and manual-verification predicates.
- Modify `news_keep_up/sources.py`: infer JSON work mode from item evidence instead of stamping every job `Remote`.
- Modify `news_keep_up/gemini.py`: normalize deterministic eligibility and set `should_alert` from the strict predicate.
- Modify `news_keep_up/job_alerts.py`: reject non-job links before classification and recheck strict eligibility before formatting/sending.
- Modify `news_keep_up/db.py`: honor `should_alert` in the pending queue and support AND-token job search with optional priority filtering.
- Modify `news_keep_up/telegram_commands.py`: add job modes and aliases while using the shared eligibility/link policy.
- Modify `config/job_search_policy.json`: add North America and missing remote-scope wording.
- Modify `config/fde_job_sources.json`: remove the incorrect feed-wide AIJobs remote assertion.
- Modify `README.md`: document suitable-job and verification commands.
- Modify `tests/test_job_search_policy.py`, `tests/test_job_alerts.py`, `tests/test_sources.py`, `tests/test_db.py`, and `tests/test_telegram_commands.py`: regression and command coverage.

### Task 1: Concrete vacancy and role-evidence gate

**Files:**
- Create: `news_keep_up/job_links.py`
- Modify: `news_keep_up/job_search_policy.py`
- Modify: `news_keep_up/job_alerts.py`
- Test: `tests/test_job_search_policy.py`
- Test: `tests/test_job_alerts.py`

**Interfaces:**
- Produces: `is_specific_job_url(url: str, source_type: str = "") -> bool`
- Produces: `is_specific_job_candidate(candidate: CandidateItem) -> bool`
- Produces: `is_specific_job_opportunity(opportunity: JobOpportunity) -> bool`
- Changes: `evaluate_job_candidate(candidate)` only uses item evidence, not `source_category`, to find a role family.

- [ ] **Step 1: Add failing role-evidence regression**

Add this case to `tests/test_job_search_policy.py`:

```python
def test_source_category_cannot_create_an_fde_match(self):
    candidate = CandidateItem(
        source_name="Bing AI Solution Architect Vietnam",
        source_kind="rss",
        source_category="fde-adjacent-job-search",
        title="Home | Microsoft AI",
        url="https://microsoft.ai/",
        canonical_url="https://microsoft.ai/",
        summary="We build frontier AI models.",
        raw={"source_type": "aggregator"},
    )

    self.assertFalse(evaluate_job_candidate(candidate).is_eligible)
```

- [ ] **Step 2: Add failing direct-link tests**

Add focused assertions to `tests/test_job_alerts.py`:

```python
def test_specific_job_link_rejects_homepage_and_accepts_direct_jobs(self):
    self.assertFalse(is_specific_job_url("https://microsoft.ai/", "aggregator"))
    self.assertFalse(is_specific_job_url("https://example.com/jobs", "official_career_page"))
    self.assertTrue(is_specific_job_url("https://aijobs.net/job/forward-deployed-engineer-277831", "job_board"))
    self.assertTrue(is_specific_job_url("https://job-boards.greenhouse.io/hightouch/jobs/6015438004", "ATS"))
    self.assertTrue(is_specific_job_url("https://www.linkedin.com/posts/person_we-are-hiring-123", "LinkedIn_post"))
```

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_job_search_policy.JobSearchPolicyTest.test_source_category_cannot_create_an_fde_match \
  tests.test_job_alerts.JobAlertsTest.test_specific_job_link_rejects_homepage_and_accepts_direct_jobs -v
```

Expected: the Microsoft candidate is currently eligible and the new link helper is missing.

- [ ] **Step 4: Implement the direct-link module**

Create `news_keep_up/job_links.py` with URL parsing that:

```python
def is_specific_job_url(url: str, source_type: str = "") -> bool:
    """Return true only for a concrete vacancy or LinkedIn hiring post."""

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
```

Recognize LinkedIn `/jobs/view/`, LinkedIn `/posts/` and `/feed/update/`, ATS/job-board paths containing a concrete child after `job`, `jobs`, `position`, `positions`, `opening`, `openings`, `vacancy`, or `viewjob`, and host-specific direct ATS paths. Reject roots and exact generic collection/search paths.

- [ ] **Step 5: Remove `candidate.source_category` from role matching**

In `evaluate_job_candidate`, build `body` from item summary, content, author, company, location, and work mode only. Preserve summary-based hidden hiring; do not add source name or configured category.

- [ ] **Step 6: Enforce the link gate before classification**

In `_new_job_candidates`, place `is_specific_job_candidate(candidate)` after source filters and role matching and before database upsert. Generic search results never become job opportunities.

- [ ] **Step 7: Run targeted tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_job_search_policy tests.test_job_alerts -v
```

Expected: all policy and job-alert tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add news_keep_up/job_links.py news_keep_up/job_search_policy.py news_keep_up/job_alerts.py tests/test_job_search_policy.py tests/test_job_alerts.py
git commit -m "fix(jobs): require concrete vacancy evidence"
```

### Task 2: Strict Vietnam and cross-border remote eligibility

**Files:**
- Modify: `config/job_search_policy.json`
- Modify: `config/fde_job_sources.json`
- Modify: `news_keep_up/job_filters.py`
- Modify: `news_keep_up/sources.py`
- Test: `tests/test_job_alerts.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Produces: `has_confident_remote_scope_candidate(candidate: CandidateItem) -> bool`
- Produces: `has_confident_remote_scope_opportunity(opportunity: JobOpportunity) -> bool`
- Produces: `is_auto_alertable_from_vietnam_opportunity(opportunity: JobOpportunity) -> bool`
- Produces: `is_manual_verification_opportunity(opportunity: JobOpportunity) -> bool`
- Preserves: `is_workable_from_vietnam_candidate` as the broad storage prefilter.

- [ ] **Step 1: Add failing Prague, North America, bare-remote, and SEA tests**

Add cases to `tests/test_job_alerts.py` proving:

```python
self.assertEqual(vietnam_workability_for_candidate(prague), "no")
self.assertEqual(vietnam_workability_for_opportunity(hightouch_na), "no")
self.assertFalse(is_auto_alertable_from_vietnam_opportunity(bare_remote))
self.assertTrue(is_manual_verification_opportunity(bare_remote))
self.assertTrue(is_auto_alertable_from_vietnam_opportunity(remote_sea))
```

Use the production-shaped Prague URL with empty location, `Remote (North America)` for Hightouch, a direct FWDDeploy job with plain `Remote`, and a direct job with `Remote Southeast Asia`.

- [ ] **Step 2: Add failing JSON work-mode parsing test**

In `tests/test_sources.py`, pass a Greenhouse-style row with `location.name="Prague, Czechia"` and no remote field to `_candidate_from_json_job`; assert `candidate.raw["remote_policy"] == ""`. Add a second row with `location.name="Remote APAC"`; assert it becomes `Remote`.

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_job_alerts tests.test_sources -v
```

Expected: Prague and North America remain permissive, strict helpers are missing, and JSON parsing stamps remote unconditionally.

- [ ] **Step 4: Update location policy vocabulary**

Add explicit exclusions for `north america`, `remote north america`, and `north america only`. Add positive bidirectional phrases such as `apac remote`, `asia remote`, `southeast asia remote`, `sea remote`, and `work from anywhere`. Keep country-specific APAC locations out of positive evidence.

- [ ] **Step 5: Split geographic evidence by trust**

Refactor `_vietnam_workability` so explicit exclusions and known foreign locations are checked against parsed location, work mode, role title, country, and location-bearing URL slugs before bare remote fallback. Add `prague`, `praha`, `czechia`, and `north america` to deterministic foreign-location terms. Do not use a search source label or URL hostname as positive Vietnam evidence.

- [ ] **Step 6: Add strict and manual predicates**

Implement:

```python
def is_auto_alertable_from_vietnam_opportunity(opportunity: JobOpportunity) -> bool:
    workability = vietnam_workability_for_opportunity(opportunity)
    return (
        is_specific_job_opportunity(opportunity)
        and opportunity.status != "closed"
        and opportunity.evidence_type != "Weak"
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
```

The send predicate deliberately does not check `should_alert`; callers own persisted queue intent, while this predicate owns evidence quality.

- [ ] **Step 7: Stop feed-wide remote assumptions**

Remove `"remote_policy": "Remote"` from the AIJobs source entry. In `_candidate_from_json_job`, prefer an item remote/workplace field, then infer `Remote` only when parsed item location or description explicitly contains `remote`; use source metadata only when the source itself guarantees every item is remote.

- [ ] **Step 8: Run targeted tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_job_alerts tests.test_sources tests.test_config -v
```

Expected: all geography, parser, and source-config tests pass.

- [ ] **Step 9: Commit Task 2**

```bash
git add config/job_search_policy.json config/fde_job_sources.json news_keep_up/job_filters.py news_keep_up/sources.py tests/test_job_alerts.py tests/test_sources.py tests/test_config.py
git commit -m "fix(jobs): enforce Vietnam remote eligibility"
```

### Task 3: Persist uncertainty without sending it

**Files:**
- Modify: `news_keep_up/gemini.py`
- Modify: `news_keep_up/job_alerts.py`
- Modify: `news_keep_up/db.py`
- Test: `tests/test_gemini.py`
- Test: `tests/test_job_alerts.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Changes: `validate_job_opportunity` sets normalized eligibility/evidence from deterministic candidate workability.
- Changes: stored uncertain concrete vacancies use `should_alert=false`.
- Changes: `list_pending_job_alerts(conn, limit)` returns only rows with `should_alert=1`.

- [ ] **Step 1: Add failing persistence and queue tests**

Cover these behaviors:

```python
self.assertFalse(validated_bare_remote.should_alert)
self.assertEqual(validated_bare_remote.vietnam_eligibility, "verify")
self.assertTrue(validated_remote_apac.should_alert)
self.assertEqual(validated_remote_apac.vietnam_eligibility, "likely_possible")
self.assertNotIn(non_alerting_id, [row.id for row in list_pending_job_alerts(conn)])
```

- [ ] **Step 2: Add failing legacy-row send regression**

In `tests/test_job_alerts.py`, insert production-shaped Prague, Microsoft homepage, and Hightouch North America rows with stale `should_alert=True`. Patch fetching/classification to return no new candidates and assert `run_fde_job_alerts(..., dry_run=True)` contains none of their titles.

- [ ] **Step 3: Run targeted tests and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_gemini tests.test_db tests.test_job_alerts -v
```

Expected: verify rows still have `should_alert=true`, pending SQL includes them, and the final alert filter is permissive.

- [ ] **Step 4: Normalize deterministic eligibility in Gemini validation**

Build the validated opportunity first, then derive `should_alert` from `is_auto_alertable_from_vietnam_opportunity`. Deterministic candidate states override model geography: `explicit_yes` maps to Hard, confident regional remote maps to `likely_possible`/Medium, and unknown maps to `verify`/Weak. Preserve relevant uncertain rows instead of returning `None`.

- [ ] **Step 5: Enforce persisted and runtime send gates**

Add `AND should_alert=1` to `list_pending_job_alerts`. Replace `is_workable_from_vietnam_opportunity` in `run_fde_job_alerts` with both persisted intent and `is_auto_alertable_from_vietnam_opportunity`. This immediately suppresses legacy stale rows.

- [ ] **Step 6: Run targeted tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_gemini tests.test_db tests.test_job_alerts -v
```

Expected: all classifier, queue, and delivery tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add news_keep_up/gemini.py news_keep_up/job_alerts.py news_keep_up/db.py tests/test_gemini.py tests/test_job_alerts.py tests/test_db.py
git commit -m "fix(jobs): separate verify and alert queues"
```

### Task 4: Policy-correct Telegram job commands

**Files:**
- Modify: `news_keep_up/db.py`
- Modify: `news_keep_up/telegram_commands.py`
- Modify: `tests/test_db.py`
- Modify: `tests/test_telegram_commands.py`

**Interfaces:**
- Changes: `search_job_opportunities(conn, query="", limit=5, *, priority="") -> list[JobOpportunity]`
- Changes: `_job_search_text(settings, query, limit=5, only_compensation=False, only_benefits=False, mode="fit") -> str`
- Adds command modes: `fit`, `vn`, `sea`, `remote`, `high`, and `verify`.

- [ ] **Step 1: Add failing database search tests**

Insert jobs whose fields separately contain `python` and `remote`, then assert `search_job_opportunities(conn, "python remote")` returns only rows matching both tokens. Insert High and Medium jobs and assert `priority="High"` filters the priority column.

- [ ] **Step 2: Add failing Telegram command tests**

Create a fixture with:

- Vietnam explicit High job;
- Remote SEA likely/Medium job;
- bare Remote verify/Weak job;
- Remote North America job;
- generic homepage row.

Assert:

```python
/jobs       -> Vietnam + SEA only
/vn         -> Vietnam only
/sea        -> SEA only
/remote     -> eligible remote rows only
/high       -> Vietnam High only
/verify     -> bare Remote only
/commands   -> the FDE command menu
```

- [ ] **Step 3: Run targeted tests and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_db tests.test_telegram_commands -v
```

Expected: multi-token search uses exact-phrase matching, `/high` does not filter priority, and new aliases/modes are missing.

- [ ] **Step 4: Implement AND-token database search**

Split normalized query text on whitespace. For every token, append one grouped `OR` clause across id, company, role title, category, location, work mode, eligibility, source type, fit text, skills, domain, country, compensation, benefits, package, company footprint, priority, and recommended action. Combine token groups with `AND`; add an optional exact case-insensitive priority clause.

- [ ] **Step 5: Implement shared command modes**

Add aliases for `fit`, `list`, `query`, `vn`, `sea`, `verify`, `new`, and `commands`. Map each original command name to a mode and apply:

```python
fit    -> is_auto_alertable_from_vietnam_opportunity
vn     -> fit and workability == "explicit_yes"
sea    -> fit and workability == "likely_possible"
remote -> fit and remote evidence in location/work policy
high   -> fit and priority == "High"
verify -> is_manual_verification_opportunity
```

Salary and benefit modes remain restricted to `fit`. Keep `/search` as news search outside `fde-jobs` and as suitable-job search inside it.

- [ ] **Step 6: Update command help and result labels**

Document the strict default and manual `/verify` queue in `_help_text`. Keep the existing concise HTML result layout and direct URL output.

- [ ] **Step 7: Run targeted tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.test_db tests.test_telegram_commands -v
```

Expected: all database and Telegram command tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add news_keep_up/db.py news_keep_up/telegram_commands.py tests/test_db.py tests/test_telegram_commands.py
git commit -m "feat(telegram): add scoped FDE job queries"
```

### Task 5: Documentation, production-data audit, and delivery verification

**Files:**
- Modify: `README.md`
- Test: full repository

**Interfaces:**
- Documents: exact FDE job command behavior and `/verify` separation.
- Verifies: reported production records under current predicates without modifying Turso data.

- [ ] **Step 1: Update README command documentation**

Add the FDE jobs command set and explicitly state that default commands show only strong Vietnam/SEA/APAC/global matches, while `/verify` shows concrete but geographically uncertain jobs.

- [ ] **Step 2: Run format and full tests**

Run:

```bash
git diff --check
.venv/bin/python -m unittest discover -s tests -v
```

Expected: no whitespace errors and zero test failures.

- [ ] **Step 3: Audit the three production regressions read-only**

Load `.vercel/.env.scheduler.local`, select the Prague, Microsoft homepage, and Hightouch North America rows from Turso, and evaluate them without updates. Expected:

```text
Prague: workability=no, alertable=false
Microsoft homepage: specific_link=false, alertable=false
Hightouch North America: workability=no, alertable=false
```

Also sample one explicit Vietnam and one Remote SEA/APAC opportunity when available; they must remain alertable if their links are specific and evidence is not Weak.

- [ ] **Step 4: Restart and inspect the local scheduler**

Run:

```bash
launchctl kickstart -k "gui/$(id -u)/com.news-keep-up.scheduler-worker"
launchctl print "gui/$(id -u)/com.news-keep-up.scheduler-worker"
```

Expected: state is `running` with a new PID. Inspect fresh stderr/stdout tails for immediate startup failures.

- [ ] **Step 5: Run a non-sending preview against an isolated local database**

Use a temporary database and test fixtures or a patched source set; do not send Telegram messages and do not mutate production Turso. Confirm output includes a qualified job and omits the three regressions.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md
git commit -m "docs(jobs): document scoped Telegram queries"
```

- [ ] **Step 7: Perform final verification and push**

Run the full suite again on the exact tree being pushed, inspect `git status`, scan every unpushed commit diff for secrets, then:

```bash
git push origin HEAD
```

Expected: push succeeds without force and `origin/main` contains all implementation commits.
