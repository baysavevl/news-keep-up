import sqlite3
import unittest
from datetime import datetime
from unittest.mock import patch

from news_keep_up.db import init_db
from news_keep_up.interactions import EngagementDelivery, InteractionSubject
from news_keep_up.models import Settings
from news_keep_up.telegram_interactions import (
    ACTION_TO_CODE,
    ButtonSpec,
    InteractiveSubject,
    build_inline_keyboard,
    decode_callback,
    encode_callback,
    send_interactive_message,
)
from news_keep_up.utils import ICT


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


if __name__ == "__main__":
    unittest.main()
