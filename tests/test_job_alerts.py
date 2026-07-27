import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_keep_up.db import connect_database, init_db
from news_keep_up.job_alerts import (
    _candidate_matches_source_filters,
    _new_job_candidates,
    format_job_alert,
    is_fde_job_candidate,
    is_workable_from_vietnam_candidate,
    is_workable_from_vietnam_opportunity,
    run_fde_job_alerts,
)
from news_keep_up.models import CandidateItem, JobOpportunity, Settings, Source


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

    def test_format_job_alert_is_concise_with_analysis_location_and_link(self):
        message = format_job_alert(make_opportunity(1))

        self.assertIn("<b>Forward Deployed Engineer</b>", message)
        self.assertIn("Wonderful · Vietnam · Remote Vietnam", message)
        self.assertIn("Phân tích:", message)
        self.assertIn("Verify:", message)
        self.assertIn("Link:", message)
        self.assertNotIn("Role/Signal:", message)

    def test_prefilter_rejects_source_name_only_search_noise(self):
        candidate = CandidateItem(
            source_name="Bing FDE Vietnam",
            source_kind="rss",
            source_category="fde-job-search",
            title="FORWARD中文 (繁體)翻譯：劍橋詞典 - Cambridge Dictionary",
            url="https://dictionary.cambridge.org/zht/dictionary/english/forward",
            canonical_url="https://dictionary.cambridge.org/zht/dictionary/english/forward",
            summary="Translation and dictionary entry for the word forward.",
            raw={"source_type": "aggregator"},
        )

        self.assertFalse(is_fde_job_candidate(candidate))

    def test_source_filters_require_configured_url_match(self):
        source = Source(
            "Bing Upwork FDE AI Deployment",
            "rss",
            "https://www.bing.com/search?q=site%3Aupwork.com%2Ffreelance-jobs",
            "freelance-job-search",
            metadata={"url_include_any": ["upwork.com/freelance-jobs"]},
        )
        matching = CandidateItem(
            source_name=source.name,
            source_kind=source.kind,
            source_category=source.category,
            title="AI Deployment Engineer for RAG workflow",
            url="https://www.upwork.com/freelance-jobs/apply/ai-deployment-engineer",
            canonical_url="https://www.upwork.com/freelance-jobs/apply/ai-deployment-engineer",
            summary="Remote project implementing OpenAI and LangChain for production workflow automation.",
        )
        non_matching = CandidateItem(
            source_name=source.name,
            source_kind=source.kind,
            source_category=source.category,
            title="AI Deployment Engineer for RAG workflow",
            url="https://example.com/jobs/ai-deployment-engineer",
            canonical_url="https://example.com/jobs/ai-deployment-engineer",
            summary="Remote project implementing OpenAI and LangChain for production workflow automation.",
        )

        self.assertTrue(_candidate_matches_source_filters(source, matching))
        self.assertFalse(_candidate_matches_source_filters(source, non_matching))

    def test_vietnam_workability_filter_rejects_onsite_india_and_remote_us(self):
        onsite_india = CandidateItem(
            source_name="FWDDeploy All Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Senior Forward Deployed Engineer",
            url="https://www.fwddeploy.com/jobs/senior-forward-deployed-engineer",
            canonical_url="https://www.fwddeploy.com/jobs/senior-forward-deployed-engineer",
            summary="Company: Handshake. Location: On-site Bengaluru, Karnataka, India. Employment: Full-time.",
            raw={"company": "Handshake", "location": "On-site Bengaluru, Karnataka, India"},
        )
        remote_us = CandidateItem(
            source_name="FWDDeploy Remote Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Forward Deployed Engineer",
            url="https://www.fwddeploy.com/jobs/us-fde",
            canonical_url="https://www.fwddeploy.com/jobs/us-fde",
            summary="Company: Example. Location: Remote United States. Employment: Full-time.",
            raw={"company": "Example", "location": "Remote United States", "remote_policy": "Remote"},
        )

        self.assertFalse(is_workable_from_vietnam_candidate(onsite_india))
        self.assertFalse(is_workable_from_vietnam_candidate(remote_us))

    def test_vietnam_workability_filter_accepts_vietnam_and_remote_apac(self):
        vietnam = CandidateItem(
            source_name="Wonderful Careers",
            source_kind="html",
            source_category="company-careers",
            title="Forward Deployed Engineer",
            url="https://www.wonderful.ai/careers",
            canonical_url="https://www.wonderful.ai/careers",
            summary="Location: Ho Chi Minh City, Vietnam. Employment: Full-time.",
            raw={"company": "Wonderful", "location": "Ho Chi Minh City, Vietnam"},
        )
        remote_apac = CandidateItem(
            source_name="FWDDeploy Remote Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Forward Deployed Engineer - APAC",
            url="https://www.fwddeploy.com/jobs/apac-fde",
            canonical_url="https://www.fwddeploy.com/jobs/apac-fde",
            summary="Location: Remote APAC. Employment: Full-time.",
            raw={"company": "Example", "location": "Remote APAC", "remote_policy": "Remote"},
        )

        self.assertTrue(is_workable_from_vietnam_candidate(vietnam))
        self.assertTrue(is_workable_from_vietnam_candidate(remote_apac))

    def test_vietnam_workability_filter_rejects_part_time_roles(self):
        part_time = CandidateItem(
            source_name="FWDDeploy Remote Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Forward Deployed AI Engineer",
            url="https://www.fwddeploy.com/jobs/part-time-fde",
            canonical_url="https://www.fwddeploy.com/jobs/part-time-fde",
            summary="Company: ETHjuniors. Location: Remote. Employment: Part-time.",
            raw={"company": "ETHjuniors", "location": "Remote", "remote_policy": "Remote", "employment_type": "Part-time"},
        )

        self.assertFalse(is_workable_from_vietnam_candidate(part_time))

    def test_vietnam_workability_filter_rejects_nontechnical_role_in_summary(self):
        designer = CandidateItem(
            source_name="FWDDeploy Remote Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="FWDDeploy Remote Jobs",
            url="https://www.fwddeploy.com/jobs/forward-deployed-creative-designer-ads",
            canonical_url="https://www.fwddeploy.com/jobs/forward-deployed-creative-designer-ads",
            summary="Forward Deployed Creative Designer, Ads. Company: Jobgether. Location: Remote. Employment: Full-time.",
            raw={"company": "Jobgether", "location": "Remote", "remote_policy": "Remote", "employment_type": "Full-time"},
        )

        self.assertFalse(is_workable_from_vietnam_candidate(designer))

    def test_vietnam_workability_filter_rejects_nontechnical_opportunity(self):
        opportunity = make_opportunity(1)
        opportunity = JobOpportunity(
            **{
                **opportunity.__dict__,
                "id": "jobgether-forward-deployed-creative-designer",
                "company": "Jobgether",
                "role_title": "Forward Deployed Creative Designer, Ads",
                "location": "Remote",
                "remote_policy": "Remote",
                "vietnam_eligibility": "verify",
                "why_it_fits": "Forward deployed creative designer ads role.",
            }
        )

        self.assertFalse(is_workable_from_vietnam_opportunity(opportunity))

    def test_prefilter_rejects_forward_deployed_designer_roles(self):
        designer = CandidateItem(
            source_name="FWDDeploy Remote Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Forward Deployed Creative Designer, Ads",
            url="https://www.fwddeploy.com/jobs/designer",
            canonical_url="https://www.fwddeploy.com/jobs/designer",
            summary="Company: Jobgether. Location: Remote. Employment: Full-time.",
            raw={"company": "Jobgether", "location": "Remote", "remote_policy": "Remote", "employment_type": "Full-time"},
        )

        self.assertFalse(is_fde_job_candidate(designer))

    def test_new_job_candidates_dedupes_same_canonical_url_across_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                max_source_workers=1,
                max_candidates_per_source=10,
                max_llm_items_per_run=20,
            )
            conn = connect_database(settings)
            init_db(conn)
            sources = [
                Source("FWDDeploy Remote Jobs", "html", "https://example.com/remote", "fde-job-board"),
                Source("FWDDeploy All Jobs", "html", "https://example.com/all", "fde-job-board"),
            ]
            first = CandidateItem(
                source_name="FWDDeploy Remote Jobs",
                source_kind="html",
                source_category="fde-job-board",
                title="Founding Forward Deployed Engineer",
                url="https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
                canonical_url="https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
                summary="Company: Clera. Location: Remote APAC. Employment: Full-time.",
                fingerprint="same-job",
                raw={"company": "Clera", "location": "Remote APAC", "remote_policy": "Remote", "source_type": "job_board"},
            )
            second = CandidateItem(
                source_name="FWDDeploy All Jobs",
                source_kind="html",
                source_category="fde-job-board",
                title="Founding Forward Deployed Engineer",
                url="https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
                canonical_url="https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
                summary="Company: Clera. Location: Remote APAC. Employment: Full-time.",
                fingerprint="same-job",
                raw={"company": "Clera", "location": "Remote APAC", "remote_policy": "Remote", "source_type": "job_board"},
            )

            with patch("news_keep_up.job_alerts.fetch_source", side_effect=[[first], [second]]):
                queued = _new_job_candidates(conn, settings, sources)

            conn.close()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][1].source_name, "FWDDeploy Remote Jobs")

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
