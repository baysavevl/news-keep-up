# News Keep Up Design

Date: 2026-07-06

## Goal

Build an automated twice-daily Telegram digest that helps a software engineer, forward deployed engineer, and solution architect keep up with high-signal news, articles, and discussions. The digest should emphasize AI, AI engineering, coding agents, AI tools, practical engineering workflow changes, and customer-facing technical strategy.

Each scheduled message must contain 3 to 5 items, with at least 3 whenever there are enough usable current or recent unsent items. The system should minimize Gemini cost by prefiltering without an LLM, caching all model outputs, and enforcing per-run and per-day limits.

## Recommended Approach

Use a Python CLI automation app with GitHub Actions scheduling, SQLite/Turso persistence, Gemini enrichment, and Telegram DM delivery.

This follows the strongest sibling-project pattern:

- `../aus-dream`: crawler-style CLI, SQLite/Turso DB abstraction, notification queue, GitHub Actions scheduling, Telegram batch formatting.
- `../solution-engineer`: Gemini API call style, fallback model, Telegram error reporting.
- `../huong-tu`: simple Telegram helper and cron style as future reference if a Vercel cron variant is needed.

## Non-Goals For V1

- No web dashboard.
- No user-facing subscription management.
- No vector database.
- No paid search API dependency.
- No browser automation for paywalled newsletters.
- No automatic posting to public channels.

## Runtime

The project runs as a Python CLI:

```bash
python -m news_keep_up.main init-db
python -m news_keep_up.main run-digest --slot morning
python -m news_keep_up.main run-digest --slot afternoon
```

GitHub Actions triggers the digest at:

- 10:00 Asia/Ho_Chi_Minh
- 16:00 Asia/Ho_Chi_Minh

The equivalent UTC schedules are:

- 03:00 UTC
- 09:00 UTC

Manual dispatch is supported for testing.

## Delivery

Delivery target is Telegram DM using:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Messages are sent with web previews disabled so each digest stays compact and predictable.

## Digest Format

Each digest has a short header:

```text
AI/FDE/SWE Digest | Morning | 06 Jul 2026 10:00 ICT
3 fresh, 1 backfill
```

Each item has:

```text
<icon> <title>
Category: <category> | Topic: <topic> | Source: <source>
Summary: <2-4 concise sentences>
Why it matters: <role-specific reason for SWE/FDE/SA work>
Takeaway VN: <one short Vietnamese takeaway>
Link: <url>
```

Backfilled items are explicitly marked:

```text
Backfill - still relevant
```

## Source Strategy

Sources are curated in config, grouped by type.

Initial article/newsletter sources:

- Latent.Space / AI News
- The Pragmatic Engineer
- Simon Willison's newsletter and blog
- One Useful Thing
- Interconnects AI
- Ahead of AI
- Lenny's Newsletter
- OpenAI Blog
- Anthropic News
- Google DeepMind Blog
- Google AI Blog
- GitHub Blog and changelog
- Vercel AI sources
- LangChain Blog

Initial discussion sources:

- Hacker News front page / newest / item feeds where available
- Selected Reddit RSS feeds for AI engineering, local LLMs, machine learning, software engineering, and programming
- GitHub trending or repository release/changelog feeds where feasible

Discussion items are capped to 1 or 2 per digest in V1.

## Pipeline

1. Load active sources from config.
2. Fetch candidates with source-specific adapters.
3. Normalize items into a shared shape.
4. Deduplicate by canonical URL and content fingerprint.
5. Run deterministic prefiltering:
   - include terms: AI, agent, LLM, coding agent, software engineering, system design, solution architect, forward deployed engineer, customer engineering, AI tools, Claude Code, Codex, Gemini CLI, Cursor, LangChain, RAG, evals, MCP, workflow automation.
   - exclude obvious low-value content: generic marketing landing pages, job ads, duplicate podcast mirrors, coupon/promotional posts.
6. Shortlist up to `MAX_LLM_ITEMS_PER_RUN` candidates.
7. Reuse cached Gemini enrichment where present.
8. Call Gemini only for uncached shortlisted candidates.
9. Select 3 to 5 digest items by relevance, recency, diversity, and source quality.
10. If fewer than 3 fresh items are selected, backfill from recent unsent enriched items from the last 3 to 7 days.
11. Format and send Telegram message.
12. Mark delivered items in the DB.

## LLM Use

Gemini performs enrichment, not raw crawling.

