import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from news_keep_up.scheduler import due_digest_jobs


ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class SchedulerTest(unittest.TestCase):
    def test_due_digest_jobs_include_current_fde_and_engineer_windows(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 10, 41, tzinfo=ICT))

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde", "10:20"), ("engineer", "10:40")],
        )

    def test_due_digest_jobs_include_interview_every_two_hours_from_0735(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 9, 36, tzinfo=ICT), lookback_minutes=10)

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde-interview", "09:35")],
        )

    def test_due_digest_jobs_skip_outside_operating_hours(self):
        self.assertEqual(due_digest_jobs(datetime(2026, 7, 14, 6, 59, tzinfo=ICT)), [])


if __name__ == "__main__":
    unittest.main()
