# news-keep-up

Automated Telegram digest for keeping up with AI, software engineering, forward deployed engineering, solution architecture, coding agents, AI tools, and high-signal technical discussions.

The digest runs every two hours at :10 from 08:10 through 20:10 Asia/Ho_Chi_Minh. GitHub Actions owns the schedule and calls the Vercel-hosted digest endpoint. Each message sends 3-5 items when enough candidates are available.

## Message Format

Each item is formatted for quick scanning:

```text
1. AI English title
Source: Latent Space | ai-engineering / coding-agents
Summary: Short English summary.
Why: Role-specific reason for SWE/FDE/SA work.
VN: One short Vietnamese takeaway.
Read: Read
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
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CRON_SECRET`

On Vercel, `GEMINI_API_KEY_B64` and `TELEGRAM_BOT_TOKEN_B64` are also supported as encoded fallbacks when direct provider-shaped secret values are rejected by the env-var API. Direct vars take precedence.

Optional for durable automation storage:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

If Turso is not configured, the app uses local SQLite at `data/news-keep-up.db`.

Cost-control defaults:

- `MAX_LLM_ITEMS_PER_RUN=20`
- `MAX_LLM_CALLS_PER_DAY=40`
- `MAX_CANDIDATES_PER_SOURCE=10`
- `MIN_RELEVANCE_SCORE=65`
- `BACKFILL_LOOKBACK_DAYS=7`

## GitHub Actions

Configure repository secrets:

- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

The workflow is in `.github/workflows/digest.yml` and runs at `10 1,3,5,7,9,11,13 * * *` UTC, equivalent to 08:10 through 20:10 ICT every two hours. It calls the Vercel endpoint with `CRON_SECRET`; the Telegram/Gemini runtime configuration remains in Vercel.

## Vercel

The Vercel deployment exposes `news_keep_up.vercel_app:app`:

- `/api/digest/news` runs the production digest
- `?dry_run=true` formats the digest without sending Telegram

Configure the Vercel environment variables listed above for production. `CRON_SECRET` must be set so scheduled callers can authenticate requests with `Authorization: Bearer $CRON_SECRET`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Docs

- Design spec: `docs/superpowers/specs/2026-07-06-news-keep-up-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-06-news-keep-up.md`
