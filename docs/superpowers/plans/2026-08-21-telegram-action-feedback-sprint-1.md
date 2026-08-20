# Telegram Action and Feedback Sprint 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add low-noise Telegram feedback, a personal action queue, and weekly outcome reporting for news, jobs, and FDE interview drills.

**Architecture:** Add a focused interaction domain and SQL store beside the existing delivery pipeline. Register outbound subjects before Telegram delivery so compact callback IDs can be attached safely; validate the registered message before applying an idempotent event and queue transition.

**Tech Stack:** Python 3.11+, Flask, urllib Telegram Bot API calls, SQLite/libSQL, dataclasses, unittest, unittest.mock.

**Spec:** docs/superpowers/specs/2026-08-21-telegram-action-feedback-sprint-1-design.md

## Global Constraints

- Keep two news items per Telegram message.
- Automatic news and job message counts must not increase.
- Combine the FDE interview announcement and two drills into one message.
- Callback actions answer with a toast and never send a chat message.
- Callback data stays below Telegram's 64-byte limit.
- Marked-up messages fit within Telegram's 4,096-character text limit.
- Feedback is isolated by Telegram actor for queue reads.
- Automatic weekly reports appear only on engineer and fde news digests.
- Automatic weekly reports append to existing content and never create a separate message.
- Dry runs do not create engagement state.
- Existing deliveries and job_alert_deliveries remain the resend-prevention source of truth.
- Feedback does not change ranking in Sprint 1.
- Add no dependency.
- Do not ingest the three external FDE learning repositories in this plan.

## File Structure

- Create news_keep_up/interactions.py for domain types, action rules, report periods, and report formatting.
- Create news_keep_up/interaction_store.py for SQL persistence, queue projection, metrics, and report reservations.
- Create news_keep_up/telegram_interactions.py for callback encoding, keyboards, interactive sends, callback handling, and queue rendering.
- Create tests/test_interactions.py, tests/test_interaction_store.py, and tests/test_telegram_interactions.py.
- Modify news_keep_up/db.py, telegram.py, telegram_commands.py, digest.py, job_alerts.py, and interview.py.
- Modify their existing test modules plus tests/test_vercel_deploy.py.
- Modify README.md with the new interaction behavior.

---

### Task 1: Interaction Domain Contracts

**Files:**
- Create: news_keep_up/interactions.py
- Create: tests/test_interactions.py

**Interfaces:**
- Produces: InteractionSubject, EngagementDelivery, QueueEntry, ResolvedQueueEntry, InteractionResult, WeeklyMetrics, ReportPeriod.
- Produces: allowed_actions(subject_type), queue_transition(action), report_period(current), format_weekly_report(metrics, profile, compact, period).
- Consumes: ICT and now_ict from news_keep_up.utils.

- [ ] **Step 1: Write failing domain tests**

Create tests/test_interactions.py:

    import unittest
    from datetime import datetime

    from news_keep_up.interactions import (
        InteractionSubject,
        WeeklyMetrics,
        allowed_actions,
        format_weekly_report,
        queue_transition,
        report_period,
    )
    from news_keep_up.utils import ICT


    class InteractionDomainTest(unittest.TestCase):
        def test_subject_normalizes_identifier_to_text(self):
            self.assertEqual(InteractionSubject("news", 42).subject_id, "42")

        def test_allowed_actions_are_contextual(self):
            self.assertEqual(allowed_actions("news"), {"useful", "noise", "save", "done"})
            self.assertEqual(allowed_actions("job"), {"save", "apply", "verify", "dismiss"})
            self.assertEqual(allowed_actions("interview"), {"done", "repeat", "dismiss"})

        def test_queue_transition_distinguishes_feedback_open_and_close(self):
            self.assertIsNone(queue_transition("useful"))
            self.assertEqual(queue_transition("apply"), ("apply", "open"))
            self.assertEqual(queue_transition("done"), ("done", "completed"))
            self.assertEqual(queue_transition("dismiss"), ("dismiss", "dismissed"))

        def test_report_period_uses_seven_complete_ict_days(self):
            period = report_period(datetime(2026, 8, 24, 9, 15, tzinfo=ICT))
            self.assertEqual(period.start.isoformat(), "2026-08-17T00:00:00+07:00")
            self.assertEqual(period.end.isoformat(), "2026-08-24T00:00:00+07:00")
            self.assertEqual(period.report_week, "2026-08-24")

        def test_compact_weekly_report_has_four_lines_and_no_fake_cost(self):
            metrics = WeeklyMetrics(
                delivered=24, responded=17, useful=14, noise=3,
                queued=6, completed=4, open_items=2,
                apply=0, verify=0, repeat=0,
            )
            report = format_weekly_report(metrics, "engineer", compact=True)
            self.assertLessEqual(len(report.splitlines()), 4)
            self.assertIn("24 delivered", report)
            self.assertIn("14 useful", report)
            self.assertNotIn("$", report)


    if __name__ == "__main__":
        unittest.main()

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

    python3 -m unittest tests.test_interactions -v

