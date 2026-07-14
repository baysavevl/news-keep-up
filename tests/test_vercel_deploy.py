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

    def test_github_actions_triggers_fallback_scheduler_tick_from_7_to_22_ict(self):
        workflow = Path(".github/workflows/digest.yml").read_text(encoding="utf-8")

        self.assertIn('cron: "8,23,38,53 0-15 * * *"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("concurrency:", workflow)
        self.assertIn("https://news-keep-up.vercel.app/api/scheduler/tick", workflow)
        self.assertNotIn("/api/digest/fde\"", workflow)
        self.assertNotIn("/api/digest/engineer", workflow)
        self.assertIn("secrets.CRON_SECRET", workflow)


class VercelDigestEndpointTest(unittest.TestCase):
    def test_favicon_routes_return_project_icon_svg(self):
        from news_keep_up.vercel_app import app

        client = app.test_client()
        for path in ("/favicon.svg", "/favicon.ico"):
            response = client.get(path)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/svg+xml")
            self.assertIn("public, max-age=86400", response.headers["Cache-Control"])
            self.assertIn("news-keep-up favicon", response.get_data(as_text=True))

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

    def test_fde_interview_endpoint_uses_guideline_flow_and_fde_env_prefix(self):
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "FDE_TELEGRAM_BOT_TOKEN": "token",
                "FDE_TELEGRAM_CHAT_ID": "-100123",
            }, clear=False),
            patch("news_keep_up.vercel_app.load_settings") as load_settings,
            patch("news_keep_up.vercel_app.run_fde_interview_guideline", return_value="guide text") as run_guideline,
            patch("news_keep_up.vercel_app.run_digest") as run_digest,
        ):
            response = app.test_client().get(
                "/api/digest/fde-interview",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slot"], "fde-interview")
        load_settings.assert_called_once_with(env_prefix="FDE")
        run_guideline.assert_called_once()
        run_digest.assert_not_called()

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

    def test_telegram_webhook_requires_secret_header(self):
        from news_keep_up.vercel_app import app

        with patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False):
            response = app.test_client().post(
                "/api/telegram/fde",
                json={"update_id": 1},
            )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_telegram_webhook_dispatches_profile_command(self):
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings") as load_settings,
            patch("news_keep_up.vercel_app.handle_telegram_update", return_value={"ok": True, "command": "help"}) as handler,
        ):
            response = app.test_client().post(
                "/api/telegram/fde",
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
                json={"update_id": 1},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        load_settings.assert_called_once_with(env_prefix="FDE")
        self.assertEqual(handler.call_args.kwargs["slot"], "fde")
        self.assertEqual(handler.call_args.kwargs["sources_path"], "config/fde_sources.json")

    def test_avatar_admin_endpoint_requires_cron_secret(self):
        from news_keep_up.vercel_app import app

        with patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False):
            response = app.test_client().post("/api/admin/avatar/fde")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_avatar_admin_endpoint_updates_profile_chat_photo(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings(
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )) as load_settings,
            patch("news_keep_up.vercel_app.set_telegram_chat_photo") as set_photo,
        ):
            response = app.test_client().post(
                "/api/admin/avatar/fde",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        load_settings.assert_called_once_with(env_prefix="FDE")
        self.assertIn("fde-avatar.png", str(set_photo.call_args.args[1]))

    def test_mark_delivered_admin_endpoint_marks_stored_items(self):
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings"),
            patch("news_keep_up.vercel_app.connect_database") as connect,
            patch("news_keep_up.vercel_app.init_db") as init,
            patch("news_keep_up.vercel_app._undelivered_item_ids", return_value=[1, 2, 3]),
            patch("news_keep_up.vercel_app.mark_delivered") as mark,
        ):
            conn = connect.return_value
            response = app.test_client().post(
                "/api/admin/mark-delivered/engineer",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["marked"], 3)
        init.assert_called_once_with(conn)
        mark.assert_called_once_with(conn, [1, 2, 3], "engineer", set())
        conn.close.assert_called_once()

    def test_scheduler_tick_runs_one_due_digest_profile(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from news_keep_up.scheduler import ScheduledDigestJob
        from news_keep_up.vercel_app import app

        job = ScheduledDigestJob(
            slot="fde",
            scheduled_for=datetime(2026, 7, 14, 10, 20, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
        )
        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings"),
            patch("news_keep_up.vercel_app.connect_database") as connect,
            patch("news_keep_up.vercel_app.init_db") as init,
            patch("news_keep_up.vercel_app.due_digest_jobs", return_value=[job]),
            patch("news_keep_up.vercel_app.claim_scheduler_run", return_value=True) as claim,
            patch("news_keep_up.vercel_app.finish_scheduler_run") as finish,
            patch("news_keep_up.vercel_app._run_digest_profile", return_value={
                "delivery_configured": True,
                "message_length": 123,
            }) as run_profile,
        ):
            conn = connect.return_value
            response = app.test_client().get(
                "/api/scheduler/tick",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["triggered"], 1)
        self.assertEqual(payload["results"][0]["slot"], "fde")
        init.assert_called_once_with(conn)
        claim.assert_called_once()
        run_profile.assert_called_once()
        finish.assert_called_once()
        self.assertEqual(finish.call_args.args[3], "done")
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
