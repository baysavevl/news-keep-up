# news-keep-up

Automated Telegram digest for keeping up with AI, software engineering, forward deployed engineering, solution architecture, coding agents, AI tools, and high-signal technical discussions.

GitHub Actions owns the schedule and calls the Vercel-hosted endpoints:

- FDE news: hourly at `:20`, from 07:20 through 22:20 Asia/Ho_Chi_Minh.
- FDE interview guideline: every 2 hours at `:35`, from 07:35 through 21:35 Asia/Ho_Chi_Minh.
- Engineer news: hourly at `:40`, from 07:40 through 22:40 Asia/Ho_Chi_Minh.

## Profiles

- `engineer`: general AI/SWE/FDE engineering digest from `config/sources.json`, delivered with `ENGINEER_TELEGRAM_*` env vars.
- `fde`: Forward Deployed Engineer industry digest from `config/fde_sources.json`, delivered with `FDE_TELEGRAM_*` env vars.
- `fde-interview`: compact Forward Deployed Engineer interview guideline flow using `FDE_TELEGRAM_*` env vars and `config/fde_interview_sources.json` for source coverage.
- `news`, `morning`, and `afternoon` remain as backward-compatible aliases using `TELEGRAM_*` env vars.

Engineer sources include 86 feeds/searches, with the new additions weighted toward AI agents, agent orchestration, automation, evals, LLMOps, observability, and AI-assisted engineering productivity. FDE interview sources include 30 feeds/searches around FDE interview loops, customer-facing deployment, agent system design, evals, RAG, voice agents, security, and integration design.

## Message Format

Each item is formatted for quick scanning:

```text
1. 🧭 English title
📰 Source: Salesforce Engineering | ✍️ Author: Unknown
🏷 Category: field-engineering / enterprise-rollout
💡 Ý chính: Key idea.
✨ Highlights:
• Specific highlight.
• Role-specific impact.
🇻🇳 VN: One short Vietnamese takeaway.
🔗 Read: Read

-----
🔥 Popularity: Medium (70/100) | 🛡 Trust: High (91/100)
⚖️ Importance: 88/100 | 🎯 Impact: High (96/100)
```

Digest messages are split into two news items per Telegram message. FDE's 8-item hourly digest is delivered as 4 Telegram messages so Telegram does not break long messages awkwardly.

Backfilled items are marked:

```text
Backfill - still relevant
```

Before each digest is sent, Gemini performs a final batch review over candidates to rerank by impact, remove low-signal items, and tighten the displayed emoji, category, summary, Vietnamese takeaway, and role-specific impact. If Gemini is unavailable, cached or fallback enrichment is still used so the automation keeps running.

FDE interview guideline messages are intentionally shorter:

```text
🧭 FDE Interview Guideline
🎯 Evals: Evals turn demos into deployments
💡 A strong FDE converts customer workflows into release gates.
🧪 Drill: Write 10 eval cases for billing, identity, timeout, and unsafe refund.
🔗 Source: OpenAI evals
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

The workflow is in `.github/workflows/digest.yml`. It calls `/api/scheduler/tick` every 5 minutes from `00:00` through `15:55` UTC. The app decides which profile is due in Asia/Ho_Chi_Minh time and stores each scheduled run in Turso so retries do not resend the same slot:

- FDE news: hourly from `07:20` through `22:20`
- FDE interview guidelines: every 2 hours from `07:35` through `21:35`
- Engineer news: hourly from `07:40` through `22:40`

Vercel Cron is not configured because the current Vercel Hobby plan only supports once-per-day cron cadence. The scheduler endpoint is compatible with a future Pro Vercel Cron setup by pointing a frequent cron at `/api/scheduler/tick`.

## Local LaunchAgent Scheduler

For a local always-on macOS agent, install `ops/launchagents/com.news-keep-up.scheduler-tick.plist` into `~/Library/LaunchAgents/`. It runs `scripts/trigger_scheduler_tick.py` every 5 minutes and calls `/api/scheduler/tick`; the app still controls exact send times and uses Turso `scheduler_runs` to avoid duplicate sends.

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