Expected: FAIL because news_keep_up.interactions does not exist.

- [ ] **Step 3: Implement immutable domain types and rules**

Create news_keep_up/interactions.py with:

    from __future__ import annotations

    from dataclasses import dataclass
    from datetime import datetime, timedelta

    from .utils import ICT, now_ict

    ACTIONS_BY_SUBJECT = {
        "news": {"useful", "noise", "save", "done"},
        "job": {"save", "apply", "verify", "dismiss"},
        "interview": {"done", "repeat", "dismiss"},
    }
    OPEN_QUEUE_ACTIONS = {"save", "apply", "verify", "repeat"}
    CLOSE_QUEUE_ACTIONS = {"done": "completed", "dismiss": "dismissed"}


    @dataclass(frozen=True)
    class InteractionSubject:
        subject_type: str
        subject_id: str

        def __init__(self, subject_type: str, subject_id: object):
            object.__setattr__(self, "subject_type", str(subject_type))
            object.__setattr__(self, "subject_id", str(subject_id))


    @dataclass(frozen=True)
    class EngagementDelivery:
        id: int
        profile: str
        subject_type: str
        subject_id: str
        delivery_kind: str
        chat_id: str
        delivery_state: str
        telegram_message_id: str
        created_at: str
        delivered_at: str


    @dataclass(frozen=True)
    class QueueEntry:
        profile: str
        chat_id: str
        actor_user_id: str
        subject_type: str
        subject_id: str
        queue_action: str
        status: str
        created_at: str
        updated_at: str
        completed_at: str


    @dataclass(frozen=True)
    class ResolvedQueueEntry:
        queue: QueueEntry
        title: str
        url: str


    @dataclass(frozen=True)
    class InteractionResult:
        duplicate: bool
        changed: bool
        toast: str


    @dataclass(frozen=True)
    class WeeklyMetrics:
        delivered: int
        responded: int
        useful: int
        noise: int
        queued: int
        completed: int
        open_items: int
        apply: int
        verify: int
        repeat: int


    @dataclass(frozen=True)
    class ReportPeriod:
        start: datetime
        end: datetime
        report_week: str


    def allowed_actions(subject_type: str) -> set[str]:
        return set(ACTIONS_BY_SUBJECT.get(subject_type, set()))


    def queue_transition(action: str) -> tuple[str, str] | None:
        if action in OPEN_QUEUE_ACTIONS:
            return action, "open"
        if action in CLOSE_QUEUE_ACTIONS:
            return action, CLOSE_QUEUE_ACTIONS[action]
        return None


    def report_period(current: datetime | None = None) -> ReportPeriod:
        value = current or now_ict()
        local = value.replace(tzinfo=ICT) if value.tzinfo is None else value.astimezone(ICT)
        end = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=7)
        monday = end - timedelta(days=end.weekday())
        return ReportPeriod(start, end, monday.date().isoformat())

