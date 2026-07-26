import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_keep_up.job_alerts import is_fde_job_candidate, run_fde_job_alerts
from news_keep_up.models import CandidateItem, JobOpportunity, Settings


def make_job_candidate() -> CandidateItem:
    return CandidateItem(
        source_name="Bing FDE Vietnam",
        source_kind="rss",
        source_category="fde-job-search",
        title="Wonderful is hiring a Forward Deployed Engineer in Vietnam",
        url="https://example.com/jobs/wonderful-fde",
        canonical_url="https://example.com/jobs/wonderful-fde",
        summary="Official listing says Vietnam remote candidates can apply for enterprise AI deployment work.",
        published_at="2026-07-27T03:00:00+00:00",
        fetched_at="2026-07-27T03:01:00+07:00",
        fingerprint="job-fp-1",
        raw={"source_type": "aggregator"},
    )


def make_opportunity(source_item_id: int) -> JobOpportunity:
    return JobOpportunity(
        id="wonderful-forward-deployed-engineer-vietnam",
        source_item_id=source_item_id,
        source_fingerprint="job-fp-1",
        crawled_at="2026-07-27",
        priority="Medium",
        company="Wonderful",
        role_title="Forward Deployed Engineer",
        category="Exact FDE Role",
        location="Vietnam",
        remote_policy="Remote Vietnam",
        vietnam_eligibility="explicit_yes",
        evidence_type="Hard",
        status="open",
        posted_date="",
        source_type="ATS",
        source_url="https://example.com/jobs/wonderful-fde",
        apply_url="https://example.com/jobs/wonderful-fde/apply",
        contact_person="",
        contact_url="",
        why_it_fits="Exact FDE role with Vietnam eligibility and enterprise AI deployment work.",
        what_to_verify=["Compensation range"],
        required_seniority="Senior",
        required_skills=["LLM", "customer deployment"],
        domain=["enterprise AI"],
        recommended_action="apply_now",
        outreach_angle="Lead with Vietnam-based enterprise AI deployment experience.",
        confidence_score=82,
        should_alert=True,
    )


class JobAlertsTest(unittest.TestCase):
    def test_prefilter_accepts_fde_job_candidate(self):
        self.assertTrue(is_fde_job_candidate(make_job_candidate()))

    def test_run_fde_job_alerts_sends_high_medium_once_per_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_path = Path(tmp) / "sources.json"
            sources_path.write_text(json.dumps([
                {
                    "name": "Bing FDE Vietnam",
                    "type": "rss",
                    "url": "https://example.com/feed.xml",
                    "category": "fde-job-search",
                    "source_type": "aggregator",
                    "enabled": True,
                }
            ]), encoding="utf-8")
            settings = Settings(
                telegram_bot_token="token",
                telegram_chat_id="-100123",
                db_path=Path(tmp) / "test.db",
            )
            candidate = make_job_candidate()

            def classify(_, candidates, crawled_at):
                source_item_id, _candidate = candidates[0]
                return [make_opportunity(source_item_id)]

            with (
                patch("news_keep_up.job_alerts.fetch_source", return_value=[candidate]),
                patch("news_keep_up.job_alerts.GeminiClient.classify_job_candidates", classify),
                patch("news_keep_up.job_alerts.send_telegram_message") as send,
            ):
                first_message = run_fde_job_alerts(settings, sources_path=sources_path)
                second_message = run_fde_job_alerts(settings, sources_path=sources_path)

            self.assertIn("FDE Job Alert", first_message)
            self.assertIn("Wonderful", first_message)
            self.assertEqual(second_message, "")
            self.assertEqual(send.call_count, 1)

    def test_run_fde_job_alerts_sends_pending_alert_after_telegram_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_path = Path(tmp) / "sources.json"
            sources_path.write_text(json.dumps([
                {
                    "name": "Bing FDE Vietnam",
                    "type": "rss",
                    "url": "https://example.com/feed.xml",
                    "category": "fde-job-search",
                    "source_type": "aggregator",
                    "enabled": True,
                }
            ]), encoding="utf-8")
            settings = Settings(db_path=Path(tmp) / "test.db")
            candidate = make_job_candidate()

            def classify(_, candidates, crawled_at):
                source_item_id, _candidate = candidates[0]
                return [make_opportunity(source_item_id)]

            with (
                patch("news_keep_up.job_alerts.fetch_source", return_value=[candidate]),
                patch("news_keep_up.job_alerts.GeminiClient.classify_job_candidates", classify),
                patch("news_keep_up.job_alerts.send_telegram_message") as send,
            ):
                first_message = run_fde_job_alerts(settings, sources_path=sources_path)
                configured = Settings(
                    telegram_bot_token="token",
                    telegram_chat_id="-100123",
                    db_path=settings.db_path,
                )
                second_message = run_fde_job_alerts(configured, sources_path=sources_path)

            self.assertEqual(first_message, "")
            self.assertIn("FDE Job Alert", second_message)
            self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
