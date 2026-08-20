import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from news_keep_up.db import connect_database, init_db, upsert_item
from news_keep_up.interaction_store import (
    mark_engagement_delivered,
    plan_engagement_deliveries,
    record_interaction,
)
from news_keep_up.interactions import (
    EngagementDelivery,
    InteractionSubject,
    QueueEntry,
    ResolvedQueueEntry,
)
from news_keep_up.models import CandidateItem, Settings
from news_keep_up.telegram_interactions import (
    ACTION_TO_CODE,
    ButtonSpec,
    InteractiveSubject,
    _queue_entry_text,
    build_inline_keyboard,
    decode_callback,
    encode_callback,
    handle_interaction_callback,
    send_queue_response,
    send_interactive_message,
    weekly_report_text,
)
from news_keep_up.utils import ICT

CREATED = "2026-08-21T10:00:00+07:00"


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def delivery(identifier, subject_type="news", subject_id=None):
    return EngagementDelivery(
        id=identifier,
        profile="engineer",
        subject_type=subject_type,
        subject_id=str(subject_id if subject_id is not None else identifier),
        delivery_kind="content",
        chat_id="-1001",
        delivery_state="planned",
        telegram_message_id="",
        created_at="2026-08-21T10:00:00+07:00",
        delivered_at="",
    )


