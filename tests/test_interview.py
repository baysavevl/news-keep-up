import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from news_keep_up.db import connect_database, init_db
from news_keep_up.interview import (
    FDE_INTERVIEW_GUIDELINES,
    format_fde_interview_announcement,
    format_fde_interview_guideline,
    run_fde_interview_guideline,
    select_fde_interview_guidelines,
    select_fde_interview_guideline,
)
from news_keep_up.models import Settings
from news_keep_up.telegram_interactions import decode_callback


class FdeInterviewGuidelineTest(unittest.TestCase):
    def test_guideline_pool_has_enough_rotation_depth(self):
        self.assertGreaterEqual(len(FDE_INTERVIEW_GUIDELINES), 12)

    def test_select_guideline_rotates_across_three_hour_slots(self):
        first = select_fde_interview_guideline(datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
        next_window = select_fde_interview_guideline(datetime(2026, 7, 13, 11, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))

        self.assertNotEqual(first.slug, next_window.slug)

    def test_select_guidelines_returns_two_distinct_cards_per_send(self):
        cards = select_fde_interview_guidelines(datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))

        self.assertEqual(len(cards), 2)
        self.assertEqual(len({card.slug for card in cards}), 2)

    def test_format_guideline_includes_at_least_two_contents(self):
        message = format_fde_interview_guideline(
            select_fde_interview_guidelines(datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
        )

        lines = [line for line in message.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 7)
        self.assertIn("FDE Interview", message)
        self.assertGreaterEqual(message.count("FDE topic:"), 2)
        self.assertGreaterEqual(message.count("Interview focus:"), 2)
        self.assertGreaterEqual(message.count("Kiến thức:"), 2)
        self.assertGreaterEqual(message.count("🎯"), 2)
        self.assertGreaterEqual(message.count("🧪"), 2)
        self.assertGreaterEqual(message.count("🔗"), 2)

    def test_announcement_uses_three_hour_business_schedule(self):
        announcement = format_fde_interview_announcement(
            select_fde_interview_guidelines(datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))),
            datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
        )

        self.assertIn("08:35, 11:35, 14:35", announcement)
        self.assertNotIn("hourly", announcement.lower())
        self.assertNotIn("FDE topics:", announcement)

    def test_run_guideline_sends_one_combined_interactive_message(self):
        current = datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        expected_cards = select_fde_interview_guidelines(current)

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                telegram_bot_token="token",
                telegram_chat_id="-100123",
                db_path=Path(tmp) / "test.db",
            )
            with patch(
                "news_keep_up.telegram_interactions.send_telegram_message",
                return_value=[{"message_id": 801}],
            ) as send:
                message = run_fde_interview_guideline(
                    settings,
                    dry_run=False,
                    current=current,
                )

            conn = connect_database(settings)
            deliveries = conn.execute(
                """SELECT id, subject_id, delivery_kind, delivery_state,
                          telegram_message_id
                   FROM engagement_deliveries ORDER BY id"""
            ).fetchall()
            conn.close()

        self.assertIn("FDE Interview", message)
        self.assertEqual(send.call_count, 1)
        sent_text = send.call_args.args[0]
        self.assertIn("Interview Prep Thread", sent_text)
        self.assertIn("FDE Interview Guideline", sent_text)
        self.assertGreaterEqual(message.count("🎯"), 2)
        keyboard = send.call_args.kwargs["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(keyboard), 2)
        self.assertEqual(
            [[button["text"] for button in row] for row in keyboard],
            [
                ["1 ✅ Đã luyện", "1 🔁 Nhắc lại", "1 🚫"],
                ["2 ✅ Đã luyện", "2 🔁 Nhắc lại", "2 🚫"],
            ],
        )
        self.assertEqual(
            [row["subject_id"] for row in deliveries],
            [card.slug for card in expected_cards],
        )
        self.assertEqual(
            [
                (row["delivery_kind"], row["delivery_state"], row["telegram_message_id"])
                for row in deliveries
            ],
            [("content", "delivered", "801"), ("content", "delivered", "801")],
        )
        self.assertEqual(
            [decode_callback(row[0]["callback_data"])[0] for row in keyboard],
            [row["id"] for row in deliveries],
        )

    def test_interview_dry_run_returns_combined_text_without_engagement_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db")

            message = run_fde_interview_guideline(
                settings,
                dry_run=True,
                current=datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
            )

            conn = connect_database(settings)
            init_db(conn)
            count = conn.execute("SELECT COUNT(*) FROM engagement_deliveries").fetchone()[0]
            conn.close()

        self.assertIn("Interview Prep Thread", message)
        self.assertIn("FDE Interview Guideline", message)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
