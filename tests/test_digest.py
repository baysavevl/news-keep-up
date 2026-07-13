import unittest
import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_keep_up.db import connect_database, count_llm_calls_today, init_db, upsert_enrichment, upsert_item
from news_keep_up.digest import _load_digest_candidates, format_digest, run_digest, select_digest_items
from news_keep_up.models import CandidateItem, DigestCandidate, DigestSelection, Enrichment, Settings
from news_keep_up.utils import now_ict


def enrichment(score: int, category: str, topic: str = "coding-agents") -> Enrichment:
    return Enrichment(
        model="gemini-test",
        relevance_score=score,
        category=category,
        topic=topic,
        icon="AI",
        title_vi=f"Tiêu đề {score}",
        summary=f"Summary {score}",
        why_it_matters=f"Why {score}",
        takeaway_vi=f"Takeaway {score}",
        should_send=True,
    )


def candidate(item_id: int, score: int, source_category: str, is_backfill: bool = False) -> DigestCandidate:
    return DigestCandidate(
        item_id=item_id,
        title=f"English title {item_id}",
        url=f"https://example.com/{item_id}",
        source_name="Test Source",
        source_category=source_category,
        published_at="2026-07-06T03:00:00+00:00",
        fetched_at="2026-07-06T03:01:00+00:00",
        enrichment=enrichment(score, source_category),
        is_backfill=is_backfill,
    )


class DigestTest(unittest.TestCase):
    def test_selection_caps_discussions_and_uses_backfill_to_reach_minimum(self):
        rows = [
            candidate(1, 95, "discussion"),
            candidate(2, 94, "discussion"),
            candidate(3, 80, "ai-engineering"),
            candidate(5, 70, "ai-engineering", is_backfill=True),
        ]

        selections = select_digest_items(rows, min_items=3, max_items=5, discussion_limit=1)

        self.assertEqual(len(selections), 3)
        self.assertEqual(sum(1 for s in selections if s.candidate.source_category == "discussion"), 1)
        self.assertTrue(any(s.candidate.is_backfill for s in selections))

    def test_format_uses_compact_telegram_html(self):
        selections = [
            select_digest_items([candidate(1, 95, "ai-engineering", is_backfill=True)], 1, 5, 1)[0]
        ]
        now = datetime(2026, 7, 6, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

        message = format_digest("news", selections, now=now)

        self.assertIn("<b>AI/FDE/SWE Digest</b>", message)
        self.assertIn("News | 06 Jul 2026 10:00 ICT", message)
        self.assertIn("<b>1. AI English title 1</b>", message)
        self.assertIn("Source: Test Source | ai-engineering / coding-agents", message)
        self.assertIn("Backfill - still relevant", message)
        self.assertIn('<a href="https://example.com/1">Read</a>', message)
        self.assertNotIn("Title VN:", message)
        self.assertNotIn("Link:", message)

    def test_format_uses_profile_specific_heading(self):
        selections = [
            select_digest_items([candidate(1, 95, "fde-industry")], 1, 5, 1)[0]
        ]

        message = format_digest("fde", selections)

        self.assertIn("<b>FDE Digest</b>", message)
        self.assertIn("FDE |", message)

    def test_format_escapes_html_and_hides_fallback_translation(self):
        item = candidate(1, 95, "ai-engineering")
        item = DigestCandidate(
            **{
                **item.__dict__,
                "title": "Agent <tools> & repos",
                "url": "https://example.com/read?x=1&y=2",
                "enrichment": Enrichment(
                    **{
                        **item.enrichment.__dict__,
                        "title_vi": "Agent <tools> & repos (bản dịch tự động chưa có)",
                    }
                ),
            }
        )

        message = format_digest("news", [DigestSelection(candidate=item, position=1)])

        self.assertIn("<b>1. AI Agent &lt;tools&gt; &amp; repos</b>", message)
        self.assertIn('href="https://example.com/read?x=1&amp;y=2"', message)
        self.assertNotIn("bản dịch tự động chưa có", message)

    def test_no_key_fallback_does_not_record_llm_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp) / "feed.xml"
            feed_path.write_text("""<?xml version="1.0"?>
            <rss version="2.0"><channel>
              <item>
                <title>Agentic engineering patterns for AI agents</title>
                <link>https://example.com/agentic</link>
                <description>Coding agents and evals for delivery teams.</description>
                <pubDate>Mon, 06 Jul 2026 03:00:00 GMT</pubDate>
              </item>
            </channel></rss>
            """, encoding="utf-8")
            sources_path = Path(tmp) / "sources.json"
            sources_path.write_text(json.dumps([{
                "name": "Local Feed",
                "type": "rss",
                "url": feed_path.as_uri(),
                "category": "ai-engineering",
                "enabled": True,
            }]), encoding="utf-8")
            settings = Settings(db_path=Path(tmp) / "test.db", gemini_api_key="")

            run_digest(settings, "morning", dry_run=True, sources_path=sources_path)
            conn = connect_database(settings)

            self.assertEqual(count_llm_calls_today(conn, now_ict().date().isoformat()), 0)

    def test_old_published_items_are_not_selected_as_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db", backfill_lookback_days=7)
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Old Feed",
                source_kind="rss",
                source_category="ai-engineering",
                title="Forward deployed engineering from 2024",
                url="https://example.com/old",
                canonical_url="https://example.com/old",
                summary="AI deployment pattern.",
                published_at="2024-02-27T00:00:00+00:00",
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, item_id, enrichment(95, "ai-engineering"))

            rows = _load_digest_candidates(conn, settings, {item_id})

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
