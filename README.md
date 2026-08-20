# news-keep-up

Automated Telegram digest for keeping up with AI, software engineering, forward deployed engineering, solution architecture, coding agents, AI tools, and high-signal technical discussions.

The long-lived scheduler service owns the production schedule. GitHub Actions
remains a manual fallback that calls the Vercel-hosted scheduler endpoint.

- FDE news: twice daily at `08:00` and `14:00` Asia/Ho_Chi_Minh.
- FDE interview guideline: `08:35`, `11:35`, and `14:35` Asia/Ho_Chi_Minh.
- FDE job alerts: every 30 minutes from `07:00` through `21:00` Asia/Ho_Chi_Minh.
- Engineer/AI news: twice daily at `09:15` and `16:00` Asia/Ho_Chi_Minh.

## Profiles

- `engineer`: general AI/SWE/FDE engineering digest from `config/sources.json`, delivered with `ENGINEER_TELEGRAM_*` env vars.
- `fde`: Forward Deployed Engineer industry digest from `config/fde_sources.json`, delivered with `FDE_TELEGRAM_*` env vars.
- `fde-interview`: compact Forward Deployed Engineer interview guideline flow using `FDE_TELEGRAM_*` env vars and `config/fde_interview_sources.json` for source coverage.
- `fde-jobs`: shared technical-headhunter flow for Forward Deployed Engineering, Solutions Engineering/Architecture, AI Consulting, Technical Presales, and Technical Account Management. It targets Mid through hands-on Lead IC roles in AI and enterprise SaaS. Automatic alerts require a concrete vacancy/hiring-post URL plus strong evidence that the role is workable from Vietnam; uncertain direct vacancies are kept for manual `/verify` review.
- `news`, `morning`, and `afternoon` remain as backward-compatible aliases using `TELEGRAM_*` env vars.

Engineer/AI-SWE sources include at least 150 feeds/searches, weighted toward practical AI agents, product workflows, engineering practices, automation, evals, LLMOps, observability, and AI-assisted engineering productivity. FDE news sources include at least 150 feeds/searches around customer rollout, field delivery, enterprise implementation, evals, governance, observability, and production deployment. FDE interview sources include at least 100 feeds/searches around FDE interview loops, customer-facing deployment, agent system design, evals, RAG, voice agents, security, and integration design.

### Technical Job Headhunter Policy

`fde-jobs` reads its machine policy from `config/job_search_policy.json`. The role-family order is Forward Deployed Engineering first, followed by Solutions Engineering and Architecture, AI Consulting, Technical Presales, and Technical Account Management. Accepted scope is Mid, Senior, Staff, and hands-on Lead individual-contributor work across AI/GenAI, agents, LLM/RAG, enterprise automation, and enterprise SaaS.

AI Consulting, Technical Presales, and Technical Account Management require direct technical evidence such as demos, PoCs, architecture, APIs, integration, troubleshooting, implementation, or production deployment. Pure quota, cold-calling, pipeline, renewal, or upsell work without technical scope is rejected.

Every evaluated item maps to one decision:

- `APPLY_NOW`: open role with confirmed technical scope and Vietnam eligibility.
- `VERIFY_FIRST`: qualifying role whose location, eligibility, seniority, or status still needs evidence.
- `DM_FIRST`: credible recruiter, hiring-manager, or team hiring signal worth contacting first.
- `WATCH`: company/team expansion signal without a concrete vacancy yet.
- `REJECT`: closed or out-of-scope role, disallowed seniority, insufficient technical scope, or explicit Vietnam incompatibility without relocation.

Unknown eligibility is retained as `VERIFY_FIRST` for manual review, but is never placed in the automatic alert queue. A bare `Remote` label is not enough: automatic alerts require explicit Vietnam scope or confident SEA/APAC/Asia/worldwide/work-from-anywhere evidence without a conflicting country lock. Country-specific roles such as Prague hybrid or Remote North America are excluded. Root homepages, generic careers/search pages, and other links that do not identify a concrete vacancy or hiring post are also excluded.

The flow does not ask for or score against a CV. Each scan sends at most three eligible alerts and leaves the rest pending for later scans. The standalone browsing-agent prompt is available at `docs/prompts/tech-job-headhunter-master-prompt.md`.

## Message Format

Engineer/AI digests send 2-3 tightly selected items per run. FDE digests send 3-5 items per run. Stored backfill is re-checked against the active profile relevance filter before selection, so generic AI/coding-agent items are not used just to fill any digest. Delivered items are excluded globally across profiles: an item already sent to the Engineer/AI thread is not sent again to FDE, and vice versa.

