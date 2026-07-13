# news-keep-up

Automated Telegram digest for keeping up with AI, software engineering, forward deployed engineering, solution architecture, coding agents, AI tools, and high-signal technical discussions.

The digests run hourly from 08:00 through 22:00 Asia/Ho_Chi_Minh. GitHub Actions owns the schedule and calls the Vercel-hosted digest endpoints: FDE at `:20`, Engineer at `:40`.

## Profiles

- `engineer`: general AI/SWE/FDE engineering digest from `config/sources.json`, delivered with `ENGINEER_TELEGRAM_*` env vars.
- `fde`: Forward Deployed Engineer industry digest from `config/fde_sources.json`, delivered with `FDE_TELEGRAM_*` env vars.
- `news`, `morning`, and `afternoon` remain as backward-compatible aliases using `TELEGRAM_*` env vars.

## Message Format

Each item is formatted for quick scanning:

```text
1. 🧭 English title
🏷 Category: field-engineering / enterprise-rollout | From: Salesforce Engineering
🔥 Popularity: Medium (70/100) | 🛡 Trust: High (91/100)
⚖️ Importance: 88/100 | 🎯 Impact: High (96/100)
💡 Ý chính: Key idea.
✨ Highlights:
• Specific highlight.
• Role-specific impact.
🇻🇳 VN: One short Vietnamese takeaway.
🔗 Read: Read
```

Backfilled items are marked:

```text
Backfill - still relevant
```

## Local Setup

```bash
python3 -m news_keep_up.main init-db
python3 -m news_keep_up.main run-digest --slot morning --dry-run
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

Optional for durable automation storage:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

If Turso is not configured, the app uses local SQLite at `data/news-keep-up.db`.

Cost-control defaults:

- `MAX_LLM_ITEMS_PER_RUN=20`
- `MAX_LLM_CALLS_PER_DAY=40`
- `MAX_CANDIDATES_PER_SOURCE=10`
- `SOURCE_FETCH_TIMEOUT_SECONDS=5`
- `MAX_SOURCE_WORKERS=12`
- `MIN_RELEVANCE_SCORE=65`
- `BACKFILL_LOOKBACK_DAYS=7`

## Telegram Commands

Each profile can also receive Telegram commands through Vercel:

- `/help` lists commands
- `/latest`, `/digest`, `/today`, `/run` generate a fresh digest preview for the current chat
- `/search keyword` searches stored news
- `/analyze keyword` analyzes stored matches through the profile lens
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

The workflow is in `.github/workflows/digest.yml`. It runs FDE at `20 1-15 * * *` UTC and Engineer at `40 1-15 * * *` UTC, equivalent to hourly from 08:20/08:40 through 22:20/22:40 ICT. It calls `/api/digest/fde` and `/api/digest/engineer` with `CRON_SECRET`; the Telegram/Gemini runtime configuration remains in Vercel.

## Vercel

The Vercel deployment exposes `news_keep_up.vercel_app:app`:

- `/api/digest/news` runs the production digest
- `/api/digest/engineer` runs the engineer digest
- `/api/digest/fde` runs the Forward Deployed Engineer digest
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
