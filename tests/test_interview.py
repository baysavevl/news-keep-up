import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from news_keep_up.interview import (
    FDE_INTERVIEW_GUIDELINES,
    format_fde_interview_guideline,
    run_fde_interview_guideline,
    select_fde_interview_guidelines,
    select_fde_interview_guideline,
)
from news_keep_up.models import Settings


class FdeInterviewGuidelineTest(unittest.TestCase):
    def test_guideline_pool_has_enough_rotation_depth(self):
        self.assertGreaterEqual(len(FDE_INTERVIEW_GUIDELINES), 12)

    def test_select_guideline_rotates_hourly_from_0735(self):
        first = select_fde_interview_guideline(datetime(2026, 7, 13, 7, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
        next_window = select_fde_interview_guideline(datetime(2026, 7, 13, 8, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))

        self.assertNotEqual(first.slug, next_window.slug)

    def test_select_guidelines_returns_two_distinct_cards_per_send(self):
        cards = select_fde_interview_guidelines(datetime(2026, 7, 13, 7, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))

        self.assertEqual(len(cards), 2)
        self.assertEqual(len({card.slug for card in cards}), 2)

    def test_format_guideline_includes_at_least_two_contents(self):
        message = format_fde_interview_guideline(
            select_fde_interview_guidelines(datetime(2026, 7, 13, 7, 35, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
        )

        lines = [line for line in message.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 7)
        self.assertIn("FDE Interview", message)
        self.assertGreaterEqual(message.count("🎯"), 2)
        self.assertGreaterEqual(message.count("🧪"), 2)
        self.assertGreaterEqual(message.count("🔗"), 2)

    def test_run_guideline_sends_to_fde_chat_when_not_dry_run(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123", db_path=Path("test.db"))

        with patch("news_keep_up.interview.send_telegram_message") as send:
            message = run_fde_interview_guideline(settings, dry_run=False)

        self.assertIn("FDE Interview", message)
        self.assertGreaterEqual(message.count("🎯"), 2)
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
