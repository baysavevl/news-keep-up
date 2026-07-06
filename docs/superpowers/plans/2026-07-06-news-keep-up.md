# News Keep Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that fetches curated AI/SWE/FDE/solution-architect sources twice daily, enriches shortlisted items with Gemini under strict budget limits, and sends a 3-5 item Telegram DM digest.

**Architecture:** The app is a small Python package with focused modules: models/config, DB persistence, source fetching, prefiltering, Gemini enrichment, digest selection/formatting, Telegram delivery, and CLI orchestration. Local development uses SQLite; automation can use Turso/libSQL through the same DB interface when `TURSO_DATABASE_URL` is set. GitHub Actions runs the CLI at 03:00 and 09:00 UTC for 10:00 and 16:00 ICT.

**Tech Stack:** Python 3.11+, standard library HTTP/XML/SQLite, optional `libsql_experimental` for Turso, `unittest` tests, GitHub Actions, Telegram Bot API, Gemini REST API.

## Global Constraints

- Delivery target is Telegram DM via `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- Schedule is 10:00 and 16:00 Asia/Ho_Chi_Minh, equivalent to 03:00 and 09:00 UTC.
- Each digest sends 3 to 5 items whenever enough current or recent unsent items exist.
- Discussion items are capped to 1 or 2 per digest in V1.
- Gemini default model is `gemini-2.5-flash-lite`; fallback model is `gemini-2.5-flash`.
- Cost controls default to `MAX_LLM_ITEMS_PER_RUN=20`, `MAX_LLM_CALLS_PER_DAY=40`, `MAX_CANDIDATES_PER_SOURCE=10`, `MIN_RELEVANCE_SCORE=65`, and `BACKFILL_LOOKBACK_DAYS=7`.
- Gemini enrichment must be cached by item and never repeated for the same canonical URL.
- If Gemini is unavailable or budget-limited, the system uses source-snippet fallback.
- Backfilled items must be marked `Backfill - still relevant`.
- Each item must show a Vietnamese title translation directly under the English title.

---

## File Structure

- `pyproject.toml`: package metadata and Python version.
- `.env.example`: required and optional environment variables.
- `.gitignore`: Python caches, local DB files, local env files.
- `config/sources.json`: curated source seed config.
- `.github/workflows/digest.yml`: scheduled and manual GitHub Actions workflow.
- `news_keep_up/models.py`: shared dataclasses for source, candidate, enrichment, and digest items.
- `news_keep_up/config.py`: env parsing, default limits, source loading.
- `news_keep_up/utils.py`: URL canonicalization, text cleanup, fingerprints, ICT time helpers.
- `news_keep_up/db.py`: SQLite/Turso connection, schema, upserts, cached enrichment, delivery tracking, LLM usage limits.
- `news_keep_up/sources.py`: RSS/Atom and Hacker News candidate fetchers.
- `news_keep_up/prefilter.py`: deterministic inclusion/exclusion scoring before Gemini.
- `news_keep_up/gemini.py`: Gemini prompt, JSON validation, fallback enrichment.
- `news_keep_up/digest.py`: candidate fetch/store/enrich/select pipeline and Telegram message formatting.
- `news_keep_up/telegram.py`: Telegram Bot API sender.
- `news_keep_up/main.py`: CLI entrypoint.
- `tests/`: unit tests for utilities, DB, prefiltering, Gemini parsing, digest selection, and formatter.

## Task 1: Scaffold Config, Models, Utilities, And Tests

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `config/sources.json`
- Create: `news_keep_up/__init__.py`
- Create: `news_keep_up/models.py`
- Create: `news_keep_up/config.py`
- Create: `news_keep_up/utils.py`
- Create: `tests/test_utils.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `load_settings(env: Mapping[str, str] | None = None) -> Settings`
- Produces: `load_sources(path: Path | str = DEFAULT_SOURCES_PATH) -> list[Source]`
- Produces: `canonicalize_url(url: str) -> str`
- Produces: `fingerprint_text(*parts: str) -> str`

- [ ] **Step 1: Write failing tests for config and utility behavior.**
- [ ] **Step 2: Run `python -m unittest tests.test_utils tests.test_config -v` and verify imports fail because the package does not exist yet.**
- [ ] **Step 3: Implement the package scaffold, source config, env parsing, URL canonicalization, and fingerprint helpers.**
- [ ] **Step 4: Rerun `python -m unittest tests.test_utils tests.test_config -v` and verify the tests pass.**

## Task 2: Add Database Persistence

