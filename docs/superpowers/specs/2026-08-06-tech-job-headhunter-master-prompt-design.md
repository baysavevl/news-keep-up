# Technical Job Headhunter Master Prompt and Shared Policy Design

Date: 2026-08-06

## Goal

Create one reusable headhunter master prompt and one shared machine-readable policy for discovering, verifying, ranking, and alerting on technical customer-facing jobs. The standalone prompt and the `fde-jobs` pipeline must apply the same scope and decision rules so that manual searches, Gemini classification, deterministic prefiltering, and fallback classification do not drift apart.

The system must alert on every new opportunity that satisfies the role, technical-scope, seniority, domain, and location rules. It must not require a CV or reject a job because the user's background is unknown.

## Approved Search Scope

### Role priority

1. Forward Deployed Engineer and close title variants.
2. Solutions Engineer and Solutions Architect.
3. AI Consultant with implementation or customer-delivery responsibility.
4. Technical Presales or Sales Engineer.
5. Technical Account Manager.

FDE remains the highest-ranked role family, but every qualifying role family is eligible for alerting.

### Seniority

Accept:

- Mid-level individual contributor.
- Senior individual contributor.
- Staff individual contributor.
- Lead individual contributor.

Reject explicit intern, graduate, entry-level, junior, manager, director, head, and executive roles. A role with no reliable seniority evidence remains eligible and is labeled `VERIFY_FIRST`. A lead role is accepted only when the evidence describes an individual-contributor or hands-on technical scope rather than people management.

### Domain

Accept roles connected to at least one of these domains:

- AI, GenAI, AI agents, LLM, RAG, or enterprise automation.
- Enterprise SaaS products or platforms.

A company category alone is not enough when the role itself is non-technical.

### Location and work arrangement

Rank location eligibility in this order:

1. Remote or WFH with explicit Vietnam eligibility.
2. Remote APAC, SEA, Asia, or global with plausible but unconfirmed Vietnam eligibility.
3. Hybrid or onsite in Vietnam.
4. APAC relocation opportunities.

Reject roles that explicitly exclude Vietnam and provide no approved relocation path. Never infer that `remote`, `APAC`, `SEA`, `global`, or a Singapore location automatically permits working from Vietnam.

## Non-Goals

- Do not evaluate the user against a CV or LinkedIn profile.
- Do not generate application documents automatically.
- Do not auto-apply or contact recruiters.
- Do not invent compensation, benefits, contacts, dates, locations, or eligibility.
- Do not replace the existing Telegram delivery profile or create separate job bots in this iteration.
- Do not introduce a new external paid search dependency.

## Core Design

Use a shared-policy architecture:

```text
Job sources
  -> shared deterministic prefilter
  -> Gemini classifier built from the master policy
  -> deterministic validation guardrails
  -> JobOpportunity persistence and deduplication
  -> ranked delivery queue
  -> Telegram alert
```

The standalone master prompt explains the full search procedure and returns both a concise human report and structured JSON. The application uses the same role catalog, evidence requirements, enums, and rejection rules when building the Gemini classification prompt.

## Artifacts and Ownership

### `config/job_search_policy.json`

This is the machine-readable source of truth. It owns:

- Policy version.
- Base location and location priority.
- Target seniority and exclusion terms.
- Target domains.
- Role families and ranking order.
- Title aliases for each role family.
- Required technical-scope signals.
- Role-specific negative signals.
- Decision and action enums.
- Source trust order.
- Hard rejection rules.

The config must be explicit and validated. Missing required sections or unknown enum values fail fast instead of silently broadening the search.

### `docs/prompts/tech-job-headhunter-master-prompt.md`

This is the copy-and-paste prompt for a browsing-capable AI. It is self-contained, does not ask for a CV, and instructs the AI to start the search using the approved defaults. If browsing is unavailable, it must state that limitation and return the query pack and search plan rather than fabricate results.

### `news_keep_up/job_search_policy.py`

This module loads and validates the policy, normalizes titles and evidence, builds prompt-ready policy text, and exposes deterministic decisions used by prefiltering and post-LLM guardrails.

The module must provide small, testable operations for:

- Matching a role family.
- Detecting technical evidence.
- Evaluating seniority.
- Evaluating location eligibility.
- Evaluating domain scope.
- Applying hard rejection rules.
- Mapping a result to a decision and delivery priority.