Implement format_weekly_report as four lines. Calculate response rate only when
delivered is non-zero and useful precision only when useful plus noise is
non-zero. Use profile-specific labels for jobs and interview.

- [ ] **Step 4: Run domain tests**

    python3 -m unittest tests.test_interactions -v

Expected: all tests PASS.

- [ ] **Step 5: Commit the domain slice**

    git add news_keep_up/interactions.py tests/test_interactions.py
    git commit -m "feat(telegram): add interaction domain"

---

### Task 2: Engagement and Queue Persistence

**Files:**
- Create: news_keep_up/interaction_store.py
- Create: tests/test_interaction_store.py
- Modify: news_keep_up/db.py:45-220
- Modify: tests/test_db.py

**Interfaces:**
- Consumes: domain dataclasses and queue_transition from Task 1.
- Produces: plan_engagement_deliveries, mark_engagement_delivered, mark_engagement_failed, load_engagement_delivery, record_interaction, list_open_queue, mark_queue_unavailable, load_stored_subject, weekly_metrics, reserve_weekly_report, complete_weekly_report, release_weekly_report.

- [ ] **Step 1: Add failing schema and store tests**

Create an in-memory SQLite test helper:

    def connection():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        return conn

Add tests that prove:

1. init_db can run twice and creates engagement_deliveries, interaction_events,
   action_queue, and weekly_report_deliveries.
2. Two planned subjects receive different positive numeric IDs.
3. mark_engagement_delivered applies one Telegram message ID to both rows.
4. A repeated callback_query_id returns duplicate=True and creates one event.
5. An apply action opens one queue row for the actor.
6. Queue rows belonging to another actor are excluded.
7. weekly_metrics counts delivered content and excludes queue delivery rows.
8. A weekly reservation is unique, releasable after send failure, and becomes
   permanently delivered after completion.
9. A planned weekly reservation older than 15 minutes can be reclaimed.

Use fixed ISO timestamps such as 2026-08-21T10:00:00+07:00.

- [ ] **Step 2: Run persistence tests and confirm failures**

    python3 -m unittest tests.test_interaction_store -v

Expected: FAIL because the store module and schema tables do not exist.

- [ ] **Step 3: Add the four tables and indexes to init_db**

Append idempotent CREATE TABLE and CREATE INDEX statements inside db.init_db().
Use the exact columns, states, and primary keys from the design spec. Preserve
the single final conn.commit() and add a tests/test_db.py regression that calls
init_db twice.

- [ ] **Step 4: Implement delivery lifecycle**

Implement:

    def plan_engagement_deliveries(
        conn,
        profile: str,
        chat_id: str,
        subjects: list[InteractionSubject],
        delivery_kind: str,
        created_at: str,
    ) -> list[EngagementDelivery]

    def mark_engagement_delivered(
        conn,
        delivery_ids: list[int],
        telegram_message_id: str,
        delivered_at: str,
    ) -> None

    def mark_engagement_failed(conn, delivery_ids: list[int]) -> None

    def load_engagement_delivery(conn, delivery_id: int) -> EngagementDelivery | None

Use INSERT ... RETURNING id so SQLite and libSQL obtain IDs without a
connection-global MAX query. Commit multi-row lifecycle changes together and
roll back on exceptions.

- [ ] **Step 5: Implement event and queue updates atomically**

Implement:

    def record_interaction(
        conn,
        delivery_id: int,
        action: str,
        actor_user_id: str,
        callback_query_id: str,
        occurred_at: str,
    ) -> InteractionResult

Behavior:

- return duplicate=True for an existing callback ID;
- reject a missing delivery or disallowed action;
- return a changed=False no-op when the actor's latest same-dimension action
  is already current;
- save, apply, verify, and repeat upsert status=open;
- done upserts status=completed;
- dismiss upserts status=dismissed;
- useful and noise never create queue rows;
- insert the event and projection update in one transaction.

Implement list_open_queue with ORDER BY updated_at DESC and a limit clamped to
1 through 8.

