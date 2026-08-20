# Telegram Action and Feedback Sprint 1 Design

Date: 2026-08-21

## Goal

Turn the existing Telegram-first digest into a measurable action loop without
increasing automatic notification volume.

Sprint 1 adds:

- one-tap contextual feedback and actions for news, jobs, and interview drills;
- a per-user action queue exposed through `/queue`;
- a seven-day outcome report exposed through `/weekly`;
- a compact weekly report appended to an existing Monday news digest;
- engagement delivery records that provide a reliable denominator for later
  product and ranking measurements.

The implementation must preserve current delivery deduplication, source
selection, LLM use, profile authorization, and dry-run behavior.

## Current State and Problem

The app already has strong ingestion, deterministic and Gemini ranking,
delivery deduplication, source health, scheduling, and profile-specific
Telegram commands. It records what was delivered but not whether a recipient
found an item useful or acted on it. Ranking is therefore fixed and product
value cannot be measured from user outcomes.

Telegram messages are currently shaped as follows:

- news: two items per message;
- jobs: one detailed opportunity per message;
- interview: a standalone announcement followed by a separate two-drill
  message.

Sprint 1 must add interaction while keeping two news items per message and
reducing interview delivery from two messages to one.

## Approved Product Decisions

1. Keep news at two items per Telegram message.
2. Use one numbered button row per news item and interview drill.
3. Use contextual buttons for jobs.
4. A positive reaction does not automatically create queue work.
5. Only explicit save, apply, verify, or repeat actions open a queue item.
6. Completion or dismissal closes a queue item.
7. Callback actions produce a Telegram toast, never a new chat message.
8. `/queue` and `/weekly` are user-requested messages and may reply normally.
9. The automatic weekly report is appended only to existing `engineer` and
   `fde` digest messages. It is never sent separately.
10. Feedback is stored per Telegram user. Automatic weekly summaries aggregate
    by profile and chat.

## Architecture

Use a layered extension rather than placing new business logic inside the
already-large digest and command modules.

### `news_keep_up/interactions.py`

Owns domain rules:

- subject and action constants;
- allowed actions per subject type;
- queue state transitions;
- weekly metric calculation;
- compact report formatting;
- interaction result messages.

It does not make Telegram HTTP calls or contain SQL.

### `news_keep_up/interaction_store.py`

Owns SQL operations over a supplied SQLite/libSQL connection:

- plan, complete, and fail engagement deliveries;
- load an interaction target from its compact numeric ID;
- idempotently record callback events;
- upsert and close queue rows;
- resolve the latest queue state;
- list a user's open queue;
- aggregate seven-day metrics;
- reserve and mark weekly report delivery.

Schema creation remains in `db.init_db()` so the application continues to
have one idempotent migration entry point.

### `news_keep_up/telegram_interactions.py`

Owns the Telegram adapter:

- builds inline keyboards from planned engagement delivery IDs;
- encodes and decodes versioned callback data;
- routes callback queries into the interaction domain service;
- formats the `/queue` response and its completion/removal buttons.

It does not select content or calculate ranking.

### Existing modules

- `telegram.py` gains reply-markup support, returns Telegram response objects,
  and exposes `answerCallbackQuery`.
- `telegram_commands.py` routes callback queries before command parsing and
  adds `/queue`, `/saved`, `/todo`, and `/weekly`.
- `digest.py`, `job_alerts.py`, and `interview.py` supply subjects and button
  presets around their existing content.
- Existing text formatter APIs remain available for dry runs and regression
  tests.

## Subject Identity

Every interactive target has a type and stable source identity:

| Subject type | Source identity |
| --- | --- |
| `news` | decimal `items.id` |
| `job` | `job_opportunities.id` |
| `interview` | `FdeInterviewGuideline.slug` |

Job IDs may be up to 120 characters and Telegram callback data is limited to
64 bytes. Callback payloads therefore never include raw subject IDs. Before a
message is sent, the app creates numeric engagement-delivery rows and uses
those IDs in callback data.

## Storage

All timestamps are stored as ISO-8601 text. Reporting converts boundaries in
`Asia/Ho_Chi_Minh`.

### `engagement_deliveries`

One row per subject placed in an outbound interactive message:

- `id INTEGER PRIMARY KEY`
- `profile TEXT NOT NULL`
- `subject_type TEXT NOT NULL`
- `subject_id TEXT NOT NULL`
- `delivery_kind TEXT NOT NULL` (`content` or `queue`)
- `chat_id TEXT NOT NULL`
- `delivery_state TEXT NOT NULL` (`planned`, `delivered`, or `failed`)
- `telegram_message_id TEXT DEFAULT ''`
- `created_at TEXT NOT NULL`
- `delivered_at TEXT DEFAULT ''`

Indexes cover `(profile, chat_id, delivered_at)` and
`(subject_type, subject_id)`.