### Existing modules

- `news_keep_up/job_alerts.py` uses the shared matcher and ranking policy. Keep `is_fde_job_candidate` as a compatibility wrapper while introducing a role-neutral internal matcher.
- `news_keep_up/gemini.py` renders the classification prompt from the shared policy and validates model output against deterministic rules.
- `news_keep_up/job_filters.py` keeps location and workability checks but consumes shared policy values rather than duplicating scope.
- `news_keep_up/source_intelligence.py` uses the shared title, domain, and region signals when discovering new ATS and career sources.
- `news_keep_up/models.py` and the current database schema remain compatible in this iteration.

## Role Catalog and Technical Gate

Every result must match a target role family. Presales, Sales Engineer, and TAM results must also contain direct technical evidence; a title alone is insufficient.

| Role family | Representative title aliases | Required or strongly preferred evidence | Reject when |
| --- | --- | --- | --- |
| Forward Deployed Engineering | Forward Deployed Engineer, Forward Deployment Engineer, Deployed Engineer, Deployment Strategist, AI Deployment Engineer | Customer deployment, implementation, integration, production rollout, solution design, technical discovery | The title is a non-engineering use of “forward deployed,” or the work is not technical |
| Solutions Engineering and Architecture | Solution Engineer, Solutions Engineer, Customer Engineer, Field Engineer, Solution Architect, Solutions Architect, Customer Success Architect, Delivery Solutions Architect | Demo, PoC, architecture, system design, security, data flow, API, integration, troubleshooting, technical discovery, implementation, deployment | The role is sales-only, customer service without technical ownership, or enterprise architecture governance without relevant product or customer delivery scope |
| AI Consulting | AI Consultant, GenAI Consultant, Technical Consultant, Implementation Consultant | AI implementation, workflow design, LLM/RAG/agent delivery, architecture, integration, productionization | The work is strategy-only, generic management consulting, or pure research |
| Technical Presales | Presales Engineer, Pre-sales Engineer, Sales Engineer, Solutions Consultant | Demo, PoC, solutioning, technical discovery, API/integration, architecture, security review | Quota, prospecting, cold sales, pipeline ownership, or renewals dominate and no technical evidence exists |
| Technical Account Management | Technical Account Manager, Technical Success Manager, Customer Success Engineer | Technical adoption, troubleshooting, architecture, integration, incident escalation, implementation guidance | Account management, renewals, upsell, relationship management, or quota dominates without technical evidence |

Title variants may broaden discovery, but responsibilities and source evidence determine the final decision.

## Master Prompt Design

The standalone prompt contains six ordered blocks.

### 1. Role and operating instructions

The AI acts as an experienced technical headhunter. Its task is to discover and verify opportunities, not to provide generic career coaching. It must search immediately with the approved defaults and must not request a CV.

### 2. Search profile

The prompt embeds the approved role priority, seniority, domains, and location order. It states that every qualifying opportunity is reportable, even when compensation or required skills are missing.

### 3. Search playbook

The AI must:

1. Expand each role family into title aliases and responsibility keywords.
2. Create several focused Boolean queries rather than one oversized query.
3. Search official company career pages and public ATS boards first.
4. Search LinkedIn Jobs and create role/company alerts where appropriate.
5. Search LinkedIn Posts for recruiter, hiring-manager, and team-growth signals.
6. Search relevant job boards, communities, and company expansion announcements.
7. Treat aggregators as discovery leads and look for the canonical employer or ATS page.
8. Verify status, date, location, work arrangement, and applicant-location restrictions.
9. Find a public contact only when a source provides evidence for the person's identity and role.
10. Deduplicate before returning results.

Boolean operators must use the syntax supported by the target platform. For LinkedIn, use uppercase `AND`, `OR`, and `NOT`, exact phrases in quotes, and parentheses. Split role families into multiple queries to stay within consumer-search Boolean limits.

### 4. Evidence and verification

Evidence is classified as:

- `HARD`: explicit Vietnam eligibility, Vietnam location, or an unambiguous approved relocation path on an official source.
- `MEDIUM`: APAC, SEA, Asia, or global language makes Vietnam plausible but not explicit.
- `WEAK`: the role is relevant, but status, location, or eligibility evidence is incomplete.

