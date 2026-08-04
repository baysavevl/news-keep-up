import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_keep_up.models import CandidateItem, Settings
from news_keep_up.source_intelligence import (
    is_source_candidate,
    run_fde_job_source_intelligence,
)


def make_source_discovery_item() -> CandidateItem:
    return CandidateItem(
        source_name="Bing Source Discovery",
        source_kind="rss",
        source_category="source-discovery-search",
        title="Ashby Forward Deployed Engineer APAC jobs",
        url="https://jobs.ashbyhq.com/runpod",
        canonical_url="https://jobs.ashbyhq.com/runpod",
        summary="Indexed ATS page with Forward Deployed Engineer roles in APAC.",
        published_at="2026-07-27T00:00:00+00:00",
        fetched_at="2026-07-27T07:10:00+07:00",
        fingerprint="source-fp-1",
        raw={"source_type": "ATS"},
    )


def make_source_discovery_item_with_url(url: str) -> CandidateItem:
    return CandidateItem(
        source_name="FWDDeploy Source Discovery",
        source_kind="html",
        source_category="source-discovery-search",
        title="Forward Deployed Engineer",
        url=url,
        canonical_url=url,
        summary="Remote Forward Deployed Engineer role from a job board.",
        published_at="2026-07-28T00:00:00+00:00",
        fetched_at="2026-07-28T07:10:00+07:00",
        fingerprint=url,
        raw={"source_type": "job_board"},
    )


class SourceIntelligenceTest(unittest.TestCase):
    def test_source_candidate_filter_accepts_ats_job_source(self):
        self.assertTrue(is_source_candidate(make_source_discovery_item()))

    def test_source_intelligence_stores_candidates_and_does_not_notify(self):
        with tempfile.TemporaryDirectory() as tmp:
            discovery_sources_path = Path(tmp) / "source_discovery.json"
            discovery_sources_path.write_text(json.dumps([
                {
                    "name": "Bing Source Discovery",
                    "type": "rss",
                    "url": "https://example.com/source-feed.xml",
                    "category": "source-discovery-search",
                    "source_type": "aggregator",
                    "enabled": True,
                }
            ]), encoding="utf-8")
            active_sources_path = Path(tmp) / "active_sources.json"
            active_sources_path.write_text(json.dumps([
                {
                    "name": "Bing FDE Vietnam",
                    "type": "rss",
                    "url": "https://www.bing.com/search?q=fde&format=rss",
                    "category": "fde-job-search",
                    "source_type": "aggregator",
                    "enabled": True,
                }
            ]), encoding="utf-8")
            settings = Settings(db_path=Path(tmp) / "test.db")

            with (
                patch("news_keep_up.source_intelligence.fetch_source", return_value=[make_source_discovery_item()]),
            ):
                message = run_fde_job_source_intelligence(
                    settings,
                    discovery_sources_path=discovery_sources_path,
                    active_sources_path=active_sources_path,
                )

            self.assertIn("Source Intelligence", message)
            self.assertIn("new source candidates: 1", message)

    def test_source_intelligence_allows_same_title_from_different_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            discovery_sources_path = Path(tmp) / "source_discovery.json"
            discovery_sources_path.write_text(json.dumps([
                {
                    "name": "FWDDeploy Source Discovery",
                    "type": "html",
                    "url": "https://example.com/source-feed.html",
                    "category": "source-discovery-search",
                    "source_type": "job_board",
                    "enabled": True,
                }
            ]), encoding="utf-8")
            active_sources_path = Path(tmp) / "active_sources.json"
            active_sources_path.write_text("[]", encoding="utf-8")
            settings = Settings(db_path=Path(tmp) / "test.db")
            items = [
                make_source_discovery_item_with_url("https://www.fwddeploy.com/jobs/fde-one"),
                make_source_discovery_item_with_url("https://www.fwddeploy.com/jobs/fde-two"),
            ]

            with patch("news_keep_up.source_intelligence.fetch_source", return_value=items):
                message = run_fde_job_source_intelligence(
                    settings,
                    discovery_sources_path=discovery_sources_path,
                    active_sources_path=active_sources_path,
                )

            self.assertIn("new source candidates: 2", message)


if __name__ == "__main__":
    unittest.main()