- [ ] **Step 6: Implement lookup, metrics, and weekly reservation**

load_stored_subject resolves news title/url and job role/company/link with
parameterized queries. weekly_metrics uses only delivery_kind=content and
delivery_state=delivered in a half-open date range. It uses the latest
useful/noise event per actor and subject and counts current open queue rows
separately.

Reservation behavior:

- INSERT planned and return True for the winner;
- return False for delivered or fresh planned rows;
- replace planned rows older than 15 minutes;
- release deletes only planned rows;
- complete updates planned to delivered.

- [ ] **Step 7: Run persistence and DB tests**

    python3 -m unittest tests.test_interaction_store tests.test_db -v

Expected: all tests PASS.

- [ ] **Step 8: Commit persistence**

    git add news_keep_up/db.py news_keep_up/interaction_store.py tests/test_db.py tests/test_interaction_store.py
    git commit -m "feat(telegram): persist engagement actions"

---

### Task 3: Telegram Transport and Interactive Adapter

**Files:**
- Create: news_keep_up/telegram_interactions.py
- Create: tests/test_telegram_interactions.py
- Modify: news_keep_up/telegram.py
- Modify: tests/test_telegram.py

**Interfaces:**
- Consumes: delivery lifecycle functions from Task 2.
- Produces: ButtonSpec, InteractiveSubject, encode_callback, decode_callback, build_inline_keyboard, send_interactive_message.
- Produces transport function answer_telegram_callback.

- [ ] **Step 1: Add failing Telegram transport tests**

Extend tests/test_telegram.py to assert:

- reply_markup is serialized into sendMessage JSON;
- send_telegram_message returns payload result dictionaries;
- a marked-up text longer than 4,096 characters raises before urlopen;
- an unmarked long message retains current splitting;
- answer_telegram_callback calls answerCallbackQuery and truncates toast text to
  200 characters.

Use a Telegram response payload:

    {"ok": True, "result": {"message_id": 99}}

- [ ] **Step 2: Add failing codec and adapter tests**

Create tests/test_telegram_interactions.py. Cover:

- encode_callback(123, "useful") round-trips through decode_callback;
- malformed version, ID, action, or extra field raises ValueError;
- every encoded payload is at most 64 bytes;
- two news subjects produce two numbered keyboard rows;
- action validation rejects a job target with useful;
- send failure calls mark_engagement_failed and re-raises;
- send success marks every planned row with the returned message ID.

Define a stable local conn object in mocks rather than constructing object()
twice in an assertion.

- [ ] **Step 3: Run Telegram tests and confirm failures**

    python3 -m unittest tests.test_telegram tests.test_telegram_interactions -v

Expected: FAIL because markup, return values, callback answers, and the adapter
do not exist.

- [ ] **Step 4: Extend telegram.py**

Change the signature to:

    def send_telegram_message(
        text: str,
        settings: Settings,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict | None = None,
    ) -> list[dict]

Compute chunks before sending. If reply_markup is not None and there is more
than one chunk, raise ValueError. Include markup in the body, collect each
successful payload["result"], and return the list.

Add:

    def answer_telegram_callback(
        callback_query_id: str,
        text: str,
        settings: Settings,
        show_alert: bool = False,
    ) -> None

- [ ] **Step 5: Implement compact callbacks and keyboard types**

Use these exact action codes:

    ACTION_TO_CODE = {
        "useful": "u", "noise": "n", "save": "s", "done": "d",
        "apply": "a", "verify": "v", "dismiss": "x", "repeat": "r",
    }

Define:

    @dataclass(frozen=True)
    class ButtonSpec:
        text: str
        action: str


    @dataclass(frozen=True)
    class InteractiveSubject:
        subject: InteractionSubject
        buttons: tuple[ButtonSpec, ...]

Callback format is i1|delivery_id|action_code. build_inline_keyboard requires
equal non-empty delivery and subject lists and prefixes labels with one-based
numbers when numbered=True.

