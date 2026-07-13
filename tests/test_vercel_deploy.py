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

    def test_vercel_json_does_not_declare_hobby_blocked_crons(self):
        config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

        self.assertNotIn("crons", config)

    def test_python_runtime_is_pinned_to_github_actions_version(self):
        self.assertEqual(Path(".python-version").read_text(encoding="utf-8").strip(), "3.12")

    def test_github_actions_triggers_vercel_hourly_from_8_to_22_ict(self):
        workflow = Path(".github/workflows/digest.yml").read_text(encoding="utf-8")

        self.assertIn('cron: "20 1-15 * * *"', workflow)
        self.assertIn('cron: "40 1-15 * * *"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("https://news-keep-up.vercel.app/api/digest/engineer", workflow)
        self.assertIn("https://news-keep-up.vercel.app/api/digest/fde", workflow)
        self.assertIn("github.event.schedule == '20 1-15 * * *'", workflow)
        self.assertIn("github.event.schedule == '40 1-15 * * *'", workflow)
        self.assertIn("secrets.CRON_SECRET", workflow)


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
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "-100123",
            }, clear=False),
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
        self.assertEqual(run_digest.call_args.kwargs["sources_path"], "config/sources.json")
        self.assertFalse(run_digest.call_args.kwargs["dry_run"])

    def test_fde_endpoint_uses_fde_sources_and_env_prefix(self):
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "FDE_TELEGRAM_BOT_TOKEN": "token",
                "FDE_TELEGRAM_CHAT_ID": "-100123",
            }, clear=False),
            patch("news_keep_up.vercel_app.load_settings") as load_settings,
            patch("news_keep_up.vercel_app.run_digest", return_value="digest text") as run_digest,
        ):
            response = app.test_client().get(
                "/api/digest/fde",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slot"], "fde")
        load_settings.assert_called_once_with(env_prefix="FDE")
        self.assertEqual(run_digest.call_args.args[1], "fde")
        self.assertEqual(run_digest.call_args.kwargs["sources_path"], "config/fde_sources.json")

    def test_profile_endpoint_skips_delivery_when_telegram_chat_is_missing(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings(telegram_bot_token="token", telegram_chat_id="")),
            patch("news_keep_up.vercel_app.run_digest") as run_digest,
        ):
            response = app.test_client().get(
                "/api/digest/fde",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertFalse(response.get_json()["delivery_configured"])
        run_digest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
