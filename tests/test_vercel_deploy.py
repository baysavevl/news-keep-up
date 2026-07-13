import json
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


class VercelDeployConfigTest(unittest.TestCase):
    def test_pyproject_declares_python_entrypoint(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["tool"]["vercel"]["entrypoint"],
            "news_keep_up.vercel_app:app",
        )

    def test_vercel_json_declares_digest_crons(self):
        config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config["crons"],
            [
                {"path": "/api/digest/news", "schedule": "10 1,3,5,7,9,11,13 * * *"},
            ],
        )

    def test_python_runtime_is_pinned_to_github_actions_version(self):
        self.assertEqual(Path(".python-version").read_text(encoding="utf-8").strip(), "3.12")

    def test_github_actions_is_manual_fallback_only(self):
        workflow = Path(".github/workflows/digest.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)


class VercelDigestEndpointTest(unittest.TestCase):
    def test_digest_endpoint_requires_cron_secret(self):
        from news_keep_up.vercel_app import app

        with patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False):
            response = app.test_client().get("/api/digest/morning")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_digest_endpoint_runs_requested_slot(self):
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.run_digest", return_value="digest text") as run_digest,
        ):
            response = app.test_client().get(
                "/api/digest/news",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slot"], "news")
        self.assertFalse(response.get_json()["dry_run"])
        self.assertEqual(run_digest.call_args.args[1], "news")
        self.assertFalse(run_digest.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
