# news-keep-up

Automated twice-daily Telegram digest for keeping up with AI, software engineering, forward deployed engineering, solution architecture, coding agents, AI tools, and high-signal technical discussions.

The digest runs at 10:00 and 16:00 Asia/Ho_Chi_Minh via GitHub Actions. Each message sends 3-5 items when enough candidates are available.

## Message Format

Each item is formatted for quick scanning:

```text
1. AI English title
Title VN: Vietnamese title translation
Category: ai-engineering | Topic: coding-agents | Source: Latent Space
Summary: Short English summary.
Why it matters: Role-specific reason for SWE/FDE/SA work.
Takeaway VN: One short Vietnamese takeaway.
Link: https://example.com/article
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

The workflow is in `.github/workflows/digest.yml` and is kept as a manual fallback. Scheduled production delivery runs through Vercel Cron.

## Vercel

The Vercel deployment exposes `news_keep_up.vercel_app:app` and schedules:

- `/api/digest/morning` at `0 3 * * *` UTC
- `/api/digest/afternoon` at `0 9 * * *` UTC

Configure the Vercel environment variables listed above for production. `CRON_SECRET` must be set so Vercel Cron can authenticate requests with `Authorization: Bearer $CRON_SECRET`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Docs

- Design spec: `docs/superpowers/specs/2026-07-06-news-keep-up-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-06-news-keep-up.md`
