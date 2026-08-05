import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_keep_up.models import Settings


ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class SchedulerRunnerTest(unittest.TestCase):
    def test_service_tick_processes_due_backlog_without_http_cap(self):
        from news_keep_up.scheduler_runner import run_scheduler_tick

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db")
            current = datetime(2026, 8, 4, 9, 5, tzinfo=ICT)
            result = run_scheduler_tick(
                settings=settings,
                current=current,
                lookback_minutes=180,
                max_jobs_per_tick=None,
                profile_runner=_profile_runner,
            )

        self.assertTrue(result["ok"])
        self.assertGreater(result["triggered"], 3)
        slots = [row["slot"] for row in result["results"] if row["status"] == "done"]
        self.assertIn("fde-job-sources", slots)
        self.assertIn("fde-interview", slots)
        self.assertGreaterEqual(slots.count("fde-jobs"), 3)


def _profile_runner(_profile, dry_run, current=None, send_window_current=None):
    return {
        "delivery_configured": True,
        "message_length": len(current.isoformat() if current else ""),
    }


if __name__ == "__main__":
    unittest.main()
