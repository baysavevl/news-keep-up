import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from news_keep_up.scheduler import due_digest_jobs


ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class SchedulerTest(unittest.TestCase):
    def test_due_digest_jobs_include_current_job_alert_windows(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 10, 41, tzinfo=ICT))

        self.assertEqual(
            [(job.slot, job.scheduled_for.strftime("%H:%M")) for job in jobs],
            [("fde-jobs", "10:00"), ("fde-jobs", "10:30")],
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

        noon_jobs = due_digest_jobs(datetime(2026, 7, 14, 12, 10, tzinfo=ICT), lookback_minutes=10)
        self.assertEqual([job.slot for job in noon_jobs], ["fde-jobs"])

    def test_due_digest_jobs_include_interview_every_three_hours_in_business_window(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 14, 36, tzinfo=ICT), lookback_minutes=7 * 60)

        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in jobs if job.slot == "fde-interview"],
            ["08:35", "11:35", "14:35"],
        )

    def test_due_digest_jobs_include_fde_jobs_every_thirty_minutes(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 9, 31, tzinfo=ICT), lookback_minutes=35)

        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in jobs if job.slot == "fde-jobs"],
            ["09:00", "09:30"],
        )

    def test_due_digest_jobs_include_fde_jobs_only_between_7_and_21(self):
        before_window = due_digest_jobs(datetime(2026, 7, 14, 6, 59, tzinfo=ICT), lookback_minutes=30)
        window_start = due_digest_jobs(datetime(2026, 7, 14, 7, 1, tzinfo=ICT), lookback_minutes=5)
        window_end = due_digest_jobs(datetime(2026, 7, 14, 21, 1, tzinfo=ICT), lookback_minutes=35)
        after_window = due_digest_jobs(datetime(2026, 7, 14, 21, 31, tzinfo=ICT), lookback_minutes=30)

        self.assertNotIn("fde-jobs", [job.slot for job in before_window])
        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in window_start if job.slot == "fde-jobs"],
            ["07:00"],
        )
        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in window_end if job.slot == "fde-jobs"],
            ["20:30", "21:00"],
        )
        self.assertNotIn("fde-jobs", [job.slot for job in after_window])

    def test_due_digest_jobs_include_daily_fde_job_source_maintenance(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 7, 11, tzinfo=ICT), lookback_minutes=5)

        self.assertEqual(
            [job.scheduled_for.strftime("%H:%M") for job in jobs if job.slot == "fde-job-sources"],
            ["07:10"],
        )

    def test_due_digest_jobs_skip_outside_operating_hours(self):
        jobs = due_digest_jobs(datetime(2026, 7, 14, 6, 59, tzinfo=ICT))

        self.assertNotIn("fde-interview", [job.slot for job in jobs])


if __name__ == "__main__":
    unittest.main()
