# FDE Job Scanner: LinkedIn-First and Cloud-Fit Design

**Date:** 2026-08-11  
**Status:** Approved for implementation planning  
**Profile:** `fde-jobs`

## Context

The repository already runs an automated `fde-jobs` scan every 30 minutes, stores normalized opportunities, and sends at most three individual Telegram alerts per run. Its source catalog covers LinkedIn search results, official career pages, ATS boards, remote job boards, and community signals. Its shared policy also supports five broad role families.

The current pipeline does not reliably satisfy the new FDE-focused search contract:

- LinkedIn Posts are not guaranteed to be processed or delivered before LinkedIn Jobs.
- Several requested FDE-adjacent titles are missing or only partially represented.
- Cloud requirements are not classified into mandatory versus optional evidence.
- A cloud-heavy role can survive classification even though the target candidate has no cloud experience.
- Alert messages do not explicitly show the posting date or cloud requirement.
- LinkedIn URLs discovered through search feeds can inherit `aggregator` metadata even when the candidate URL is a LinkedIn Post or Job.
- Stale, closed, login-walled, and unverifiable links are not distinguished consistently.

This design upgrades the existing profile. It does not introduce a second scheduler, endpoint, database, or Telegram destination.

## Goals

1. Search and prioritize credible LinkedIn hiring Posts before LinkedIn Jobs and other vacancy sources.
2. Keep Forward Deployed Engineering as the first role family while retaining the existing broader technical job scope.
3. Add these explicit title aliases:
   - Forward Deployed Software Engineer
   - AI Solutions Engineer
   - AI Implementation Engineer
   - AI Deployment Engineer
   - Technical Solutions Engineer
   - Integration Engineer
   - AI Transformation Consultant
4. Reject roles where AWS, GCP, Azure, Kubernetes, Terraform, DevOps, SRE, or MLOps is a mandatory core capability.
5. Retain roles where cloud is optional or exposure-only and label them as stretch opportunities.
6. Prefer work confirmed for Vietnam, retain uncertain APAC/global remote roles for verification, and place APAC country-locked roles in a clearly labeled auxiliary tier.
7. Check link and posting evidence conservatively without inventing open status, dates, eligibility, or official apply URLs.
8. Continue sending one Telegram message per opportunity, with no more than three alerts per scan.

## Non-goals

- Do not auto-apply, submit forms, or contact recruiters.
- Do not require or score a CV.
- Do not create a new `fde-jobs` profile, schedule, Telegram bot, or endpoint.
- Do not remove the existing Solutions Engineering/Architecture, AI Consulting, Technical Presales, or Technical Account Management families.
- Do not bypass LinkedIn access controls or treat a login wall as proof that a role is open.
- Do not require every search-result lead to have an official ATS match; unverifiable but credible evidence may remain `VERIFY_FIRST`.
- Do not add a third-party runtime dependency.

## Architecture

The existing pipeline remains authoritative:

```text
Configured sources
  -> staged concurrent fetch
  -> deterministic source/title/location prefilter
  -> source-aware candidate allocation and ordering
  -> Gemini classification or local fallback
  -> deterministic cloud/location/status validation
  -> database upsert and URL/entity deduplication
  -> pending-alert ordering
  -> one Telegram message per opportunity
```

The change extends six existing boundaries instead of creating a parallel system:

1. `config/job_search_policy.json` becomes policy version 2 and adds cloud evidence rules and source-stage ordering.
2. `news_keep_up/job_search_policy.py` loads the new policy and produces deterministic role and cloud assessments.
3. `news_keep_up/job_alerts.py` stages sources, allocates the bounded classification budget, verifies direct links, and orders candidates.
4. `news_keep_up/gemini.py` requests and validates structured cloud evidence while preserving its local fallback.
5. `news_keep_up/models.py` and `news_keep_up/db.py` persist cloud assessment safely on existing SQLite and Turso databases.
6. `config/fde_job_sources.json` and its discovery catalog gain focused LinkedIn Post and LinkedIn Job queries for the approved aliases.

## Source Stages and Candidate Budget

Sources are assigned to these ordered stages:

1. `LinkedIn_post`
2. `LinkedIn_job`
3. `official_career_page` and `ATS`
4. `job_board`, `community`, and equivalent direct vacancy sources
5. `aggregator` and other discovery-only sources