- [ ] **Step 6: Implement interactive send orchestration**

Implement:

    def send_interactive_message(
        conn,
        settings: Settings,
        profile: str,
        text: str,
        subjects: list[InteractiveSubject],
        *,
        delivery_kind: str = "content",
        numbered: bool = False,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
        current: datetime | None = None,
    ) -> list[EngagementDelivery]

Plan targets, build markup, send once, require one result containing message_id,
mark all plans delivered, and return refreshed rows. On an exception, mark all
plans failed and re-raise.

- [ ] **Step 7: Run Telegram tests**

    python3 -m unittest tests.test_telegram tests.test_telegram_interactions -v

Expected: all tests PASS.

- [ ] **Step 8: Commit transport and adapter**

    git add news_keep_up/telegram.py news_keep_up/telegram_interactions.py tests/test_telegram.py tests/test_telegram_interactions.py
    git commit -m "feat(telegram): add inline action transport"

---

### Task 4: Callback Handling

**Files:**
- Modify: news_keep_up/telegram_interactions.py
- Modify: news_keep_up/telegram_commands.py:27-157
- Modify: tests/test_telegram_interactions.py
- Modify: tests/test_telegram_commands.py
- Modify: tests/test_vercel_deploy.py

**Interfaces:**
- Consumes: compact callback, delivery lookup, record_interaction, and Telegram callback answers.
- Produces: handle_interaction_callback(callback_query, profile, settings, current).
- Preserves: handle_telegram_update(update, slot, sources_path, settings).

- [ ] **Step 1: Add failing callback tests**

Add tests with this callback shape:

    {
        "id": "cb-1",
        "from": {"id": 42},
        "data": encode_callback(delivery.id, "save"),
        "message": {"message_id": 700, "chat": {"id": -1001}},
    }

Prove:

- a valid callback records one event and answers one toast;
- a duplicate callback returns success without a second event;
- a wrong configured chat is ignored without mutation;
- a mismatched Telegram message ID is rejected;
- an action incompatible with the target subject is rejected;
- a missing news, job, or interview subject is rejected;
- a planned row with matching callback chat and message may be promoted;
- callback handling never calls send_telegram_message or Gemini.

- [ ] **Step 2: Add failing command and webhook routing tests**

Call handle_telegram_update with a callback_query-only update and patch
handle_interaction_callback. Assert the callback handler receives profile=slot
and the command response sender is not called.

Post the same shape through an existing secret-protected webhook in
tests/test_vercel_deploy.py and prove its current authentication still applies.

- [ ] **Step 3: Run callback tests and confirm failures**

    python3 -m unittest tests.test_telegram_interactions tests.test_telegram_commands tests.test_vercel_deploy -v

Expected: new tests FAIL because callback updates are currently ignored.

- [ ] **Step 4: Implement subject validation and callback handling**

Implement:

    def handle_interaction_callback(
        callback_query: dict,
        *,
        profile: str,
        settings: Settings,
        current: datetime | None = None,
    ) -> dict

Open the configured DB, initialize schema, decode the registered delivery,
validate profile/chat/message/action, resolve the underlying subject, call
record_interaction, close the DB, and answer a short toast. Return a JSON-safe
dictionary with ok, callback, action, duplicate, and changed fields.

Validate news and jobs with parameterized SELECT queries. Validate interview
against the FDE_INTERVIEW_GUIDELINES slug set through a local import to avoid an
import cycle.

- [ ] **Step 5: Route callbacks before parsing commands**

At the top of handle_telegram_update:

    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        return handle_interaction_callback(
            callback_query,
            profile=slot,
            settings=settings,
        )

Leave the webhook secret validation in vercel_app.py unchanged.

- [ ] **Step 6: Run callback and webhook tests**

    python3 -m unittest tests.test_telegram_interactions tests.test_telegram_commands tests.test_vercel_deploy -v

Expected: all tests PASS.