**Files:**
- Create: `news_keep_up/db.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes: `Source`, `CandidateItem`, `Enrichment`
- Produces: `connect_database(settings: Settings)`
- Produces: `init_db(conn) -> None`
- Produces: `upsert_source(conn, source: Source) -> int`
- Produces: `upsert_item(conn, item: CandidateItem) -> tuple[int, bool]`
- Produces: `get_enrichment(conn, item_id: int) -> Enrichment | None`
- Produces: `upsert_enrichment(conn, item_id: int, enrichment: Enrichment) -> None`
- Produces: `mark_delivered(conn, item_ids: list[int], slot: str, backfill_ids: set[int]) -> None`
- Produces: `count_llm_calls_today(conn, call_date: str) -> int`

- [ ] **Step 1: Write failing DB tests using a temporary SQLite database.**
- [ ] **Step 2: Run `python -m unittest tests.test_db -v` and verify it fails because `news_keep_up.db` does not exist.**
- [ ] **Step 3: Implement schema creation, source/item/enrichment upserts, delivery tracking, and LLM usage counting.**
- [ ] **Step 4: Rerun `python -m unittest tests.test_db -v` and verify the DB tests pass.**

## Task 3: Add Source Fetching And Prefiltering

**Files:**
- Create: `news_keep_up/sources.py`
- Create: `news_keep_up/prefilter.py`
- Create: `tests/test_sources.py`
- Create: `tests/test_prefilter.py`

**Interfaces:**
- Consumes: `Source`, `CandidateItem`
- Produces: `parse_rss_or_atom(xml_text: str, source: Source) -> list[CandidateItem]`
- Produces: `fetch_source(source: Source, user_agent: str, timeout_seconds: int = 15) -> list[CandidateItem]`
- Produces: `prefilter_score(item: CandidateItem) -> int`
- Produces: `is_candidate_relevant(item: CandidateItem) -> bool`

- [ ] **Step 1: Write failing tests for RSS/Atom parsing and deterministic prefilter scoring.**
- [ ] **Step 2: Run `python -m unittest tests.test_sources tests.test_prefilter -v` and verify missing-module failures.**
- [ ] **Step 3: Implement RSS/Atom parsing, Hacker News API fetching, keyword scoring, and exclusion filtering.**
- [ ] **Step 4: Rerun `python -m unittest tests.test_sources tests.test_prefilter -v` and verify tests pass.**

## Task 4: Add Gemini Enrichment With Budget Fallbacks

**Files:**
- Create: `news_keep_up/gemini.py`
- Create: `tests/test_gemini.py`

**Interfaces:**
- Consumes: `Settings`, `CandidateItem`, `Enrichment`
- Produces: `build_prompt(item: CandidateItem) -> str`
- Produces: `parse_enrichment_response(text: str, item: CandidateItem, model: str) -> Enrichment`
- Produces: `fallback_enrichment(item: CandidateItem, reason: str = "fallback") -> Enrichment`
- Produces: `GeminiClient.enrich(item: CandidateItem) -> Enrichment`

- [ ] **Step 1: Write failing tests for Gemini JSON extraction, Vietnamese title translation validation, and fallback summaries.**
- [ ] **Step 2: Run `python -m unittest tests.test_gemini -v` and verify it fails because `news_keep_up.gemini` does not exist.**
- [ ] **Step 3: Implement prompt generation, strict JSON parsing, value clamping, and urllib-based Gemini REST calls.**
- [ ] **Step 4: Rerun `python -m unittest tests.test_gemini -v` and verify tests pass.**

## Task 5: Add Digest Selection, Formatting, Telegram, And CLI

**Files:**
- Create: `news_keep_up/digest.py`
- Create: `news_keep_up/telegram.py`
- Create: `news_keep_up/main.py`
- Create: `tests/test_digest.py`

**Interfaces:**
- Consumes: all earlier modules.
- Produces: `select_digest_items(rows: list[DigestCandidate], min_items: int, max_items: int, discussion_limit: int) -> list[DigestSelection]`
- Produces: `format_digest(slot: str, selections: list[DigestSelection], now: datetime | None = None) -> str`
- Produces: `run_digest(settings: Settings, slot: str, dry_run: bool = False) -> str`
- Produces: `send_telegram_message(text: str, settings: Settings) -> None`

- [ ] **Step 1: Write failing tests for 3-5 item selection, discussion cap, backfill marking, Vietnamese translated title placement, and message format.**
- [ ] **Step 2: Run `python -m unittest tests.test_digest -v` and verify it fails because digest functions do not exist.**
- [ ] **Step 3: Implement selection, formatting, Telegram sending, and CLI orchestration.**
- [ ] **Step 4: Rerun `python -m unittest tests.test_digest -v` and verify tests pass.**

## Task 6: Add Automation, Docs, And Full Verification

**Files:**
- Create: `.github/workflows/digest.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: CLI commands from Task 5.
- Produces: scheduled GitHub Actions workflow and user setup docs.

- [ ] **Step 1: Add workflow for `0 3,9 * * *` UTC and manual dispatch.**
- [ ] **Step 2: Update README with local dev, env vars, dry run, real run, and GitHub secrets.**
- [ ] **Step 3: Run `python -m unittest discover -s tests -v`.**
- [ ] **Step 4: Run `python -m news_keep_up.main init-db --db-path /tmp/news-keep-up-test.db`.**
- [ ] **Step 5: Run `python -m news_keep_up.main run-digest --slot morning --dry-run --db-path /tmp/news-keep-up-test.db`.**
- [ ] **Step 6: Commit all implementation files with `git commit -m "feat: implement automated news digest"`.**
