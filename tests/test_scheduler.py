import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from news_keep_up.scheduler import due_digest_jobs


ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class SchedulerTest(unittest.TestCase):
    def test_due_digest_jobs_include_current_engineer_and_interview_windows(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 10, 41, tzinfo=ICT))

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde-interview", "10:35"), ("engineer", "10:40")],
        )

    def test_due_digest_jobs_include_engineer_news_every_three_hours_from_0740(self):
        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in due_digest_jobs(
                datetime(2026, 7, 14, 13, 41, tzinfo=ICT),
                lookback_minutes=1,
            )],
            [("engineer", "13:40")],
        )

        self.assertEqual(
            due_digest_jobs(datetime(2026, 7, 14, 11, 41, tzinfo=ICT), lookback_minutes=1),
            [],
        )

    def test_due_digest_jobs_include_fde_news_every_two_hours_from_0720(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 9, 21, tzinfo=ICT), lookback_minutes=10)

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde", "09:20")],
        )

        self.assertEqual(due_digest_jobs(datetime(2026, 7, 14, 8, 21, tzinfo=ICT), lookback_minutes=10), [])

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