Planned rows exist before the Telegram call so their compact numeric IDs can
be embedded in buttons. They become `delivered` only after Telegram succeeds.
Failures become `failed` and are excluded from reports. A callback normally
requires a delivered row; if a post-send DB update failed, a callback whose
chat and Telegram message ID match may safely promote the planned row to
delivered. Reports count only `content` rows. A `/queue` response creates
separate `queue` rows so its buttons are bound to the new Telegram message
without inflating the content-delivery denominator.

The existing `deliveries` and `job_alert_deliveries` tables remain the source
of truth for resend prevention. This table is the source of truth for
engagement measurement and callback target resolution.

### `interaction_events`

Append-only callback history:

- `id INTEGER PRIMARY KEY`
- `engagement_delivery_id INTEGER NOT NULL`
- `action TEXT NOT NULL`
- `actor_user_id TEXT NOT NULL`
- `telegram_callback_query_id TEXT NOT NULL UNIQUE`
- `created_at TEXT NOT NULL`

An index covers `(actor_user_id, created_at)`. The unique callback query ID
makes Telegram retries idempotent. Repeating an already-current action returns
a successful no-op result rather than inflating metrics.

### `action_queue`

Current queue projection:

- `profile TEXT NOT NULL`
- `chat_id TEXT NOT NULL`
- `actor_user_id TEXT NOT NULL`
- `subject_type TEXT NOT NULL`
- `subject_id TEXT NOT NULL`
- `queue_action TEXT NOT NULL`
- `status TEXT NOT NULL` (`open`, `completed`, `dismissed`, or `unavailable`)
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `completed_at TEXT DEFAULT ''`
- primary key on `(profile, chat_id, actor_user_id, subject_type, subject_id)`

Queue actions upsert the current row. Completion and dismissal preserve the
row for reporting. A subject that can no longer be resolved is closed as
`unavailable` when the queue is read.

### `weekly_report_deliveries`

Prevents duplicate automatic reports:

- `profile TEXT NOT NULL`
- `chat_id TEXT NOT NULL`
- `report_week TEXT NOT NULL` (ISO Monday date)
- `delivery_state TEXT NOT NULL` (`planned` or `delivered`)
- `created_at TEXT NOT NULL`
- `delivered_at TEXT DEFAULT ''`
- primary key on `(profile, chat_id, report_week)`

The compact report is reserved with a `planned` row before Telegram delivery.
Only the caller that creates the reservation may attach the report. A send
failure removes the reservation so the next digest can retry. A planned row
older than 15 minutes may be reclaimed after a crashed run.

## Button Presets

### News

Two rows are attached to the existing two-item digest message:

```text
1 👍   1 👎   1 📌   1 ✅
2 👍   2 👎   2 📌   2 ✅
```

Actions are `useful`, `noise`, `save`, and `done`.

### Jobs

Each existing job alert gets one row:

```text
📌 Lưu   💼 Apply   🔎 Verify   🚫 Bỏ
```

Actions are `save`, `apply`, `verify`, and `dismiss`.

### Interview

The announcement and two drills are combined into one message. It receives two
numbered rows:

```text
1 ✅ Đã luyện   1 🔁 Nhắc lại   1 🚫
2 ✅ Đã luyện   2 🔁 Nhắc lại   2 🚫
```

Actions are `done`, `repeat`, and `dismiss`.

## Callback Protocol and Authorization

Callback data uses a compact, versioned form:

```text
i1|<engagement_delivery_id>|<action_code>
```

The decoder rejects malformed versions, non-decimal delivery IDs, unknown
action codes, payloads over Telegram's limit, and extra fields.

The callback flow is:

1. The existing webhook secret check succeeds.
2. Extract the callback message chat, message ID, callback ID, and actor ID.
3. Require the callback chat to equal the configured profile chat.
4. Decode the compact payload and load the engagement delivery.
5. Require matching profile, chat, message ID, subject type, and allowed action.
6. Require the underlying news item, job opportunity, or interview slug to
   exist.
7. In one DB transaction, insert the idempotent event and update queue state.
8. Answer the callback with a short toast such as `Đã lưu vào /queue`.

The bot does not edit the original keyboard because message edits are shared
across every group member while queue state is personal.

## Telegram Transport Behavior

`send_telegram_message()` accepts optional `reply_markup` and returns the list
of successful Telegram `result` objects. Existing callers may ignore the
return value.

Messages without markup retain existing safe splitting. A message with markup
must fit in one 4,096-character Telegram message. If it does not, the transport
raises before sending rather than split text away from its buttons.

For interactive messages, outbound flow is:

1. Create planned engagement rows.
2. Build the keyboard from their numeric IDs.
3. Send one Telegram message.
4. Mark every planned row delivered with the returned message ID.
5. Run the existing news/job delivery marker.

