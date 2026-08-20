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

    def test_unknown_subject_has_no_allowed_actions(self):
        self.assertEqual(allowed_actions("unknown"), set())

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

    def test_report_period_converts_an_aware_time_to_ict(self):
        current = datetime.fromisoformat("2026-08-23T18:30:00+00:00")

        period = report_period(current)

        self.assertEqual(period.end.isoformat(), "2026-08-24T00:00:00+07:00")

    def test_compact_weekly_report_has_four_lines_and_no_fake_cost(self):
        metrics = WeeklyMetrics(
            delivered=24,
            responded=17,
            useful=14,
            noise=3,
            queued=6,
            completed=4,
            open_items=2,
            apply=0,
            verify=0,
            repeat=0,
        )

        report = format_weekly_report(metrics, "engineer", compact=True)

        self.assertEqual(len(report.splitlines()), 4)
        self.assertIn("24 delivered", report)
        self.assertIn("17 responded (71%)", report)
        self.assertIn("14 useful", report)
        self.assertIn("82% useful", report)
        self.assertNotIn("$", report)

    def test_profile_specific_report_uses_job_and_interview_outcomes(self):
        metrics = WeeklyMetrics(
            delivered=8,
            responded=5,
            useful=0,
            noise=0,
            queued=5,
            completed=3,
            open_items=2,
            apply=3,
            verify=2,
            repeat=1,
        )

        jobs = format_weekly_report(metrics, "fde-jobs", compact=True)
        interview = format_weekly_report(metrics, "fde-interview", compact=True)

        self.assertIn("3 apply", jobs)
        self.assertIn("2 verify", jobs)
        self.assertIn("3 practiced", interview)
        self.assertIn("1 repeat", interview)


if __name__ == "__main__":
    unittest.main()
