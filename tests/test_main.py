import unittest
from io import StringIO
import tempfile
from pathlib import Path
from unittest.mock import patch

from news_keep_up.db import connect_database, init_db, record_source_fetch_log
from news_keep_up.main import main
from news_keep_up.models import Settings, SourceFetchLog


class MainCliTest(unittest.TestCase):
    def test_run_digest_force_flag_passes_to_fde_jobs_flow(self):
        with (
            patch("news_keep_up.main.load_settings", return_value=Settings()),
            patch("news_keep_up.main.run_fde_job_alerts", return_value="") as run_jobs,
        ):
            exit_code = main(["run-digest", "--slot", "fde-jobs", "--force"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(run_jobs.call_args.kwargs["force"])

    def test_source_health_command_prints_recent_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            settings = Settings(db_path=db_path)
            conn = connect_database(settings)
            init_db(conn)
            record_source_fetch_log(conn, SourceFetchLog(
                slot="fde-jobs",
                source_name="Blocked Upwork",
                source_url="https://www.upwork.com/nx/search/jobs/?q=fde",
                source_kind="html",
                status="failed",
                item_count=0,
                error_type="HTTPError",
                error_message="HTTP Error 403: Forbidden",
                fetched_at="2026-08-04T08:00:00+07:00",
            ))
            conn.close()

            stdout = StringIO()
            with (
                patch("news_keep_up.main.load_settings", return_value=Settings(db_path=db_path)),
                patch("sys.stdout", stdout),
            ):
                exit_code = main(["source-health", "--slot", "fde-jobs"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Blocked Upwork", output)
        self.assertIn("failed=1", output)
        self.assertIn("403", output)

    def test_probe_job_sources_command_prints_fetch_only_summary(self):
        with (
            patch("news_keep_up.main.load_settings", return_value=Settings()),
            patch(
                "news_keep_up.main.probe_fde_job_sources",
                return_value={
                    "sources": 150,
                    "fetched_items": 42,
                    "source_filtered_candidates": 12,
                    "fde_candidates": 5,
                    "workable_candidates": 3,
                    "rows": [],
                },
            ) as probe,
        ):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["probe-job-sources"])

        self.assertEqual(exit_code, 0)
        probe.assert_called_once()
        self.assertIn("sources=150", stdout.getvalue())
        self.assertIn("workable=3", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