Source trust order is:

1. Official company career page or official ATS posting.
2. Official recruiter, hiring manager, or company post.
3. Established job board or community hiring thread.
4. Aggregator or search result used only as a lead.

The prompt must distinguish sourced facts from inference. Unknown fields remain empty and are added to `what_to_verify`.

### 5. Decision policy

- `APPLY_NOW`: a concrete open role, sufficient technical evidence, accepted seniority, and hard Vietnam or approved relocation evidence.
- `VERIFY_FIRST`: a concrete role within scope whose Vietnam eligibility, seniority, or open status needs confirmation.
- `DM_FIRST`: a credible recruiter, hiring-manager, or team post that should be approached directly, with or without a formal apply link.
- `WATCH`: a credible expansion or hiring signal without a concrete vacancy.
- `REJECT`: closed or expired, wrong role, wrong domain, disallowed seniority, insufficient technical scope, fabricated or misleading, or explicitly incompatible with Vietnam and relocation rules.

All decisions except `REJECT` are alertable. Priority affects ordering only and never suppresses a qualifying result.

### 6. Output contract

The prompt returns a concise summary followed by a JSON block in this shape. `should_alert` is `false` only for `REJECT` and is `true` for every other valid decision.

```json
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
```

For the application classifier, existing `JobOpportunity` fields remain authoritative:

- `role_family` maps to `category`.
- `decision` maps to `recommended_action` and existing status fields.
- `technical_evidence` is summarized into `why_it_fits` so the evidence survives persistence without a schema migration.
- `hidden_hiring_signal` maps to `linkedin_post_signal` when it is a LinkedIn signal and to `company_expansion_signal` otherwise.

## Application Pipeline

### Candidate discovery

Continue using the current source fetchers and source configuration. Broaden source terms through the shared policy to include the approved role aliases and enterprise SaaS signals. Public ATS APIs and official career pages are preferred where available; discovery-source maintenance continues to find candidate ATS and career sources.

### Deterministic prefilter

The prefilter should be broad enough to avoid false negatives. It admits a candidate when it contains:

- A target title or strong role-responsibility signal.
- An accepted domain signal.
- No unambiguous hard rejection.

Unknown location or seniority does not cause prefilter rejection. Those fields are resolved by classification and can produce `VERIFY_FIRST`.

### Gemini classification

`build_job_classification_prompt` retains its public call pattern and renders the compact application variant of the master policy. Candidate content remains bounded to control token use. Gemini returns the existing `JobOpportunity`-compatible shape plus the decision semantics described above.

### Deterministic post-validation

Local validation has final authority over hard rules:

- Force `should_alert=false` for `REJECT` or `closed` results.
- Force `should_alert=true` for all other valid decisions.
- Downgrade unsupported explicit eligibility to `verify`.
- Reject pure sales or account-management roles without technical evidence.
- Reject explicit disallowed seniority.
- Reject explicit location incompatibility without relocation evidence.
- Preserve unknown data as unknown rather than synthesizing values.

If Gemini is unavailable or returns invalid JSON, the fallback classifier uses the same policy and produces conservative `VERIFY_FIRST` decisions for incomplete but relevant evidence.

## Ranking and Delivery

Order pending opportunities by:

1. Decision: `APPLY_NOW`, `DM_FIRST`, `VERIFY_FIRST`, then `WATCH`.
2. Role-family priority, with FDE first.
3. Evidence strength and confidence.
4. Explicit Vietnam or approved relocation evidence.
5. Freshness and source trust.

Keep the existing maximum of three Telegram alerts per scan. Every other qualifying result remains pending and is delivered on a later scan; the batch limit is flood control, not a relevance filter.

The Telegram alert must show:

- Decision and confidence.
- Role title and role family.
- Company, seniority, and technical evidence.
- Domain, location, remote policy, and Vietnam eligibility.
- Status, source type, and canonical apply or source link.
- Why the item was sent and what remains to verify.
- Recommended action and an evidence-based outreach angle when available.

## Deduplication and Material Updates

Primary deduplication uses canonical apply URL. When no canonical apply URL exists, use normalized company, role title, location, and source identity.

Do not resend an unchanged opportunity. A new alert is allowed when a material field changes:

