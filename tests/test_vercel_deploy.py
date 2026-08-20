import json
import tempfile
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

    def test_github_actions_scheduler_tick_is_manual_fallback_only(self):
        workflow = Path(".github/workflows/digest.yml").read_text(encoding="utf-8")

        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("cron:", workflow)
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

    def test_scheduled_news_profile_passes_scheduled_time_to_digest(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import DIGEST_PROFILES, _run_digest_profile

        scheduled = datetime(2026, 8, 24, 9, 15, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        settings = Settings(
            telegram_bot_token="token",
            telegram_chat_id="-100123",
        )
        with (
            patch("news_keep_up.vercel_app._settings_for_profile", return_value=settings),
            patch("news_keep_up.vercel_app.run_digest", return_value="digest") as run_digest,
        ):
            _run_digest_profile(
                DIGEST_PROFILES["engineer"],
                dry_run=False,
                current=scheduled,
            )

        self.assertEqual(run_digest.call_args.kwargs["current"], scheduled)

    def test_scheduled_interview_profile_passes_scheduled_time_to_guideline(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import DIGEST_PROFILES, _run_digest_profile

        scheduled = datetime(2026, 8, 24, 9, 15, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        settings = Settings(
            telegram_bot_token="token",
            telegram_chat_id="-100123",
        )
        with (
            patch("news_keep_up.vercel_app._settings_for_profile", return_value=settings),
            patch(
                "news_keep_up.vercel_app.run_fde_interview_guideline",
                return_value="guide",
            ) as run_guideline,
        ):
            _run_digest_profile(
                DIGEST_PROFILES["fde-interview"],
                dry_run=False,
                current=scheduled,
            )

        self.assertEqual(run_guideline.call_args.kwargs["current"], scheduled)

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

    def test_fde_jobs_endpoint_uses_job_alert_flow_and_fde_env_prefix(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "FDE_TELEGRAM_BOT_TOKEN": "token",
                "FDE_TELEGRAM_CHAT_ID": "-100123",
                "FDE_JOBS_TELEGRAM_CHAT_ID": "-100999",
            }, clear=False),
            patch(
                "news_keep_up.vercel_app.load_settings",
                return_value=Settings(telegram_bot_token="token", telegram_chat_id="-100123"),
            ) as load_settings,
            patch("news_keep_up.vercel_app.run_fde_job_alerts", return_value="job alert") as run_jobs,
            patch("news_keep_up.vercel_app.run_digest") as run_digest,
        ):
            response = app.test_client().get(
                "/api/digest/fde-jobs",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slot"], "fde-jobs")
        load_settings.assert_called_once_with(env_prefix="FDE")
        run_jobs.assert_called_once()
        self.assertEqual(run_jobs.call_args.args[0].telegram_chat_id, "-100999")
        self.assertEqual(run_jobs.call_args.args[0].telegram_bot_token, "token")
        self.assertEqual(run_jobs.call_args.kwargs["sources_path"], "config/fde_job_sources.json")
        run_digest.assert_not_called()

    def test_fde_jobs_endpoint_passes_force_query_to_job_alert_flow(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "TELEGRAM_BOT_TOKEN": "token",
                "FDE_JOBS_TELEGRAM_CHAT_ID": "-100999",
            }, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings()),
            patch("news_keep_up.vercel_app.run_fde_job_alerts", return_value="job alert") as run_jobs,
        ):
            response = app.test_client().get(
                "/api/digest/fde-jobs?force=true",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(run_jobs.call_args.kwargs["force"])

    def test_fde_job_sources_endpoint_runs_without_telegram_delivery(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings()),
            patch(
                "news_keep_up.vercel_app.run_fde_job_source_intelligence",
                return_value="source intelligence",
            ) as run_sources,
        ):
            response = app.test_client().get(
                "/api/digest/fde-job-sources",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slot"], "fde-job-sources")
        self.assertFalse(response.get_json()["delivery_configured"])
        run_sources.assert_called_once()
        self.assertEqual(
            run_sources.call_args.kwargs["discovery_sources_path"],
            "config/fde_job_source_discovery_sources.json",
        )

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

    def test_fde_jobs_endpoint_runs_storage_flow_when_telegram_chat_is_missing(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings()),
            patch("news_keep_up.vercel_app.run_fde_job_alerts", return_value="") as run_jobs,
        ):
            response = app.test_client().get(
                "/api/digest/fde-jobs",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertFalse(response.get_json()["delivery_configured"])
        run_jobs.assert_called_once()

    def test_fde_jobs_endpoint_requires_jobs_chat_override_not_fde_chat(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "FDE_TELEGRAM_BOT_TOKEN": "token",
                "FDE_TELEGRAM_CHAT_ID": "-100123",
            }, clear=False),
            patch(
                "news_keep_up.vercel_app.load_settings",
                return_value=Settings(telegram_bot_token="token", telegram_chat_id="-100123"),
            ),
            patch("news_keep_up.vercel_app.run_fde_job_alerts", return_value="") as run_jobs,
        ):
            response = app.test_client().get(
                "/api/digest/fde-jobs",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["delivery_configured"])
        run_jobs.assert_called_once()
        self.assertEqual(run_jobs.call_args.args[0].telegram_chat_id, "")
        self.assertEqual(run_jobs.call_args.args[0].telegram_bot_token, "token")

    def test_fde_jobs_endpoint_can_reuse_global_bot_token_with_jobs_chat(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "TELEGRAM_BOT_TOKEN": "global-token",
                "FDE_JOBS_TELEGRAM_CHAT_ID": "-100999",
            }, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings()),
            patch("news_keep_up.vercel_app.run_fde_job_alerts", return_value="job alert") as run_jobs,
        ):
            response = app.test_client().get(
                "/api/digest/fde-jobs",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["delivery_configured"])
        run_jobs.assert_called_once()
        self.assertEqual(run_jobs.call_args.args[0].telegram_chat_id, "-100999")
        self.assertEqual(run_jobs.call_args.args[0].telegram_bot_token, "global-token")

    def test_fde_jobs_endpoint_uses_stored_jobs_chat_id_when_env_is_missing(self):
        from news_keep_up.db import connect_database, init_db, upsert_profile_setting
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            settings = Settings(db_path=db_path)
            conn = connect_database(settings)
            init_db(conn)
            upsert_profile_setting(conn, "fde-jobs", "telegram_chat_id", "-100777")
            conn.close()

            with (
                patch.dict("os.environ", {
                    "CRON_SECRET": "test-secret",
                    "TELEGRAM_BOT_TOKEN": "global-token",
                    "FDE_JOBS_TELEGRAM_CHAT_ID": "",
                    "DB_PATH": str(db_path),
                    "TURSO_DATABASE_URL": "",
                    "TURSO_AUTH_TOKEN": "",
                }, clear=False),
                patch("news_keep_up.vercel_app.run_fde_job_alerts", return_value="job alert") as run_jobs,
            ):
                response = app.test_client().get(
                    "/api/digest/fde-jobs",
                    headers={"Authorization": "Bearer test-secret"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["delivery_configured"])
        self.assertEqual(run_jobs.call_args.args[0].telegram_chat_id, "-100777")
        self.assertEqual(run_jobs.call_args.args[0].telegram_bot_token, "global-token")

    def test_telegram_webhook_requires_secret_header(self):
        from news_keep_up.vercel_app import app

        with patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False):
            response = app.test_client().post(
                "/api/telegram/fde",
                json={"update_id": 1},
            )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_callback_webhook_requires_secret_before_dispatch(self):
        from news_keep_up.vercel_app import app

        callback_update = {
            "update_id": 1,
            "callback_query": {
                "id": "cb-1",
                "from": {"id": 42},
                "data": "i1|1|u",
                "message": {"message_id": 700, "chat": {"id": -100123}},
            },
        }
        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.handle_telegram_update") as handler,
        ):
            response = app.test_client().post(
                "/api/telegram/fde",
                json=callback_update,
            )

        self.assertEqual(response.status_code, 401)
        handler.assert_not_called()

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

    def test_fde_jobs_telegram_webhook_reuses_global_bot_token(self):
        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        with (
            patch.dict("os.environ", {
                "CRON_SECRET": "test-secret",
                "TELEGRAM_BOT_TOKEN": "global-token",
            }, clear=False),
            patch("news_keep_up.vercel_app.load_settings", return_value=Settings()),
            patch("news_keep_up.vercel_app.handle_telegram_update", return_value={"ok": True, "command": "chatid"}) as handler,
        ):
            response = app.test_client().post(
                "/api/telegram/fde-jobs",
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
                json={"update_id": 1},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(handler.call_args.kwargs["slot"], "fde-jobs")
        self.assertEqual(handler.call_args.kwargs["sources_path"], "config/fde_job_sources.json")
        self.assertEqual(handler.call_args.kwargs["settings"].telegram_bot_token, "global-token")

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

    def test_scheduler_tick_passes_scheduled_time_to_job_alert_profile(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from news_keep_up.scheduler import ScheduledDigestJob
        from news_keep_up.vercel_app import app

        scheduled_for = datetime(2026, 7, 14, 20, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        triggered_at = datetime(2026, 7, 14, 21, 31, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        job = ScheduledDigestJob(slot="fde-jobs", scheduled_for=scheduled_for)
        with (
            patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
            patch("news_keep_up.vercel_app.now_ict", return_value=triggered_at),
            patch("news_keep_up.vercel_app.load_settings"),
            patch("news_keep_up.vercel_app.connect_database") as connect,
            patch("news_keep_up.vercel_app.init_db"),
            patch("news_keep_up.vercel_app.due_digest_jobs", return_value=[job]),
            patch("news_keep_up.vercel_app.claim_scheduler_run", return_value=True),
            patch("news_keep_up.vercel_app.finish_scheduler_run"),
            patch("news_keep_up.vercel_app._run_digest_profile", return_value={
                "delivery_configured": True,
                "message_length": 123,
            }) as run_profile,
        ):
            response = app.test_client().get(
                "/api/scheduler/tick",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_profile.call_args.kwargs["current"], scheduled_for)
        self.assertEqual(run_profile.call_args.kwargs["send_window_current"], triggered_at)
        connect.return_value.close.assert_called_once()

    def test_scheduler_tick_catches_daily_source_maintenance_after_delayed_start(self):
        from datetime import datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from zoneinfo import ZoneInfo

        from news_keep_up.models import Settings
        from news_keep_up.vercel_app import app

        current = datetime(2026, 8, 4, 9, 5, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        with TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db")
            with (
                patch.dict("os.environ", {"CRON_SECRET": "test-secret"}, clear=False),
                patch("news_keep_up.vercel_app.now_ict", return_value=current),
                patch("news_keep_up.vercel_app.load_settings", return_value=settings),
                patch("news_keep_up.vercel_app._run_digest_profile", return_value={
                    "delivery_configured": True,
                    "message_length": 0,
                }),
            ):
                response = app.test_client().get(
                    "/api/scheduler/tick",
                    headers={"Authorization": "Bearer test-secret"},
                )

        self.assertEqual(response.status_code, 200)
        slots = [result["slot"] for result in response.get_json()["results"]]
        self.assertIn("fde-job-sources", slots)


if __name__ == "__main__":
    unittest.main()