Each digest message is formatted for quick scanning:

```text
1. 🧭 English title
Source: Salesforce Engineering · Author: Unknown
Topic: field-engineering / enterprise-rollout
FDE topic: Engineering · Delivery/Ops
Fit: Impact: High (96/100) · Trust: High (91/100) · Importance: 88/100
Why read: A customer rollout pattern with reusable launch gates and ownership signals.
Scan:
• Rollout: Specific rollout change or deployment lesson.
• Evidence: Customer, stakeholder, metric, or production signal.
• Risk: Integration, governance, eval, rollback, or observability concern.
• Action: What a reader should inspect, test, or turn into a checklist.
• Fit: Why it belongs in this profile, not a generic AI feed.
Takeaway: One short Vietnamese takeaway.
Read: Read
```

Digest messages are split into two news items per Telegram message. FDE's 3-5 item digest is delivered twice daily as up to 3 Telegram messages so Telegram does not break long messages awkwardly. Scheduled runs stay silent when no qualifying item is found; manual previews still return a no-item diagnostic.

Backfilled items are marked:

```text
Backfill - still relevant
```

Before each digest is sent, Gemini performs a final batch review over candidates to rerank by impact, remove low-signal items, and tighten the displayed emoji, category, summary, Vietnamese takeaway, and role-specific impact. Final local ranking then combines source trust, role impact, practical content quality, recency, and backfill penalty. If Gemini is unavailable, cached or fallback enrichment is still used, but the same profile moderation and ranking gates still apply.

Each FDE interview delivery combines its thread announcement and at least two
compact drills into one Telegram message. Each drill explicitly says which
interview section and knowledge area it supports:

```text
🧭 FDE Interview Prep Thread
Time: 16 Jul 09:35 ICT
Schedule: 08:35, 11:35, 14:35 ICT
Contents: 2 focused drills

🧭 FDE Interview Guideline
1. 📊 Evals: Evals turn demos into deployments
🎯 FDE topic: Delivery/Ops
🧩 Interview focus: Deployment readiness
📚 Kiến thức: task success eval, safety eval, escalation rule, latency target, launch gate
💡 A strong FDE converts customer workflows into release gates.
🧪 Drill: Write 10 eval cases for billing, identity, timeout, and unsafe refund.
🔗 Source: OpenAI evals

2. 🔌 Integration: The last mile is API, auth, and messy data
🎯 FDE topic: Engineering
🧩 Interview focus: Integration design
📚 Kiến thức: auth, tenant boundary, retry, typed error, stale record, rate limit
💡 A customer deployment fails when typed errors and tenant boundaries are vague.
🧪 Drill: Create a failure matrix for 401, 403, 404, 409, 429, and 5xx.
🔗 Source: OpenAPI specification
```

### Telegram Action and Feedback

Interactive delivery adds an action loop without adding automatic messages:

- Each two-item news message gets numbered `👍`, `👎`, `📌`, and `✅` rows.
- Each job alert keeps one message and gets `📌 Lưu`, `💼 Apply`, `🔎 Verify`,
  and `🚫 Bỏ`.
- Each combined interview message gets one numbered `✅ Đã luyện`, `🔁 Nhắc
  lại`, and `🚫` row per drill.
- Button taps return a short Telegram toast; they do not post another chat
  message.
- Only save, apply, verify, or repeat opens work in the action queue. Done and
  dismiss close it; useful/noise reactions remain feedback only.

Queue state is isolated by Telegram user, chat, and profile. `/queue`,
`/saved`, and `/todo` show only the caller's open items. `/weekly` and
`/report` summarize the previous seven complete ICT calendar days. Engineer
and FDE news append one compact report to the first existing digest of each
week; the report is never sent as a separate notification. Job and interview
reports remain on demand.

Sprint 1 records delivery, feedback, and action outcomes for measurement. It
does not yet use feedback to change content ranking or source weights.

## Local Setup

```bash
python3 -m news_keep_up.main init-db
python3 -m news_keep_up.main run-digest --slot morning --dry-run
python3 -m news_keep_up.main run-digest --slot fde-interview --dry-run
```

Use `python` instead of `python3` on systems where `python` points to Python 3.11+.

## Environment

Required for real Telegram delivery:

- `GEMINI_API_KEY`
- `CRON_SECRET`
- `TELEGRAM_WEBHOOK_SECRET` is optional. If unset, Telegram webhooks use `CRON_SECRET` as the secret token.