- The role reopens.
- Eligibility improves or changes.
- Location or remote policy changes.
- An official apply link appears.
- A hidden-hiring signal becomes a concrete vacancy.

Normalize common title differences such as `Sr.` and `Senior` before fallback deduplication. Hidden-hiring signals use company, role family, public poster identity when available, source URL, and a bounded time window.

## Failure Handling

- Invalid policy config fails fast with a clear diagnostic.
- One source failure does not stop other sources; source-health logging remains active.
- Gemini timeout, quota, invalid JSON, or schema mismatch falls back to local classification.
- Missing evidence produces `VERIFY_FIRST` or `WATCH`, not invented facts.
- Aggregator-only results retain the aggregator URL and list the official source as something to verify.
- A Telegram delivery failure leaves the opportunity pending for retry.
- Existing alert fingerprints and delivery records remain compatible.

## Testing Strategy

### Policy tests

- The config loads and validates all required fields and enums.
- Every role family has aliases, technical signals, and negative signals.
- Invalid or incomplete policy fails clearly.

### Matching tests

- Positive fixtures cover all target role families.
- Technical Presales and TAM with PoC, demo, architecture, API, integration, troubleshooting, or implementation evidence pass.
- Quota-led Presales, Sales, and account-management-only TAM fixtures fail.
- Enterprise SaaS technical roles pass; non-technical SaaS roles fail.
- Mid, Senior, Staff, and Lead IC pass.
- Junior and management-track roles fail.
- Unknown seniority remains eligible as `VERIFY_FIRST`.
- Explicit Vietnam, ambiguous APAC, Vietnam onsite, APAC relocation, and incompatible remote locations classify correctly.
- Hidden-hiring and expansion signals map to `DM_FIRST` and `WATCH`.

### Prompt and parsing tests

- The standalone master prompt contains every approved scope and no unresolved placeholders.
- The application prompt contains the same enums and hard rules while staying within a bounded size.
- Gemini parsing and fallback classification yield compatible decisions.
- The model cannot override deterministic hard rejections.
- Unknown values are not fabricated.

### Pipeline tests

- Every non-rejected opportunity is persisted with `should_alert=true`.
- The three-alert batch limit leaves remaining opportunities pending.
- Canonical and normalized fallback deduplication work.
- Material updates can alert again while unchanged jobs cannot.
- Telegram formatting includes the approved decision, technical, location, verification, and action fields.
- Source or LLM failures do not lose previously stored opportunities.

## Acceptance Criteria

The work is complete when:

1. A standalone master prompt can be copied into a browsing-capable AI and run without a CV.
2. The standalone prompt reports the approved five role groups, including enterprise SaaS, and distinguishes direct vacancies from hidden-hiring signals.
3. `fde-jobs` uses the same policy for deterministic prefiltering, Gemini classification, fallback classification, and source discovery.
4. Pure non-technical sales and account management are rejected while technically involved Presales and TAM roles are retained.
5. Every qualifying job is queued for Telegram delivery, with no CV-based suppression.
6. Location eligibility is evidence-based and ambiguous APAC or remote roles are clearly marked for verification.
7. Existing endpoints, schedules, database rows, and Telegram profile configuration remain compatible.
8. The full automated test suite passes.

## Reference Basis

- LinkedIn supports uppercase Boolean operators, exact quoted phrases, and parenthetical grouping: <https://www.linkedin.com/help/linkedin/answer/a524335/using-boolean-search-on-linkedin>
- LinkedIn consumer search limits the number of Boolean operators, so searches should be split by role family: <https://www.linkedin.com/help/linkedin/answer/a524411/boolean-query-limitations>
- LinkedIn supports job alerts for saved searches and company-specific alerts: <https://www.linkedin.com/help/linkedin/answer/a511279/job-alerts-on-linkedin>
- Google `JobPosting` guidance distinguishes fully remote work and applicant-location requirements and documents expired-job handling: <https://developers.google.com/search/docs/appearance/structured-data/job-posting>
- Public job-board interfaces are documented by Greenhouse, Lever, and Ashby: <https://developer.greenhouse.io/job-board.html>, <https://github.com/lever/postings-api>, and <https://developers.ashbyhq.com/docs/public-job-posting-api>