class TelegramInteractionsTest(unittest.TestCase):
    def test_callback_codec_round_trips_compact_payload(self):
        payload = encode_callback(123, "useful")

        self.assertEqual(payload, "i1|123|u")
        self.assertEqual(decode_callback(payload), (123, "useful"))

    def test_callback_decoder_rejects_malformed_payloads(self):
        invalid = [
            "i2|123|u",
            "i1|abc|u",
            "i1|0|u",
            "i1|123|z",
            "i1|123|u|extra",
            "x" * 65,
        ]

        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    decode_callback(payload)

    def test_every_action_code_fits_telegram_callback_limit(self):
        for action in ACTION_TO_CODE:
            with self.subTest(action=action):
                self.assertLessEqual(
                    len(encode_callback(9_223_372_036_854_775_807, action).encode("utf-8")),
                    64,
                )

    def test_two_news_subjects_build_two_numbered_rows(self):
        subjects = [
            InteractiveSubject(
                InteractionSubject("news", 10),
                (ButtonSpec("👍", "useful"), ButtonSpec("📌", "save")),
            ),
            InteractiveSubject(
                InteractionSubject("news", 11),
                (ButtonSpec("👍", "useful"), ButtonSpec("📌", "save")),
            ),
        ]

        markup = build_inline_keyboard(
            [delivery(1, subject_id=10), delivery(2, subject_id=11)],
            subjects,
            numbered=True,
        )

        rows = markup["inline_keyboard"]
        self.assertEqual([[button["text"] for button in row] for row in rows], [["1 👍", "1 📌"], ["2 👍", "2 📌"]])
        self.assertEqual(decode_callback(rows[0][0]["callback_data"]), (1, "useful"))
        self.assertEqual(decode_callback(rows[1][1]["callback_data"]), (2, "save"))

    def test_keyboard_rejects_an_action_incompatible_with_subject(self):
        subject = InteractiveSubject(
            InteractionSubject("job", "job-1"),
            (ButtonSpec("👍", "useful"),),
        )

        with self.assertRaises(ValueError):
            build_inline_keyboard([delivery(1, "job", "job-1")], [subject])

    def test_interactive_send_marks_every_subject_with_message_id(self):
        conn = connection()
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-1001")
        subjects = [
            InteractiveSubject(
                InteractionSubject("news", 10),
                (ButtonSpec("👍", "useful"),),
            ),
            InteractiveSubject(
                InteractionSubject("news", 11),
                (ButtonSpec("👍", "useful"),),
            ),
        ]

        with patch(
            "news_keep_up.telegram_interactions.send_telegram_message",
            return_value=[{"message_id": 99}],
        ) as sender:
            rows = send_interactive_message(
                conn,
                settings,
                "engineer",
                "Digest",
                subjects,
                numbered=True,
                current=datetime(2026, 8, 21, 10, 0, tzinfo=ICT),
            )

        self.assertEqual([row.delivery_state for row in rows], ["delivered", "delivered"])
        self.assertEqual([row.telegram_message_id for row in rows], ["99", "99"])
        markup = sender.call_args.kwargs["reply_markup"]
        self.assertEqual(len(markup["inline_keyboard"]), 2)
        conn.close()

    def test_interactive_send_marks_plans_failed_when_telegram_fails(self):
        conn = connection()
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-1001")
        subjects = [
            InteractiveSubject(
                InteractionSubject("news", 10),
                (ButtonSpec("👍", "useful"),),
            )
        ]

        with patch(
            "news_keep_up.telegram_interactions.send_telegram_message",
            side_effect=RuntimeError("Telegram unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                send_interactive_message(
                    conn,
                    settings,
                    "engineer",
                    "Digest",
                    subjects,
                    current=datetime(2026, 8, 21, 10, 0, tzinfo=ICT),
                )

        state = conn.execute(
            "SELECT delivery_state FROM engagement_deliveries"
        ).fetchone()[0]
        self.assertEqual(state, "failed")
        conn.close()

    def test_valid_callback_records_action_and_answers_only_a_toast(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(
                conn,
                CandidateItem(
                    source_name="Source",
                    source_kind="rss",
                    source_category="ai",
                    title="Agent article",
                    url="https://example.com/article",
                    canonical_url="https://example.com/article",
                ),
            )
            planned = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [InteractionSubject("news", item_id)],
                "content",
                "2026-08-21T10:00:00+07:00",
            )[0]
            mark_engagement_delivered(
                conn,
                [planned.id],
                "700",
                "2026-08-21T10:00:00+07:00",
            )
            conn.close()
            callback = {
                "id": "cb-1",
                "from": {"id": 42},
                "data": encode_callback(planned.id, "save"),
                "message": {"message_id": 700, "chat": {"id": -1001}},
            }

            with (
                patch("news_keep_up.telegram_interactions.answer_telegram_callback") as answer,
                patch("news_keep_up.telegram_interactions.send_telegram_message") as send,
            ):
                result = handle_interaction_callback(
                    callback,
                    profile="engineer",
                    settings=settings,
                    current=datetime(2026, 8, 21, 10, 5, tzinfo=ICT),
                )

            conn = connect_database(settings)
            event_count = conn.execute("SELECT COUNT(*) FROM interaction_events").fetchone()[0]
            queue_status = conn.execute("SELECT status FROM action_queue").fetchone()[0]
            conn.close()

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "save")
        self.assertTrue(result["changed"])
        self.assertEqual(event_count, 1)
        self.assertEqual(queue_status, "open")
        answer.assert_called_once()
        self.assertIn("/queue", answer.call_args.args[1])
        send.assert_not_called()

    def test_duplicate_callback_returns_success_without_second_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(
                conn,
                CandidateItem(
                    source_name="Source",
                    source_kind="rss",
                    source_category="ai",
                    title="Agent article",
                    url="https://example.com/article",
                    canonical_url="https://example.com/article",
                ),
            )
            planned = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [InteractionSubject("news", item_id)],
                "content",
                CREATED,
            )[0]
            mark_engagement_delivered(conn, [planned.id], "700", CREATED)
            conn.close()

            callback = {
                "id": "cb-duplicate",
                "from": {"id": 42},
                "data": encode_callback(planned.id, "useful"),
                "message": {"message_id": 700, "chat": {"id": -1001}},
            }
            with patch("news_keep_up.telegram_interactions.answer_telegram_callback"):
                first = handle_interaction_callback(callback, profile="engineer", settings=settings)
                second = handle_interaction_callback(callback, profile="engineer", settings=settings)

            conn = connect_database(settings)
            count = conn.execute("SELECT COUNT(*) FROM interaction_events").fetchone()[0]
            conn.close()

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(count, 1)

    def test_callback_rejects_wrong_chat_and_mismatched_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            rows = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [InteractionSubject("news", 1)],
                "content",
                CREATED,
            )
            mark_engagement_delivered(conn, [rows[0].id], "700", CREATED)
            conn.close()
            base = {
                "id": "cb-invalid",
                "from": {"id": 42},
                "data": encode_callback(rows[0].id, "save"),
            }

            with patch("news_keep_up.telegram_interactions.answer_telegram_callback"):
                wrong_chat = handle_interaction_callback(
                    {**base, "message": {"message_id": 700, "chat": {"id": -999}}},
                    profile="engineer",
                    settings=settings,
                )
                wrong_message = handle_interaction_callback(
                    {**base, "id": "cb-invalid-2", "message": {"message_id": 701, "chat": {"id": -1001}}},
                    profile="engineer",
                    settings=settings,
                )

            conn = connect_database(settings)
            count = conn.execute("SELECT COUNT(*) FROM interaction_events").fetchone()[0]
            conn.close()

        self.assertEqual(wrong_chat["reason"], "unauthorized_chat")
        self.assertEqual(wrong_message["reason"], "stale_message")
        self.assertEqual(count, 0)

    def test_callback_rejects_incompatible_action_and_missing_subjects(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            rows = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [
                    InteractionSubject("job", "missing-job"),
                    InteractionSubject("news", 999),
                    InteractionSubject("interview", "missing-drill"),
                ],
                "content",
                CREATED,
            )
            mark_engagement_delivered(conn, [row.id for row in rows], "700", CREATED)
            conn.close()

            def callback(row, action, identifier):
                return {
                    "id": identifier,
                    "from": {"id": 42},
                    "data": encode_callback(row.id, action),
                    "message": {"message_id": 700, "chat": {"id": -1001}},
                }

            with patch("news_keep_up.telegram_interactions.answer_telegram_callback"):
                incompatible = handle_interaction_callback(
                    callback(rows[0], "useful", "cb-action"),
                    profile="engineer",
                    settings=settings,
                )
                missing_job = handle_interaction_callback(
                    callback(rows[0], "save", "cb-job"),
                    profile="engineer",
                    settings=settings,
                )
                missing_news = handle_interaction_callback(
                    callback(rows[1], "save", "cb-news"),
                    profile="engineer",
                    settings=settings,
                )
                missing_interview = handle_interaction_callback(
                    callback(rows[2], "done", "cb-interview"),
                    profile="engineer",
                    settings=settings,
                )

        self.assertEqual(incompatible["reason"], "incompatible_action")
        self.assertEqual(missing_job["reason"], "missing_subject")
        self.assertEqual(missing_news["reason"], "missing_subject")
        self.assertEqual(missing_interview["reason"], "missing_subject")

    def test_matching_planned_callback_promotes_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(
                conn,
                CandidateItem(
                    source_name="Source",
                    source_kind="rss",
                    source_category="ai",
                    title="Agent article",
                    url="https://example.com/article",
                    canonical_url="https://example.com/article",
                ),
            )
            planned = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [InteractionSubject("news", item_id)],
                "content",
                CREATED,
            )[0]
            conn.close()

            with patch("news_keep_up.telegram_interactions.answer_telegram_callback"):
                result = handle_interaction_callback(
                    {
                        "id": "cb-promote",
                        "from": {"id": 42},
                        "data": encode_callback(planned.id, "useful"),
                        "message": {"message_id": 700, "chat": {"id": -1001}},
                    },
                    profile="engineer",
                    settings=settings,
                    current=datetime(2026, 8, 21, 10, 5, tzinfo=ICT),
                )

            conn = connect_database(settings)
            stored = conn.execute(
                "SELECT delivery_state, telegram_message_id FROM engagement_deliveries"
            ).fetchone()
            conn.close()

        self.assertTrue(result["ok"])
        self.assertEqual((stored["delivery_state"], stored["telegram_message_id"]), ("delivered", "700"))

    def test_invalid_planned_callback_does_not_promote_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            planned = plan_engagement_deliveries(
                conn,
                "fde-jobs",
                "-1001",
                [InteractionSubject("job", "missing-job")],
                "content",
                CREATED,
            )[0]
            conn.close()

            with patch("news_keep_up.telegram_interactions.answer_telegram_callback"):
                result = handle_interaction_callback(
                    {
                        "id": "cb-invalid-planned",
                        "from": {"id": 42},
                        "data": encode_callback(planned.id, "useful"),
                        "message": {"message_id": 700, "chat": {"id": -1001}},
                    },
                    profile="fde-jobs",
                    settings=settings,
                )

            conn = connect_database(settings)
            state = conn.execute(
                "SELECT delivery_state FROM engagement_deliveries WHERE id=?",
                (planned.id,),
            ).fetchone()[0]
            conn.close()

        self.assertEqual(result["reason"], "incompatible_action")
        self.assertEqual(state, "planned")

    def test_queue_response_is_actor_scoped_and_creates_fresh_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_ids = []
            for index in (1, 2):
                item_id, _ = upsert_item(
                    conn,
                    CandidateItem(
                        source_name="Source",
                        source_kind="rss",
                        source_category="ai",
                        title=f"Article {index}",
                        url=f"https://example.com/article-{index}",
                        canonical_url=f"https://example.com/article-{index}",
                    ),
                )
                item_ids.append(item_id)
            deliveries = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [InteractionSubject("news", item_id) for item_id in item_ids],
                "content",
                CREATED,
            )
            mark_engagement_delivered(
                conn,
                [row.id for row in deliveries],
                "700",
                CREATED,
            )
            record_interaction(conn, deliveries[0].id, "save", "42", "cb-save-42", CREATED)
            record_interaction(conn, deliveries[1].id, "save", "84", "cb-save-84", CREATED)
            conn.close()

            with patch(
                "news_keep_up.telegram_interactions.send_telegram_message",
                return_value=[{"message_id": 701}],
            ) as sender:
                result = send_queue_response(
                    settings,
                    profile="engineer",
                    chat_id="-1001",
                    actor_user_id="42",
                    reply_to_message_id=55,
                    current=datetime(2026, 8, 21, 11, 0, tzinfo=ICT),
                )

            conn = connect_database(settings)
            queue_targets = conn.execute(
                """SELECT subject_id, delivery_kind, telegram_message_id
                   FROM engagement_deliveries WHERE delivery_kind='queue'"""
            ).fetchall()
            conn.close()

        sent_text = sender.call_args.args[0]
        markup = sender.call_args.kwargs["reply_markup"]
        self.assertEqual(result["count"], 1)
        self.assertIn("Article 1", sent_text)
        self.assertNotIn("Article 2", sent_text)
        self.assertEqual(
            [button["text"] for button in markup["inline_keyboard"][0]],
            ["1 ✅ Xong", "1 🗑 Bỏ"],
        )
        self.assertEqual(sender.call_args.kwargs["reply_to_message_id"], 55)
        self.assertEqual(
            [(row["subject_id"], row["delivery_kind"], row["telegram_message_id"]) for row in queue_targets],
            [(str(item_ids[0]), "queue", "701")],
        )

    def test_queue_response_marks_missing_subject_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-1001",
            )
            conn = connect_database(settings)
            init_db(conn)
            delivery = plan_engagement_deliveries(
                conn,
                "engineer",
                "-1001",
                [InteractionSubject("news", 999)],
                "content",
                CREATED,
            )[0]
            mark_engagement_delivered(conn, [delivery.id], "700", CREATED)
            record_interaction(conn, delivery.id, "save", "42", "cb-missing", CREATED)
            conn.close()

            with patch(
                "news_keep_up.telegram_interactions.send_telegram_message",
                return_value=[{"message_id": 701}],
            ) as sender:
                result = send_queue_response(
                    settings,
                    profile="engineer",
                    chat_id="-1001",
                    actor_user_id="42",
                    current=datetime(2026, 8, 21, 11, 0, tzinfo=ICT),
                )

            conn = connect_database(settings)
            status = conn.execute("SELECT status FROM action_queue").fetchone()[0]
            target_count = conn.execute(
                "SELECT COUNT(*) FROM engagement_deliveries WHERE delivery_kind='queue'"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(result["count"], 0)
        self.assertEqual(sender.call_args.args[0], "Queue trống.")
        self.assertNotIn("reply_markup", sender.call_args.kwargs)
        self.assertEqual(status, "unavailable")
        self.assertEqual(target_count, 0)

    def test_queue_entry_with_long_escaped_metadata_stays_valid_and_compact(self):
        queue = QueueEntry(
            profile="engineer",
            chat_id="-1001",
            actor_user_id="42",
            subject_type="news",
            subject_id="1",
            queue_action="save",
            status="open",
            created_at=CREATED,
            updated_at=CREATED,
            completed_at="",
        )
        entry = ResolvedQueueEntry(
            queue=queue,
            title="&" * 500,
            url="https://e.test/?" + ("&" * 160),
        )

        rendered = _queue_entry_text(1, entry)

        self.assertLessEqual(len(rendered), 350)
        self.assertEqual(rendered.count("<b>"), rendered.count("</b>"))
        self.assertEqual(rendered.count("<a "), rendered.count("</a>"))

    def test_weekly_report_text_uses_profile_specific_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db")
            conn = connect_database(settings)
            init_db(conn)
            fixtures = [
                ("engineer", InteractionSubject("news", 1), [("useful", "cb-useful"), ("save", "cb-save")]),
                ("fde-jobs", InteractionSubject("job", "job-1"), [("apply", "cb-apply")]),
                ("fde-jobs", InteractionSubject("job", "job-2"), [("verify", "cb-verify")]),
                ("fde-interview", InteractionSubject("interview", "agent-state"), [("done", "cb-done")]),
                ("fde-interview", InteractionSubject("interview", "tool-boundaries"), [("repeat", "cb-repeat")]),
            ]
            for index, (profile, subject, actions) in enumerate(fixtures, start=1):
                row = plan_engagement_deliveries(
                    conn,
                    profile,
                    "-1001",
                    [subject],
                    "content",
                    "2026-08-20T10:00:00+07:00",
                )[0]
                mark_engagement_delivered(
                    conn,
                    [row.id],
                    str(700 + index),
                    "2026-08-20T10:00:00+07:00",
                )
                for action, callback_id in actions:
                    record_interaction(
                        conn,
                        row.id,
                        action,
                        "42",
                        callback_id,
                        "2026-08-20T11:00:00+07:00",
                    )
            conn.close()
            current = datetime(2026, 8, 24, 9, 0, tzinfo=ICT)

            engineer = weekly_report_text(
                settings,
                profile="engineer",
                chat_id="-1001",
                actor_user_id="42",
                current=current,
            )
            jobs = weekly_report_text(
                settings,
                profile="fde-jobs",
                chat_id="-1001",
                actor_user_id="42",
                current=current,
            )
            interview = weekly_report_text(
                settings,
                profile="fde-interview",
                chat_id="-1001",
                actor_user_id="42",
                current=current,
            )

        self.assertIn("17/08–23/08", engineer)
        self.assertIn("1 useful", engineer)
        self.assertIn("1 apply", jobs)
        self.assertIn("1 verify", jobs)
        self.assertIn("1 practiced", interview)
        self.assertIn("1 repeat", interview)


if __name__ == "__main__":
    unittest.main()