- [ ] **Step 7: Commit callback handling**

    git add news_keep_up/telegram_interactions.py news_keep_up/telegram_commands.py tests/test_telegram_interactions.py tests/test_telegram_commands.py tests/test_vercel_deploy.py
    git commit -m "feat(telegram): handle action callbacks"

---

### Task 5: Action Queue and Weekly Commands

**Files:**
- Modify: news_keep_up/telegram_interactions.py
- Modify: news_keep_up/telegram_commands.py
- Modify: tests/test_telegram_interactions.py
- Modify: tests/test_telegram_commands.py

**Interfaces:**
- Produces: send_queue_response and weekly_report_text.
- Consumes: list_open_queue, load_stored_subject, mark_queue_unavailable, weekly_metrics, report_period, and format_weekly_report.

- [ ] **Step 1: Add failing queue command tests**

Add queue, saved, and todo command cases. Prove:

- actor identity uses message.from.id and falls back to chat_id only when from
  is absent;
- only the actor's open rows in the current profile appear;
- at most eight rows appear;
- output is one message with numbered done and remove buttons;
- queue response targets use delivery_kind=queue;
- unresolvable subjects are marked unavailable and omitted;
- an empty queue replies with Queue trống.

- [ ] **Step 2: Add failing weekly command tests**

Add weekly and report aliases. Seed content deliveries and interactions, call
/weekly, and prove:

- the seven-day date range is displayed;
- queue delivery rows are excluded;
- engineer uses useful/noise labels;
- fde-jobs uses apply/verify labels;
- fde-interview uses practiced/repeat labels;
- exactly one plain response is sent.

- [ ] **Step 3: Run command tests and confirm failures**

    python3 -m unittest tests.test_telegram_commands tests.test_telegram_interactions -v

Expected: new queue and weekly tests FAIL.

- [ ] **Step 4: Implement queue resolution and marked-up response**

Resolve:

- news to items.title and items.url;
- job to role_title plus company and apply_url or source_url;
- interview to category plus title and source_url.

Format each result within 350 characters and the complete response within
4,096 characters. Use:

    QUEUE_BUTTONS = (
        ButtonSpec("✅ Xong", "done"),
        ButtonSpec("🗑 Bỏ", "dismiss"),
    )

Before sending, create fresh delivery_kind=queue targets for the returned
subjects. Call send_interactive_message with numbered=True and reply to the
command message.

- [ ] **Step 5: Implement weekly report text**

Use report_period(current), weekly_metrics, and format_weekly_report with the
calling actor_user_id. A user-requested report does not reserve or mark the
automatic weekly delivery table.

- [ ] **Step 6: Integrate command aliases and help**

Add queue/saved/todo and weekly/report to COMMAND_ALIASES and profile help.
Queue sends its own marked-up response and returns early. Weekly uses the
existing plain response sender.

- [ ] **Step 7: Run queue and weekly command tests**

    python3 -m unittest tests.test_telegram_commands tests.test_telegram_interactions -v

Expected: all tests PASS.

- [ ] **Step 8: Commit user commands**

    git add news_keep_up/telegram_interactions.py news_keep_up/telegram_commands.py tests/test_telegram_interactions.py tests/test_telegram_commands.py
    git commit -m "feat(telegram): add action queue and weekly report"

---

### Task 6: Interactive News and Automatic Weekly Recap

**Files:**
- Modify: news_keep_up/digest.py:257-350, 774-815
- Modify: tests/test_digest.py

**Interfaces:**
- Consumes: send_interactive_message and news button specifications.
- Consumes: reserve_weekly_report, complete_weekly_report, release_weekly_report, weekly_metrics.
- Preserves: format_digest_messages returns list[str].

- [ ] **Step 1: Add failing news keyboard tests**

With four selections, prove:

- format_digest_messages still returns two text messages;
- production sends exactly two Telegram messages;
- each message contains two numbered keyboard rows;
- the first keyboard maps to the first two item IDs;
- two engagement rows share the returned Telegram message ID;
- existing mark_delivered runs only after interactive send succeeds.

