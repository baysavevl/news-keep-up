import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_keep_up.db import (
    connect_database,
    get_profile_setting,
    init_db,
    record_source_fetch_log,
    upsert_enrichment,
    upsert_item,
    upsert_job_opportunity,
)
from news_keep_up.models import CandidateItem, Enrichment, JobOpportunity, Settings, SourceFetchLog
from news_keep_up.telegram_commands import handle_telegram_update


def update(text: str, chat_id: int = -100123, message_id: int = 42, title: str = "") -> dict:
    chat = {"id": chat_id, "type": "supergroup"}
    if title:
        chat["title"] = title
    return {
        "update_id": 1,
        "message": {
            "message_id": message_id,
            "chat": chat,
            "text": text,
        },
    }


class TelegramCommandsTest(unittest.TestCase):
    def test_help_command_lists_interactive_news_commands(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
            result = handle_telegram_update(
                update("/help"),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        self.assertTrue(result["ok"])
        sent_text = send.call_args.args[0]
        self.assertIn("/latest", sent_text)
        self.assertIn("/search", sent_text)
        self.assertIn("/analyze", sent_text)
        self.assertIn("/focus", sent_text)
        self.assertEqual(send.call_args.kwargs["chat_id"], "-100123")
        self.assertEqual(send.call_args.kwargs["reply_to_message_id"], 42)

    def test_latest_command_runs_profile_digest_as_preview(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with (
            patch("news_keep_up.telegram_commands.run_digest", return_value="<b>Digest</b>") as run_digest,
            patch("news_keep_up.telegram_commands.send_telegram_message") as send,
        ):
            handle_telegram_update(
                update("/latest@ForwardDeployEngineerBot"),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        self.assertEqual(run_digest.call_args.args[1], "fde")
        self.assertEqual(run_digest.call_args.kwargs["sources_path"], "config/fde_sources.json")
        self.assertTrue(run_digest.call_args.kwargs["dry_run"])
        self.assertEqual(send.call_args.args[0], "<b>Digest</b>")

    def test_fde_jobs_latest_command_runs_job_alert_preview(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with (
            patch("news_keep_up.telegram_commands.run_fde_job_alerts", return_value="<b>Job Alert</b>") as run_jobs,
            patch("news_keep_up.telegram_commands.run_digest") as run_digest,
            patch("news_keep_up.telegram_commands.send_telegram_message") as send,
        ):
            handle_telegram_update(
                update("/latest"),
                slot="fde-jobs",
                sources_path="config/fde_job_sources.json",
                settings=settings,
            )

        run_jobs.assert_called_once()
        self.assertTrue(run_jobs.call_args.kwargs["dry_run"])
        self.assertEqual(run_jobs.call_args.kwargs["sources_path"], "config/fde_job_sources.json")
        run_digest.assert_not_called()
        self.assertEqual(send.call_args.args[0], "<b>Job Alert</b>")

    def test_fde_focus_command_explains_fde_relevance(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
            handle_telegram_update(
                update("/focus"),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        sent_text = send.call_args.args[0].lower()
        self.assertIn("forward deployed", sent_text)
        self.assertIn("customer rollout", sent_text)
        self.assertIn("enterprise implementation", sent_text)
        self.assertIn("generic ai", sent_text)

    def test_status_command_reports_updated_fde_schedule(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
            handle_telegram_update(
                update("/status"),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        sent_text = send.call_args.args[0]
        self.assertIn("twice daily at 08:00 and 14:00", sent_text)

    def test_sources_command_reports_recent_failing_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )
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

            with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
                handle_telegram_update(
                    update("/sources"),
                    slot="fde-jobs",
                    sources_path="config/fde_job_sources.json",
                    settings=settings,
                )

        sent_text = send.call_args.args[0]
        self.assertIn("Problem sources", sent_text)
        self.assertIn("Blocked Upwork", sent_text)
        self.assertIn("failed=1", sent_text)

    def test_fde_jobs_force_command_sends_alert_run_and_replies_summary(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with (
            patch(
                "news_keep_up.telegram_commands.run_fde_job_alerts",
                return_value="<b>FDE Job Alert</b>\n<b>Forward Deployed Engineer</b>",
            ) as run_jobs,
            patch("news_keep_up.telegram_commands.send_telegram_message") as send,
        ):
            result = handle_telegram_update(
                update("/force"),
                slot="fde-jobs",
                sources_path="config/fde_job_sources.json",
                settings=settings,
            )

        self.assertEqual(result["command"], "force")
        self.assertFalse(run_jobs.call_args.kwargs["dry_run"])
        self.assertTrue(run_jobs.call_args.kwargs["force"])
        self.assertIn("Force run complete", send.call_args.args[0])
        self.assertIn("sent 1 alert", send.call_args.args[0])

    def test_search_command_returns_recent_stored_news(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Salesforce Engineering",
                source_kind="rss",
                source_category="field-engineering",
                title="Building enterprise AI agents for customer rollout",
                url="https://example.com/agent",
                canonical_url="https://example.com/agent",
                summary="Customer-facing deployment teams use evals and guardrails.",
            ))
            upsert_enrichment(conn, item_id, Enrichment(
                model="gemini-test",
                relevance_score=91,
                category="field-engineering",
                topic="enterprise-rollout",
                icon="🧭",
                title_vi="",
                summary="Key idea.",
                why_it_matters="Impact.",
                takeaway_vi="Takeaway.",
                should_send=True,
            ))

            with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
                handle_telegram_update(
                    update("/search rollout"),
                    slot="fde",
                    sources_path="config/fde_sources.json",
                    settings=settings,
                )

        sent_text = send.call_args.args[0]
        self.assertIn("Search: rollout", sent_text)
        self.assertIn("#", sent_text)
        self.assertIn("Building enterprise AI agents", sent_text)
        self.assertIn("Salesforce Engineering", sent_text)

    def test_fde_jobs_job_search_command_returns_stored_opportunities(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Wonderful Careers",
                source_kind="html",
                source_category="company-careers",
                title="Wonderful Forward Deployed Engineer",
                url="https://wonderful.ai/jobs/fde",
                canonical_url="https://wonderful.ai/jobs/fde",
                summary="Remote Vietnam enterprise AI deployment role.",
            ))
            upsert_job_opportunity(conn, JobOpportunity(
                id="wonderful-forward-deployed-engineer-vietnam",
                source_item_id=item_id,
                source_fingerprint="job-fp",
                crawled_at="2026-07-27",
                priority="High",
                company="Wonderful",
                role_title="Forward Deployed Engineer",
                category="Exact FDE Role",
                location="Ho Chi Minh City, Vietnam",
                remote_policy="Hybrid HCMC",
                vietnam_eligibility="explicit_yes",
                evidence_type="Hard",
                status="open",
                posted_date="",
                source_type="ATS",
                source_url="https://wonderful.ai/jobs/fde",
                apply_url="https://wonderful.ai/jobs/fde/apply",
                contact_person="",
                contact_url="",
                why_it_fits="Exact FDE role in Vietnam for enterprise AI deployment.",
                what_to_verify=["Compensation range"],
                required_seniority="",
                required_skills=["LLM", "customer deployment"],
                domain=["enterprise AI"],
                country="Vietnam",
                compensation="Competitive salary",
                benefits="Health insurance",
                package="Base + equity",
                company_size="51-200 employees",
                company_coverage="Vietnam and US customers",
                recommended_action="apply_now",
                confidence_score=94,
                should_alert=True,
            ))
            conn.close()

            with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
                result = handle_telegram_update(
                    update("/jobs wonderful"),
                    slot="fde-jobs",
                    sources_path="config/fde_job_sources.json",
                    settings=settings,
                )

        self.assertEqual(result["command"], "jobsearch")
        sent_text = send.call_args.args[0]
        self.assertIn("<b>FDE job search: wonderful</b>", sent_text)
        self.assertIn("Forward Deployed Engineer", sent_text)
        self.assertIn("🏢 Wonderful", sent_text)
        self.assertIn("📍 Ho Chi Minh City, Vietnam", sent_text)
        self.assertIn("💰 Competitive salary", sent_text)
        self.assertIn("🏬 51-200 employees", sent_text)
        self.assertIn("🔗", sent_text)

    def test_fde_jobs_salary_command_returns_compensated_opportunities(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Wonderful Careers",
                source_kind="html",
                source_category="company-careers",
                title="Wonderful Forward Deployed Engineer",
                url="https://wonderful.ai/jobs/fde",
                canonical_url="https://wonderful.ai/jobs/fde",
                summary="Remote Vietnam enterprise AI deployment role.",
            ))
            base = {
                "source_item_id": item_id,
                "source_fingerprint": "job-fp",
                "crawled_at": "2026-07-27",
                "priority": "High",
                "category": "Exact FDE Role",
                "location": "Vietnam",
                "remote_policy": "Remote Vietnam",
                "vietnam_eligibility": "explicit_yes",
                "evidence_type": "Hard",
                "status": "open",
                "posted_date": "",
                "source_type": "ATS",
                "contact_person": "",
                "contact_url": "",
                "why_it_fits": "Exact FDE role in Vietnam.",
                "what_to_verify": [],
                "required_seniority": "",
                "required_skills": [],
                "domain": [],
                "country": "Vietnam",
                "recommended_action": "apply_now",
                "confidence_score": 90,
                "should_alert": True,
            }
            upsert_job_opportunity(conn, JobOpportunity(
                **base,
                id="wonderful-paid-fde",
                company="Wonderful",
                role_title="Forward Deployed Engineer",
                source_url="https://wonderful.ai/jobs/fde",
                apply_url="https://wonderful.ai/jobs/fde/apply",
                compensation="$120k-$160k",
                package="Base + equity",
            ))
            upsert_job_opportunity(conn, JobOpportunity(
                **base,
                id="unknown-pay-fde",
                company="UnknownPay",
                role_title="Forward Deployed Engineer",
                source_url="https://example.com/no-pay",
                apply_url="https://example.com/no-pay",
            ))
            conn.close()

            with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
                result = handle_telegram_update(
                    update("/salary"),
                    slot="fde-jobs",
                    sources_path="config/fde_job_sources.json",
                    settings=settings,
                )

        self.assertEqual(result["command"], "salarysearch")
        sent_text = send.call_args.args[0]
        self.assertIn("FDE job search: salary/package", sent_text)
        self.assertIn("$120k-$160k", sent_text)
        self.assertNotIn("UnknownPay", sent_text)

    def test_markread_command_marks_matching_items_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Salesforce Engineering",
                source_kind="rss",
                source_category="field-engineering",
                title="Enterprise AI rollout with eval guardrails",
                url="https://example.com/rollout",
                canonical_url="https://example.com/rollout",
                summary="Customer-facing deployment teams use evals and guardrails.",
            ))
            upsert_enrichment(conn, item_id, Enrichment(
                model="gemini-test",
                relevance_score=91,
                category="field-engineering",
                topic="enterprise-rollout",
                icon="🧭",
                title_vi="",
                summary="Key idea.",
                why_it_matters="Impact.",
                takeaway_vi="Takeaway.",
                should_send=True,
            ))

            with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
                result = handle_telegram_update(
                    update("/markread rollout"),
                    slot="fde",
                    sources_path="config/fde_sources.json",
                    settings=settings,
                )

            row = conn.execute("SELECT slot FROM deliveries WHERE item_id=?", (item_id,)).fetchone()

        self.assertEqual(result["command"], "markread")
        self.assertEqual(row["slot"], "fde")
        self.assertIn("Marked read: 1", send.call_args.args[0])

    def test_interview_command_returns_fde_guideline_preview(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with (
            patch("news_keep_up.telegram_commands.run_fde_interview_guideline", return_value="<b>FDE Interview</b>") as run,
            patch("news_keep_up.telegram_commands.send_telegram_message") as send,
        ):
            result = handle_telegram_update(
                update("/interview"),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        self.assertEqual(result["command"], "interview")
        self.assertTrue(run.call_args.kwargs["dry_run"])
        self.assertEqual(send.call_args.args[0], "<b>FDE Interview</b>")

    def test_unauthorized_chat_is_ignored(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
            result = handle_telegram_update(
                update("/help", chat_id=-999),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["ignored"])
        send.assert_not_called()

    def test_chatid_command_responds_even_when_chat_is_not_authorized_yet(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="-100123")

        with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
            result = handle_telegram_update(
                update("/chatid", chat_id=-100999),
                slot="fde",
                sources_path="config/fde_sources.json",
                settings=settings,
            )

        self.assertEqual(result["command"], "chatid")
        self.assertIn("-100999", send.call_args.args[0])
        self.assertEqual(send.call_args.kwargs["chat_id"], "-100999")

    def test_fde_jobs_chatid_command_saves_expected_group_chat_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="",
            )

            with patch("news_keep_up.telegram_commands.send_telegram_message") as send:
                result = handle_telegram_update(
                    update("/chatid", chat_id=-100999, title="FDE jobs"),
                    slot="fde-jobs",
                    sources_path="config/fde_job_sources.json",
                    settings=settings,
                )

            conn = connect_database(settings)
            init_db(conn)
            stored = get_profile_setting(conn, "fde-jobs", "telegram_chat_id")
            conn.close()

        self.assertEqual(result["command"], "chatid")
        self.assertEqual(stored, "-100999")
        self.assertIn("Saved for fde-jobs delivery.", send.call_args.args[0])

    def test_fde_jobs_chatid_command_does_not_save_unexpected_group_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="",
            )

            with patch("news_keep_up.telegram_commands.send_telegram_message"):
                handle_telegram_update(
                    update("/chatid", chat_id=-100999, title="Random group"),
                    slot="fde-jobs",
                    sources_path="config/fde_job_sources.json",
                    settings=settings,
                )

            conn = connect_database(settings)
            init_db(conn)
            stored = get_profile_setting(conn, "fde-jobs", "telegram_chat_id")
            conn.close()

        self.assertEqual(stored, "")


if __name__ == "__main__":
    unittest.main()