For each shortlisted candidate, Gemini returns structured JSON:

```json
{
  "relevance_score": 0,
  "category": "ai-engineering",
  "topic": "coding-agents",
  "icon": "AI",
  "summary": "Short English summary.",
  "why_it_matters": "Role-specific reason.",
  "takeaway_vi": "Short Vietnamese takeaway.",
  "should_send": true
}
```

The app validates the JSON and falls back to source snippets if the model fails.

Primary model:

- `gemini-2.5-flash-lite` by default for cost control.

Fallback model:

- `gemini-2.5-flash` only when configured or needed.

## Cost Controls

The project should use Gemini under the user's purchased limit and avoid unnecessary model calls.

Default controls:

- `MAX_LLM_ITEMS_PER_RUN=20`
- `MAX_LLM_CALLS_PER_DAY=40`
- `MAX_CANDIDATES_PER_SOURCE=10`
- `MIN_RELEVANCE_SCORE=65`
- `BACKFILL_LOOKBACK_DAYS=7`

Rules:

- Never re-summarize the same canonical URL.
- Store every enrichment result permanently.
- Prefer deterministic prefiltering before LLM scoring.
- Stop model calls when per-run or per-day limits are reached.
- Send a digest with cached/source-snippet summaries when Gemini is unavailable or the limit is reached.

## Persistence

Use a DB abstraction matching `aus-dream`:

- Local SQLite for development.
- Turso/libSQL when `TURSO_DATABASE_URL` is set.

Tables:

### sources

- `id`
- `name`
- `type`
- `url`
- `category`
- `enabled`
- `created_at`

### items

- `id`
- `source_id`
- `source_name`
- `title`
- `url`
- `canonical_url`
- `summary`
- `content`
- `author`
- `published_at`
- `fetched_at`
- `fingerprint`
- `raw_json`

Unique index:

- `canonical_url`

### enrichments

- `id`
- `item_id`
- `model`
- `relevance_score`
- `category`
- `topic`
- `icon`
- `summary`
- `why_it_matters`
- `takeaway_vi`
- `should_send`
- `created_at`

Unique index:

- `item_id`

### deliveries

- `id`
- `item_id`
- `slot`
- `delivered_at`
- `is_backfill`

### llm_usage

- `id`
- `model`
- `call_date`
- `slot`
- `item_id`
- `status`
- `created_at`

## Source Adapters

V1 adapters:

- RSS/Atom adapter for newsletters, blogs, Reddit feeds, and changelog feeds.
- Hacker News adapter using a public API or feed.
- Static seed loader for the initial source config.

Adapters should return normalized candidates and fail independently. One broken source must not fail the entire digest.

## Error Handling

- Failed source fetch: log and continue.
- Malformed RSS/Atom: skip that source for the run.
- Gemini failure: log, send Telegram silent error to the owner if configured, and use snippet fallback.
- Telegram failure: return non-zero from CLI so GitHub Actions marks the run failed.
- DB unavailable: fail the run before making LLM calls.

## Testing

Focused tests should cover:

- URL canonicalization and dedupe.
- RSS/Atom parsing from fixtures.
- Deterministic prefilter scoring.
- Gemini JSON validation and fallback.
- Digest selection with fresh and backfill items.
- Telegram formatter output.
- DB writer upsert behavior.

## Configuration

Required env vars for production:

- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional env vars:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `GEMINI_MODEL`
- `GEMINI_FALLBACK_MODEL`
- `MAX_LLM_ITEMS_PER_RUN`
- `MAX_LLM_CALLS_PER_DAY`
- `MAX_CANDIDATES_PER_SOURCE`
- `MIN_RELEVANCE_SCORE`
- `BACKFILL_LOOKBACK_DAYS`

## Success Criteria

- `python -m news_keep_up.main init-db` creates the DB schema locally.
- `python -m news_keep_up.main run-digest --dry-run` prints a valid digest without sending Telegram.
- A real run sends one Telegram DM containing 3 to 5 items when enough candidates exist.
- Backfilled items are clearly marked when fewer than 3 fresh items qualify.
- Already-delivered URLs are not resent.
- Cached enrichments are reused without new Gemini calls.
- GitHub Actions can run the morning and afternoon slots automatically.

## Future Extensions

- Add a compact web dashboard.
- Add source quality metrics.
- Add per-topic weights configurable by the user.
- Add weekly recap.
- Add interactive Telegram commands for source toggling and manual refresh.