Candidate URL evidence takes precedence over configured source metadata. A final URL containing `linkedin.com/posts` is a `LinkedIn_post`; a final URL containing `linkedin.com/jobs` is a `LinkedIn_job`, even if the enclosing Bing RSS source is configured as an aggregator.

Each source stage fetches concurrently, while stages are processed in the order above. All stages are attempted on every run, even when earlier stages return candidates. A bounded, reclaimable allocation prevents LinkedIn Posts from consuming the entire `MAX_LLM_ITEMS_PER_RUN` budget:

- LinkedIn Posts reserve 40% of the available candidate slots.
- LinkedIn Jobs reserve 30%.
- Official/ATS and other job sources reserve the remaining 30%.
- Unused slots from any stage are redistributed to the next best eligible candidates across all stages.

Percentages apply after rounding to whole candidates and always preserve at least one slot for each populated major bucket when the configured total is at least three. This keeps the existing cost ceiling while guaranteeing that both Posts and concrete Jobs are considered.

Within each source stage, ordering is:

1. Forward Deployed Engineering.
2. Requested FDE-adjacent titles and then the remaining approved role families in policy order.
3. Explicit Vietnam eligibility, likely Vietnam eligibility, unknown/verify, then APAC country-lock.
4. Cloud not mentioned, cloud optional/exposure, then cloud unclear.
5. Freshness, evidence strength, confidence, and source trust.

The pending alert queue uses the same source-stage-first order. Therefore individual messages still satisfy Posts -> Jobs; FDE remains first inside each stage. The existing three-message limit remains flood control, and unsent eligible opportunities stay pending.

## Role Scope

The five existing role families remain, in this order:

1. Forward Deployed Engineering
2. Solutions Engineering and Architecture
3. AI Consulting
4. Technical Presales
5. Technical Account Management

The requested aliases map deterministically:

- Forward Deployed Engineering: `Forward Deployed Software Engineer`, `AI Implementation Engineer`, and `AI Deployment Engineer`.
- Solutions Engineering and Architecture: `AI Solutions Engineer`, `Technical Solutions Engineer`, and `Integration Engineer`.
- AI Consulting: `AI Transformation Consultant`.

All aliases still require an approved domain signal. A generic Integration Engineer result without AI, enterprise automation, or enterprise SaaS evidence is rejected, avoiding unrelated integration roles.

Existing seniority and technical-evidence gates remain. FDE is prioritized, not made exclusive.

## Cloud Assessment

Each opportunity receives two persisted fields:

- `cloud_requirement`: `required_core`, `nice_to_have`, `exposure`, `not_mentioned`, or `unclear`.
- `cloud_evidence`: short source-backed text or normalized evidence terms explaining the classification.

The policy defines:

- cloud technologies: AWS, Amazon Web Services, GCP, Google Cloud, Azure, Kubernetes, K8s, Terraform, infrastructure as code, DevOps, SRE, site reliability, and MLOps;
- mandatory markers: required, must have, you must, essential, minimum qualification, proficiency, strong expertise, deep expertise, production experience, and hands-on experience;
- optional markers: preferred, desirable, bonus, plus, nice to have, and optional;
- exposure markers: exposure, familiarity, awareness, working knowledge, or willingness to learn;
- core responsibility signals: owning cloud infrastructure, operating Kubernetes clusters, building Terraform/IaC, production cloud architecture, CI/CD platform ownership, reliability/on-call ownership, or MLOps platform operations.

Deterministic assessment uses sentence-level or bounded-neighborhood evidence. A technology name elsewhere in the job description is not enough to infer a mandatory requirement.

Rules:

- Mandatory marker plus a cloud technology, or an unambiguous core responsibility signal, produces `required_core` and rejects the candidate.
- Optional wording produces `nice_to_have`; the opportunity remains alertable and is labeled `Stretch`.
- Familiarity/exposure wording produces `exposure`; the opportunity remains alertable and is labeled `Stretch`.
- No cloud evidence produces `not_mentioned`.
- Conflicting or insufficient wording produces `unclear`, adds cloud to `what_to_verify`, and cannot produce `APPLY_NOW` solely from model inference.

Gemini may extract evidence, but local post-validation has final authority. The local fallback applies the same deterministic assessment.

## Location and Applicant Eligibility

The current `vietnam_eligibility` contract remains authoritative:

- `explicit_yes`: the source explicitly allows Vietnam or locates the role in Vietnam.
- `likely_possible`: credible regional/global evidence makes Vietnam plausible but not explicit.
- `verify`: eligibility is unknown or access prevents verification.
- `unlikely` or `no`: explicit restrictions conflict with applying from Vietnam.

Ordering and action rules are:

- Confirmed Vietnam roles rank first and may be `APPLY_NOW` when other evidence is sufficient.
- Remote APAC, SEA, Asia, global, or worldwide language without explicit Vietnam eligibility becomes `VERIFY_FIRST`.
- APAC country-locked roles are retained only as low-priority auxiliary opportunities. They are labeled country-locked, never marked `APPLY_NOW`, and sort after all Vietnam-compatible or verification candidates.
- Country-locked roles outside APAC are rejected unless the source explicitly offers relevant relocation or visa sponsorship.
- Onsite roles outside Vietnam require explicit relocation evidence to remain eligible.

The alert reuses location, country, remote policy, eligibility, and `what_to_verify` to show the exact restriction. No separate country-lock database column is required.

## Link, Freshness, and Official-Source Verification

Direct-link checking is best effort and bounded by the existing source timeout. It follows redirects but does not bypass access controls. Checks run with bounded concurrency only for candidates selected into the classification budget, preventing the 340-source catalog from creating a second unbounded fetch pass.

Status rules:

- HTTP 404 or 410, an explicit closed/expired/no-longer-accepting marker, or a source-provided closed status rejects the opportunity.
- A live official career or ATS page with an explicit accepting/open marker supports `open`. A live page with a recognizable job record but no explicit open or closed marker supports only `likely_open`.
- A LinkedIn login wall, rate limit, bot challenge, timeout, or ambiguous page remains `uncertain` and becomes `VERIFY_FIRST`; it is not evidence that the listing is closed.
- A LinkedIn Post older than 30 days is rejected unless it links to or is reconciled with an official vacancy that still appears open.
- A Job older than 30 days may remain eligible when its official career or ATS page still appears open. Its original posting date remains visible.
- Missing dates remain empty and are added to `what_to_verify`; the crawler date is never substituted as the posting date.

When multiple candidates normalize to the same company, role title, and location, the pipeline prefers the official ATS/career URL as `apply_url`, preserves the LinkedIn Post as `source_url` or hiring signal, and avoids sending duplicate alerts. Reconciliation is conservative: incomplete company/title evidence does not cause unrelated roles to merge.

## Persistence and Compatibility

`JobOpportunity` gains `cloud_requirement` and `cloud_evidence` with backward-compatible defaults. `job_opportunities` gains matching text columns through the existing `_ensure_columns` migration mechanism:

- existing rows default to `unclear` and empty evidence;
- SQLite and Turso use the same additive migration;
- no table rebuild or destructive migration is required;
- inserts, updates, row reads, raw JSON serialization, and job search include both new fields; `alert_fingerprint` includes `cloud_requirement` but omits explanatory `cloud_evidence` text to avoid repeat alerts caused only by wording changes.

A change between eligible cloud classifications (`unclear`, `nice_to_have`, `exposure`, or `not_mentioned`) is material and can generate one updated alert. A change to `required_core` suppresses the opportunity before delivery. If later source evidence corrects it back to an eligible classification, the updated `cloud_requirement` fingerprint permits one corrected alert while preventing identical repeats.

## Gemini Contract and Local Authority

The job-classification prompt adds:

- source stage and corrected source-type hint;
- the explicit title aliases;
- `cloud_requirement` and `cloud_evidence`;
- rules for mandatory versus optional cloud wording;
- conservative link/date/status handling;
- APAC country-lock behavior.

Gemini can enrich and summarize but cannot override local hard rules. Local validation rejects `required_core`, closed links, out-of-scope roles, disallowed seniority, and incompatible non-APAC location restrictions. Unsupported claims are downgraded to `VERIFY_FIRST`.

If Gemini is unavailable, malformed, or over budget, fallback classification still emits eligible opportunities using deterministic role, cloud, source, location, and status evidence. Source failures are logged independently and do not abort the scan.

## Telegram Alert Contract

Alerts remain individual HTML Telegram messages. The current detailed content remains and gains posting and cloud lines:

