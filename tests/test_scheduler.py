import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from news_keep_up.scheduler import due_digest_jobs


ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class SchedulerTest(unittest.TestCase):
    def test_due_digest_jobs_include_current_interview_window(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 10, 41, tzinfo=ICT))

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde-interview", "10:35")],
        )

    def test_due_digest_jobs_include_engineer_news_at_fixed_times(self):
        all_day_jobs = due_digest_jobs(datetime(2026, 7, 14, 16, 1, tzinfo=ICT), lookback_minutes=9 * 60)

        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in all_day_jobs if job.slot == "engineer"],
            ["09:15", "16:00"],
        )

        self.assertEqual(
            due_digest_jobs(datetime(2026, 7, 14, 13, 41, tzinfo=ICT), lookback_minutes=1),
            [],
        )

    def test_due_digest_jobs_include_fde_news_at_two_fixed_times(self):
        all_day_jobs = due_digest_jobs(datetime(2026, 7, 14, 14, 1, tzinfo=ICT), lookback_minutes=7 * 60)

        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in all_day_jobs if job.slot == "fde"],
            ["08:00", "14:00"],
        )

        self.assertEqual(due_digest_jobs(datetime(2026, 7, 14, 12, 10, tzinfo=ICT), lookback_minutes=10), [])

    def test_due_digest_jobs_include_interview_hourly_from_0735(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 8, 36, tzinfo=ICT), lookback_minutes=10)

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde-interview", "08:35")],
        )

    def test_due_digest_jobs_skip_outside_operating_hours(self):
        self.assertEqual(due_digest_jobs(datetime(2026, 7, 14, 6, 59, tzinfo=ICT)), [])


if __name__ == "__main__":
    unittest.main()
