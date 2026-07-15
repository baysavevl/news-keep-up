import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_keep_up.db import connect_database, init_db, upsert_enrichment, upsert_item
from news_keep_up.models import CandidateItem, Enrichment, Settings
from news_keep_up.telegram_commands import handle_telegram_update


def update(text: str, chat_id: int = -100123, message_id: int = 42) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id, "type": "supergroup"},
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
        self.assertIn("every 2 hours at :20", sent_text)

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


if __name__ == "__main__":
    unittest.main()