- [ ] **Step 2: Add failing weekly recap tests**

Seed the prior seven days and run an engineer digest on Monday. Prove:

- the compact report appears on the first chunk only;
- send count remains unchanged;
- a second digest in the same ISO week has no recap;
- a failed first send releases the reservation;
- an over-limit combined first chunk omits the report and releases reservation;
- dry-run does not reserve or create engagement rows.

- [ ] **Step 3: Run digest tests and confirm failures**

    python3 -m unittest tests.test_digest -v

Expected: new tests FAIL because production still sends plain messages.

- [ ] **Step 4: Define news button specifications**

    NEWS_BUTTONS = (
        ButtonSpec("👍", "useful"),
        ButtonSpec("👎", "noise"),
        ButtonSpec("📌", "save"),
        ButtonSpec("✅", "done"),
    )

Map each DigestSelection in a chunk to InteractionSubject("news", item_id).

- [ ] **Step 5: Prepare the automatic recap**

For profile engineer or fde, non-dry-run, and non-empty selections:

1. calculate ReportPeriod;
2. reserve the current report_week;
3. calculate chat metrics with actor_user_id=None;
4. format compact text;
5. append it only if the first chunk remains at most 4,096 characters;
6. release immediately if it cannot be appended.

- [ ] **Step 6: Send interactive chunks**

Call send_interactive_message for each chunk with delivery_kind=content and
numbered=True. After success run the existing mark_delivered. Complete the
weekly reservation after the first message succeeds. Release it if the first
send raises, then re-raise.

- [ ] **Step 7: Run digest tests**

    python3 -m unittest tests.test_digest -v

Expected: all tests PASS.

- [ ] **Step 8: Commit news integration**

    git add news_keep_up/digest.py tests/test_digest.py
    git commit -m "feat(digest): add feedback and weekly outcomes"

---

### Task 7: Interactive Job Alerts

**Files:**
- Modify: news_keep_up/job_alerts.py:40-82
- Modify: tests/test_job_alerts.py

**Interfaces:**
- Consumes: send_interactive_message, ButtonSpec, InteractiveSubject, InteractionSubject.
- Preserves: selection, three-alert cap, send window, and fingerprint delivery markers.

- [ ] **Step 1: Add failing job interaction tests**

Extend the current send-once coverage. Prove:

- the Telegram call gets one row with Lưu, Apply, Verify, and Bỏ;
- callbacks resolve the exact opportunity even when its raw ID has 120 chars;
- one content engagement row receives the returned message ID;
- mark_job_alert_delivered runs only after successful interactive delivery;
- Telegram failure marks engagement failed and leaves the job pending;
- dry-run creates no engagement rows.

- [ ] **Step 2: Run job tests and confirm failures**

    python3 -m unittest tests.test_job_alerts -v

Expected: new tests FAIL because alerts have no inline markup.

- [ ] **Step 3: Define job buttons and replace the send**

    JOB_BUTTONS = (
        ButtonSpec("📌 Lưu", "save"),
        ButtonSpec("💼 Apply", "apply"),
        ButtonSpec("🔎 Verify", "verify"),
        ButtonSpec("🚫 Bỏ", "dismiss"),
    )

For each alert call send_interactive_message with one job subject and
numbered=False. Keep mark_job_alert_delivered immediately after successful
interactive delivery.

- [ ] **Step 4: Run job alert tests**

    python3 -m unittest tests.test_job_alerts -v

Expected: all tests PASS.

- [ ] **Step 5: Commit jobs integration**

    git add news_keep_up/job_alerts.py tests/test_job_alerts.py
    git commit -m "feat(jobs): add alert action buttons"

---

### Task 8: One-Message Interactive FDE Interview

**Files:**
- Modify: news_keep_up/interview.py:291-320
- Modify: tests/test_interview.py

**Interfaces:**
- Consumes: send_interactive_message and interview button specifications.
- Preserves: selection and text formatter output.

