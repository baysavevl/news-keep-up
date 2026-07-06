import unittest
import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_keep_up.db import connect_database, count_llm_calls_today
from news_keep_up.digest import format_digest, run_digest, select_digest_items
from news_keep_up.models import DigestCandidate, Enrichment, Settings
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

    def test_format_places_vietnamese_title_under_english_title(self):
        selections = [
            select_digest_items([candidate(1, 95, "ai-engineering", is_backfill=True)], 1, 5, 1)[0]
        ]
        now = datetime(2026, 7, 6, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

        message = format_digest("morning", selections, now=now)

        self.assertIn("AI/FDE/SWE Digest | Morning | 06 Jul 2026 10:00 ICT", message)
        title_index = message.index("1. AI English title 1")
        translated_index = message.index("Title VN: Tiêu đề 95")
        self.assertLess(title_index, translated_index)
        self.assertIn("Backfill - still relevant", message)
        self.assertIn("Link: https://example.com/1", message)

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


if __name__ == "__main__":
    unittest.main()