Telegram delivery can use either the default env vars or profile-specific env vars:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `ENGINEER_TELEGRAM_BOT_TOKEN`, `ENGINEER_TELEGRAM_CHAT_ID`
- `FDE_TELEGRAM_BOT_TOKEN`, `FDE_TELEGRAM_CHAT_ID`

On Vercel, `GEMINI_API_KEY_B64`, `TELEGRAM_BOT_TOKEN_B64`, `ENGINEER_TELEGRAM_BOT_TOKEN_B64`, and `FDE_TELEGRAM_BOT_TOKEN_B64` are also supported as encoded fallbacks when direct provider-shaped secret values are rejected by the env-var API. Direct vars take precedence.

Required for durable production storage and duplicate prevention across cold starts/deploys:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

If Turso is not configured, the app uses local SQLite at `data/news-keep-up.db`. On Vercel, avoid `/tmp` for production because delivered-news markers can be lost between function instances.

Cost-control defaults:

- `MAX_LLM_ITEMS_PER_RUN=20`
- `MAX_LLM_CALLS_PER_DAY=40`
- `MAX_CANDIDATES_PER_SOURCE=10`
- `SOURCE_FETCH_TIMEOUT_SECONDS=5`
- `MAX_SOURCE_WORKERS=12`
- `MIN_RELEVANCE_SCORE=65`
- `BACKFILL_LOOKBACK_DAYS=10`

## Telegram Commands

Each profile can also receive Telegram commands through Vercel:

- `/help` lists commands
- `/latest`, `/digest`, `/today`, `/run` generate a fresh digest preview for the current chat
- `/search keyword` searches stored news
- `/analyze keyword` analyzes stored matches through the profile lens
- `/markread id|keyword|all` marks stored news as read so it will not be sent again
- `/interview` shows the next FDE interview guideline in the FDE group
- `/sources` shows source coverage and recent problem sources when fetch logs exist
- `/status` shows schedule and config status
- `/focus` explains relevance criteria
- `/force` in the FDE jobs group scans and sends pending job alerts immediately, even outside the normal send window
- `/queue`, `/saved`, `/todo` show the calling user's open action queue
- `/weekly`, `/report` show the calling user's seven-day outcome report

The FDE jobs group adds scoped job queries:

- `/jobs [keywords]`, `/fit [keywords]`, `/list [keywords]`, `/new [keywords]`, and `/open [keywords]` list only suitable jobs with strong Vietnam eligibility.
- `/vn [keywords]` lists roles explicitly open in Vietnam.
- `/sea [keywords]` lists suitable SEA/APAC/global remote roles with confident cross-border evidence.
- `/remote [keywords]` lists only suitable remote roles; country-locked remote jobs are omitted.
- `/high [keywords]` lists suitable jobs whose stored priority is exactly `High`.
- `/verify [keywords]` lists concrete vacancies whose Vietnam eligibility remains uncertain. These rows are never auto-sent.
- `/company <name>`, `/query <keywords>`, and `/search <keywords>` search only suitable jobs in this group.
- `/salary [keywords]` and `/benefits [keywords]` apply the same suitability gate before checking those fields.
- `/commands` is an alias for the FDE jobs command menu.

Multi-word queries use AND semantics across job fields: `/jobs python remote` requires every word to match somewhere in the same opportunity.

Webhook endpoints:

- `/api/telegram/engineer`
- `/api/telegram/fde`
- `/api/telegram/fde-jobs`

Commands and button callbacks use the same profile webhook endpoints. Telegram
must send `X-Telegram-Bot-Api-Secret-Token` matching
`TELEGRAM_WEBHOOK_SECRET` or `CRON_SECRET`. Responses are restricted to the
configured profile chat ID when `ENGINEER_TELEGRAM_CHAT_ID` or
`FDE_TELEGRAM_CHAT_ID` is set.

## FDE Learning Source Roadmap

These repositories are approved candidates for a future licensed, pinned,
quality-gated FDE learning adapter:

- [Forward Deployed Engineer Material](https://github.com/weissmanntobi-del/Forward_Deployed_Engineer_Material)
- [Awesome FDE Resources](https://github.com/global-fde/awesome-fde-resources)
- [FDE Interview Mastery](https://github.com/vivianaranha/fde-interview-mastery)

They are references only in Sprint 1. The current interview runtime still uses
its reviewed static guideline pool and does not ingest these repositories.

## Scheduler Service

Run the scheduler as a long-lived worker service. This is the primary production path for frequent jobs; it runs ticks in-process, catches up delayed slots with Turso `scheduler_runs`, and avoids depending on GitHub Actions or Vercel Cron cadence.

One-shot check:

```bash
.venv/bin/python -m news_keep_up.main scheduler-tick \
  --env-file .vercel/.env.production.local \
  --lookback-minutes 180
```

Long-running worker:

```bash
.venv/bin/python -m news_keep_up.main scheduler-worker \
  --env-file .vercel/.env.production.local \
  --interval-seconds 60 \
  --lookback-minutes 180
```

Force the FDE jobs flow outside the normal send window:

```bash
.venv/bin/python -m news_keep_up.main run-digest \
  --env-file .vercel/.env.production.local \
  --slot fde-jobs \
  --force
```

Inspect source health from recent fetch logs:

```bash
.venv/bin/python -m news_keep_up.main source-health \
  --env-file .vercel/.env.production.local \
  --slot fde-jobs
```

Fetch all FDE job sources and log source health without Gemini classification or Telegram delivery:

```bash
.venv/bin/python -m news_keep_up.main probe-job-sources \
  --env-file .vercel/.env.production.local
```

The app decides which profile is due in Asia/Ho_Chi_Minh time and stores each scheduled run in Turso so retries do not resend the same slot:

- FDE news: twice daily at `08:00` and `14:00`
- FDE interview guidelines: `08:35`, `11:35`, and `14:35`
- FDE job alerts: every 30 minutes from `07:00` through `21:00`
- FDE job source maintenance: daily at `07:10`
- Engineer/AI news: twice daily at `09:15` and `16:00`

Service templates:

- macOS launchd: `ops/launchagents/com.news-keep-up.scheduler-worker.plist`
- Linux systemd: `ops/systemd/news-keep-up-scheduler.service`

## GitHub Actions

The workflow in `.github/workflows/digest.yml` is manual fallback only. It still calls `/api/scheduler/tick` when triggered with `workflow_dispatch`, but it no longer owns the periodic schedule.

## Local LaunchAgent Scheduler

For a local always-on macOS agent, install `ops/launchagents/com.news-keep-up.scheduler-worker.plist` into `~/Library/LaunchAgents/`. It runs `scheduler-worker` continuously and reads production environment variables from `.vercel/.env.production.local`. If a due slot has no qualifying news, scheduled delivery stays silent.

The older `ops/launchagents/com.news-keep-up.scheduler-tick.plist` remains only for endpoint fallback testing. Logs are written to `~/Library/Logs/news-keep-up/`.

## Vercel

The Vercel deployment exposes `news_keep_up.vercel_app:app`:

- `/api/digest/news` runs the production digest
- `/api/digest/engineer` runs the engineer digest
- `/api/digest/fde` runs the Forward Deployed Engineer digest
- `/api/digest/fde-interview` sends the compact FDE interview guideline
- `/api/digest/fde-jobs?force=true` runs FDE job alerts immediately and bypasses the send window
- `/api/scheduler/tick` runs due scheduled profiles as a manual/fallback trigger and records them in Turso
- `/api/telegram/engineer` handles Engineer bot commands
- `/api/telegram/fde` handles FDE bot commands
- `/api/telegram/fde-jobs` handles FDE jobs bot commands
- `?dry_run=true` formats the digest without sending Telegram

Configure the Vercel environment variables listed above for production. `CRON_SECRET` must be set so scheduled callers can authenticate requests with `Authorization: Bearer $CRON_SECRET`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Docs

- Design spec: `docs/superpowers/specs/2026-07-06-news-keep-up-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-06-news-keep-up.md`
- Technical headhunter design: `docs/superpowers/specs/2026-08-06-tech-job-headhunter-master-prompt-design.md`
- Technical headhunter implementation plan: `docs/superpowers/plans/2026-08-06-tech-job-headhunter-master-prompt.md`
- Strict FDE eligibility/query design: `docs/superpowers/specs/2026-08-13-fde-job-eligibility-telegram-query-design.md`
- Strict FDE eligibility/query plan: `docs/superpowers/plans/2026-08-13-fde-job-eligibility-telegram-query.md`
- Telegram action/feedback design: `docs/superpowers/specs/2026-08-21-telegram-action-feedback-sprint-1-design.md`
- Telegram action/feedback implementation plan: `docs/superpowers/plans/2026-08-21-telegram-action-feedback-sprint-1.md`
- Standalone technical headhunter prompt: `docs/prompts/tech-job-headhunter-master-prompt.md`