```text
🔴 Tech Job Alert · VERIFY FIRST · 84/100
Time: 11 Aug 09:00 ICT

Forward Deployed Engineer
🏢 Công ty: Example
🏷 Nhóm: Forward Deployed Engineering
📅 Ngày đăng: 10 Aug 2026
🔧 Tech evidence: Python, TypeScript, AI agents, APIs
📍 Địa điểm: Remote APAC
🌍 Quốc gia: APAC
🌐 Remote: Remote; applicant location needs verification
☁️ Cloud: Nice-to-have · Stretch
🇻🇳 Khả năng từ VN: verify · Medium signal
📌 Trạng thái: uncertain · Nguồn: LinkedIn Post
❓ Cần verify: Vietnam payroll, official JD, closing status
🎯 Hành động: Verify eligibility/status first
🔗 Link: ...
```

Formatting rules:

- Missing posting date displays `Chưa thấy trong source`.
- `required_core` never reaches Telegram.
- `nice_to_have` and `exposure` append `Stretch`.
- `not_mentioned` displays `Không đề cập`.
- `unclear` displays `Chưa rõ` and adds a verification item.
- APAC country-lock text is explicit and cannot be summarized as merely remote.
- Existing salary, benefits, company footprint, outreach, and direct-link lines remain.

## Error Handling

- A failed source produces a source-health failure log and does not fail other stages.
- Link-check timeout, access challenge, or login wall produces `uncertain`, not `closed`.
- Gemini failure invokes the deterministic fallback.
- Invalid cloud enums normalize to `unclear`.
- Invalid or missing posting dates remain unknown.
- Database migration and read paths provide defaults for pre-upgrade rows.
- Telegram delivery behavior and delivery deduplication remain unchanged.

## Testing Strategy

Implementation is test-driven and covers:

1. Policy version 2 loads the new aliases, source stages, cloud terms, and enums.
2. Title matching accepts every requested alias and keeps FDE at priority one.
3. Generic Integration Engineer results without an approved domain are rejected.
4. Mandatory cloud wording and core Kubernetes/Terraform/DevOps/SRE/MLOps responsibility reject candidates.
5. Preferred, bonus, familiarity, and exposure wording stays alertable and becomes stretch.
6. A bare cloud technology mention does not become mandatory without supporting wording.
7. Candidate URLs override aggregator metadata for LinkedIn Post and Job source types.
8. Stage allocation considers Posts and Jobs within the bounded LLM budget and redistributes unused capacity.
9. Pending alerts order Posts before Jobs and FDE before adjacent families inside each stage.
10. Vietnam, uncertain APAC, APAC country-lock, non-APAC country-lock, and relocation cases follow the agreed ordering and actions.
11. Closed/expired evidence rejects; login walls and timeouts become uncertain.
12. Old Posts require a live official vacancy; live official Jobs may remain eligible after 30 days.
13. Cross-source reconciliation prefers an official apply URL without merging unrelated roles.
14. Additive database migration, round-trip persistence, searching, and alert fingerprints include cloud assessment.
15. Gemini parsing, deterministic post-validation, and local fallback agree on hard cloud rejection.
16. Telegram output shows posting date, cloud status, stretch, source, location restriction, and verification items.
17. Existing scheduler, endpoint, dry-run, force, deduplication, and three-alert flood-control tests continue to pass.

The full repository test suite remains the release gate.

## Documentation and Operations

The standalone technical-headhunter prompt and README will be updated so manual browsing runs and the automated `fde-jobs` flow share the same cloud/location/source policy. Source-count assertions will be adjusted only for the focused queries actually added.

No deployment is part of the implementation unless separately requested. Before a future Vercel deployment, the operator should upgrade the outdated Vercel CLI from 58.5.1 to the current release with `npm i -g vercel@latest` or `pnpm add -g vercel@latest`.

## Acceptance Criteria

The feature is ready for implementation completion when:

- all requested aliases are discoverable and classified;
- LinkedIn Posts are processed and queued before LinkedIn Jobs;
- FDE is first within every source stage;
- cloud-mandatory core roles are deterministically suppressed;
- optional/exposure cloud roles are retained and labeled stretch;
- Vietnam eligibility and APAC country-lock are explicit;
- stale/closed/blocked evidence is handled conservatively;
- each Telegram message includes posting date and cloud assessment;
- every scan still sends at most three individual alerts;
- existing data migrates additively; and
- the full test suite passes.