If Telegram fails, mark the planned rows failed and do not run existing
delivery markers.

## Action Queue

`/queue`, `/saved`, and `/todo` are aliases. The response is scoped to the
calling Telegram user, configured chat, and current profile.

It lists at most eight most recently updated open rows in one message. Subjects
are resolved from existing news/job storage or the static interview guideline
pool. Before the response is sent, each listed subject receives a new
`delivery_kind=queue` callback target. Each row gets `✅ Xong` and `🗑 Bỏ`
callback actions bound to that response message. An empty queue returns one
short line.

State rules:

- `useful` and `noise` update feedback only;
- `save`, `apply`, `verify`, and `repeat` open or update a queue row;
- `done` marks a queue row completed, or records direct completion when no row
  was open;
- `dismiss` closes the row as dismissed;
- only the latest mutually exclusive sentiment is used in reports.

## Weekly Outcome Report

`/weekly` returns one message for the previous seven complete local calendar
days, ending at midnight ICT. The response labels the date range.

Core metrics are:

- interactive subjects delivered;
- subjects with at least one response;
- latest useful and noise reactions;
- queue items opened;
- items completed;
- currently open queue items;
- response rate;
- useful precision when useful/noise data exists.

Jobs replace generic labels with apply/verify counts. Interview reports use
practiced/repeat counts. Sprint 1 does not invent monetary cost or time-saved
estimates.

For `engineer` and `fde`, a four-line compact version is appended to the first
successful digest of each ISO week on or after Monday. It is appended to the
first digest chunk and never sent separately. If it would push that message
over Telegram's limit, the report is omitted and remains eligible for the next
digest. The weekly-delivery marker is written only after Telegram succeeds.

Jobs and interview never auto-send reports; they support `/weekly` only.

## Error Handling

- Malformed, unauthorized, stale, or incompatible callbacks do not mutate DB
  state.
- Duplicate callback IDs return a successful no-op toast.
- DB failure returns a generic retryable callback error and leaves queue state
  unchanged.
- Telegram send failure leaves existing delivery dedupe state unchanged.
- Weekly report formatting failure does not block the underlying digest.
- Old messages without keyboards and all existing commands remain compatible.
- Dry runs emit text only and do not create engagement rows.
- No callback path invokes Gemini or fetches external content.

## Testing

Use test-driven development. Required tests cover:

1. idempotent creation of all four tables on SQLite;
2. SQLite/libSQL-compatible SQL and row access patterns;
3. callback codec bounds and malformed payload rejection;
4. reply markup in Telegram requests and returned message IDs;
5. refusal to split marked-up messages;
6. exact mapping of two news items to two keyboard rows;
7. contextual job and interview presets;
8. callback chat/profile/message/action validation;
9. duplicate callback idempotency;
10. queue transitions, user isolation, stale targets, and eight-item limit;
11. weekly date boundaries in ICT and metric calculations;
12. weekly report injection at most once per week without a new message;
13. send failure never marks engagement or existing delivery state complete;
14. interview delivery decreases from two messages to one;
15. existing dry-run output remains usable;
16. the complete existing unit-test suite passes.

## Success Criteria

- Automatic news and job message counts do not increase.
- Each interactive subject maps to the correct callback target.
- Interview learning delivery decreases from two messages to one.
- A repeated Telegram callback cannot duplicate metrics or queue rows.
- `/queue` and `/weekly` fit in one message under their configured limits.
- The first successful weekly news digest includes at most one compact report.
- No feedback influences ranking in Sprint 1; collected data is ready for the
  later adaptive-ranking sprint.
- All tests pass before commit and push.

## Non-Goals

- adaptive ranking or source-weight changes;
- web dashboard or multi-user administration;
- monetary ROI estimation;
- external notes, calendar, or task integrations;
- natural-language chat over saved content;
- bulk ingestion of external FDE learning repositories.

## Follow-Up: FDE Learning Source Adapter

After Sprint 1, create a separately designed source adapter rather than merely
adding URLs to `config/fde_interview_sources.json`. The current interview
runtime uses a static guideline pool and does not consume that config.

Approved source order:

1. `weissmanntobi-del/Forward_Deployed_Engineer_Material`: preferred practical
   drill seed; MIT-licensed free content; exclude premium marketing.
2. `global-fde/awesome-fde-resources`: curated discovery registry; CC-BY-4.0
   content and Apache-2.0 code; do not automatically trust every linked source.
3. `vivianaranha/fde-interview-mastery`: question-discovery/link source only
   until licensing is explicit; apply repetition and quality gates rather than
   importing its claimed 1,260 answers wholesale.

That adapter will need pinned or conditional GitHub fetches, license metadata,
Markdown parsing, question deduplication, a quality gate, and stable learning
card identities. It is intentionally outside this implementation plan.