- [ ] **Step 1: Add failing one-message tests**

Change production expectations to prove:

- exactly one Telegram message is sent;
- that message contains the announcement and both drills;
- two numbered keyboard rows appear;
- each row maps to its guideline slug;
- buttons are Đã luyện, Nhắc lại, and dismiss;
- two content engagement rows share the returned message ID;
- dry-run returns combined text and writes no engagement data.

- [ ] **Step 2: Run interview tests and confirm count failure**

    python3 -m unittest tests.test_interview -v

Expected: FAIL because production currently sends two messages.

- [ ] **Step 3: Replace two sends with one interactive send**

For production, open and initialize the configured DB. Use:

    INTERVIEW_BUTTONS = (
        ButtonSpec("✅ Đã luyện", "done"),
        ButtonSpec("🔁 Nhắc lại", "repeat"),
        ButtonSpec("🚫", "dismiss"),
    )

Combine announcement, a blank line, and guideline. Map both slugs, call
send_interactive_message with profile=fde-interview and numbered=True, and
close the DB in finally.

- [ ] **Step 4: Run interview tests**

    python3 -m unittest tests.test_interview -v

Expected: all tests PASS and send count equals one.

- [ ] **Step 5: Commit interview integration**

    git add news_keep_up/interview.py tests/test_interview.py
    git commit -m "feat(interview): add drill action buttons"

---

### Task 9: Documentation and Full Verification

**Files:**
- Modify: README.md
- Modify: integration tests only when final public shapes require it.

**Interfaces:**
- Consumes: every completed slice.
- Produces: a clean, verified branch ready for push.

- [ ] **Step 1: Update README**

Document the three button sets; queue/saved/todo and weekly/report commands;
per-user queue isolation; Monday recap for engineer and fde; one-message
interview delivery; reuse of existing webhook endpoints and secret; and the
fact that Sprint 1 records feedback without changing ranking.

State that the three external FDE repositories are scheduled for a separate
source adapter rather than active runtime ingestion.

- [ ] **Step 2: Run focused tests**

    python3 -m unittest \
      tests.test_interactions \
      tests.test_interaction_store \
      tests.test_telegram \
      tests.test_telegram_interactions \
      tests.test_telegram_commands \
      tests.test_digest \
      tests.test_job_alerts \
      tests.test_interview \
      tests.test_vercel_deploy -v

Expected: all focused tests PASS.

- [ ] **Step 3: Run the complete suite**

    python3 -m unittest discover -s tests -v

Expected: no errors and no failures.

- [ ] **Step 4: Run compile and diff checks**

    python3 -m compileall -q news_keep_up tests
    git diff --check
    git status --short

Expected: compile and diff checks exit zero and status contains only intended
files.

- [ ] **Step 5: Confirm notification invariants**

From test evidence and the final diff, confirm:

- four news items still emit two messages;
- three jobs still emit three messages;
- one interview run emits one message instead of two;
- callbacks call answerCallbackQuery and never sendMessage;
- automatic weekly recap is appended to the first existing digest chunk.

- [ ] **Step 6: Stage intended files and scan for credentials**

    git add README.md news_keep_up tests docs/superpowers/plans/2026-08-21-telegram-action-feedback-sprint-1.md
    git diff --cached --check
    git diff --cached | rg -n "AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|mongodb://|postgres://|mysql://|redis://"

Expected: no credential value or private key. Legitimate configuration names
and Telegram protocol terms are not secrets.

- [ ] **Step 7: Commit remaining documentation or test changes**

For documentation only:

    git commit -m "docs(telegram): document action workflow"

If residual tests and docs are both staged:

    git reset
    git add tests
    git commit -m "test(telegram): cover action workflow"
    git add README.md
    git commit -m "docs(telegram): document action workflow"

- [ ] **Step 8: Verify branch and push without force**

    git status --short
    git log --oneline origin/main..HEAD
    git push origin HEAD

Expected: a clean worktree and all new commits pushed to origin/main. Never
force push.
