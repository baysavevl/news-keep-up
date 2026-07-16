# news-keep-up

Automated Telegram digest for keeping up with AI, software engineering, forward deployed engineering, solution architecture, coding agents, AI tools, and high-signal technical discussions.

GitHub Actions owns the schedule and calls the Vercel-hosted endpoints:

- FDE news: every 2 hours at `:20`, from 07:20 through 21:20 Asia/Ho_Chi_Minh.
- FDE interview guideline: hourly at `:35`, from 07:35 through 22:35 Asia/Ho_Chi_Minh.
- Engineer news: every 3 hours at `:40`, from 07:40 through 22:40 Asia/Ho_Chi_Minh.

## Profiles

- `engineer`: general AI/SWE/FDE engineering digest from `config/sources.json`, delivered with `ENGINEER_TELEGRAM_*` env vars.
- `fde`: Forward Deployed Engineer industry digest from `config/fde_sources.json`, delivered with `FDE_TELEGRAM_*` env vars.
- `fde-interview`: compact Forward Deployed Engineer interview guideline flow using `FDE_TELEGRAM_*` env vars and `config/fde_interview_sources.json` for source coverage.
- `news`, `morning`, and `afternoon` remain as backward-compatible aliases using `TELEGRAM_*` env vars.

Engineer/AI-SWE sources include at least 150 feeds/searches, weighted toward practical AI agents, product workflows, engineering practices, automation, evals, LLMOps, observability, and AI-assisted engineering productivity. FDE news sources include at least 150 feeds/searches around customer rollout, field delivery, enterprise implementation, evals, governance, observability, and production deployment. FDE interview sources include at least 100 feeds/searches around FDE interview loops, customer-facing deployment, agent system design, evals, RAG, voice agents, security, and integration design.

## Message Format

Engineer/AI digests send 2-3 tightly selected items per run. FDE digests send 3-5 items per run. Stored backfill is re-checked against the active profile relevance filter before selection, so generic AI/coding-agent items are not used just to fill any digest. Delivered items are excluded globally across profiles: an item already sent to the Engineer/AI thread is not sent again to FDE, and vice versa.

Each news thread starts with a standalone announcement message so Telegram groups are easy to scan:

```text
🧭 FDE News Thread
Time: 16 Jul 09:20 ICT
Schedule: every 2 hours at :20
Scope: Customer rollout, field delivery, enterprise implementation
Selected: 4 items · 1 fresh · 3 backfill
```

Each item is formatted for quick scanning:

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

Digest messages are split into two news items per Telegram message. FDE's 3-5 item digest is delivered every 2 hours as up to 3 Telegram messages so Telegram does not break long messages awkwardly.

Backfilled items are marked:

```text
Backfill - still relevant
```

Before each digest is sent, Gemini performs a final batch review over candidates to rerank by impact, remove low-signal items, and tighten the displayed emoji, category, summary, Vietnamese takeaway, and role-specific impact. Final local ranking then combines source trust, role impact, practical content quality, recency, and backfill penalty. If Gemini is unavailable, cached or fallback enrichment is still used, but the same profile moderation and ranking gates still apply.

FDE interview guideline messages also start with a standalone thread announcement and include at least two compact contents. Each content explicitly says which interview section and knowledge area it supports:

```text
🧭 FDE Interview Prep Thread
Time: 16 Jul 09:35 ICT
Schedule: hourly at :35
Contents: 2 focused drills
FDE topics: Engineering · Product

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
- `/sources` shows source coverage
- `/status` shows schedule and config status
- `/focus` explains relevance criteria

Webhook endpoints:

- `/api/telegram/engineer`
- `/api/telegram/fde`

Telegram must send `X-Telegram-Bot-Api-Secret-Token` matching `TELEGRAM_WEBHOOK_SECRET` or `CRON_SECRET`. Command responses are restricted to the configured profile chat ID when `ENGINEER_TELEGRAM_CHAT_ID` or `FDE_TELEGRAM_CHAT_ID` is set.

## GitHub Actions

Configure repository secrets:

- `CRON_SECRET`

The workflow is in `.github/workflows/digest.yml`. It is a fallback scheduler that calls `/api/scheduler/tick` at `:08`, `:23`, `:38`, and `:53` from `00:00` through `15:59` UTC. The app decides which profile is due in Asia/Ho_Chi_Minh time and stores each scheduled run in Turso so retries do not resend the same slot:

- FDE news: every 2 hours from `07:20` through `21:20`
- FDE interview guidelines: hourly from `07:35` through `22:35`
- Engineer news: hourly from `07:40` through `22:40`

Vercel Cron is not configured because the current Vercel Hobby plan only supports once-per-day cron cadence. On Vercel Pro, configure a frequent cron against `/api/scheduler/tick`; GitHub Actions and the local LaunchAgent can keep running as idempotent fallbacks.

## Local LaunchAgent Scheduler

For a local always-on macOS agent, install `ops/launchagents/com.news-keep-up.scheduler-tick.plist` into `~/Library/LaunchAgents/`. It runs `scripts/trigger_scheduler_tick.py` every 5 minutes and calls `/api/scheduler/tick`; the app still controls exact send times and uses Turso `scheduler_runs` to avoid duplicate sends. If a due slot has no qualifying news, the digest sends a short heartbeat message so the Telegram group still confirms scheduler and delivery health.

The installed runtime copy should live under `~/Library/Application Support/news-keep-up/` with a private `.env` containing `CRON_SECRET`. Logs are written to `~/Library/Logs/news-keep-up/`.

## Vercel

The Vercel deployment exposes `news_keep_up.vercel_app:app`:

- `/api/digest/news` runs the production digest
- `/api/digest/engineer` runs the engineer digest
- `/api/digest/fde` runs the Forward Deployed Engineer digest
- `/api/digest/fde-interview` sends the compact FDE interview guideline
- `/api/scheduler/tick` runs at most one due scheduled profile and records it in Turso
- `/api/telegram/engineer` handles Engineer bot commands
- `/api/telegram/fde` handles FDE bot commands
- `?dry_run=true` formats the digest without sending Telegram

Configure the Vercel environment variables listed above for production. `CRON_SECRET` must be set so scheduled callers can authenticate requests with `Authorization: Bearer $CRON_SECRET`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Docs

- Design spec: `docs/superpowers/specs/2026-07-06-news-keep-up-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-06-news-keep-up.md`
