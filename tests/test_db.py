import tempfile
import unittest
from pathlib import Path

from news_keep_up.db import (
    connect_database,
    count_llm_calls_today,
    get_enrichment,
    init_db,
    mark_delivered,
    record_llm_usage,
    upsert_enrichment,
    upsert_item,
    upsert_source,
)
from news_keep_up.models import CandidateItem, Enrichment, Settings, Source


def make_item(title: str = "AI agents for engineers") -> CandidateItem:
    return CandidateItem(
        source_name="Latent Space",
        source_kind="rss",
        source_category="ai-engineering",
        title=title,
        url="https://example.com/post?utm_source=x",
        canonical_url="https://example.com/post",
        summary="A useful article about AI agents.",
        content="",
        author="",
        published_at="2026-07-06T03:00:00+00:00",
        fetched_at="2026-07-06T03:01:00+00:00",
        fingerprint="abc",
        raw={"id": "1"},
    )


def make_enrichment(score: int = 88) -> Enrichment:
    return Enrichment(
        model="gemini-2.5-flash-lite",
        relevance_score=score,
        category="ai-engineering",
        topic="coding-agents",
        icon="AI",
        title_vi="Tác nhân AI cho kỹ sư",
        summary="This explains how coding agents change engineering workflows.",
        why_it_matters="Useful for designing agent-assisted delivery workflows.",
        takeaway_vi="Nên thử nghiệm agent trong quy trình giao việc nhỏ.",
        should_send=True,
    )


class DatabaseTest(unittest.TestCase):
    def test_upsert_source_and_item_dedupes_by_canonical_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            source = Source("Latent Space", "rss", "https://www.latent.space/feed", "ai-engineering")
            first_source_id = upsert_source(conn, source)
            second_source_id = upsert_source(conn, source)
            self.assertEqual(first_source_id, second_source_id)

            first_item_id, first_is_new = upsert_item(conn, make_item())
            second_item_id, second_is_new = upsert_item(conn, make_item("Updated title"))

            self.assertEqual(first_item_id, second_item_id)
            self.assertTrue(first_is_new)
            self.assertFalse(second_is_new)

    def test_enrichment_is_cached_by_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            self.assertIsNone(get_enrichment(conn, item_id))
            upsert_enrichment(conn, item_id, make_enrichment())
            cached = get_enrichment(conn, item_id)

            self.assertIsNotNone(cached)
            self.assertEqual(cached.title_vi, "Tác nhân AI cho kỹ sư")
            self.assertEqual(cached.relevance_score, 88)

    def test_delivery_and_llm_usage_are_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            record_llm_usage(conn, "gemini-2.5-flash-lite", "2026-07-06", "morning", item_id, "ok")
            record_llm_usage(conn, "gemini-2.5-flash-lite", "2026-07-06", "morning", item_id, "fallback")
            mark_delivered(conn, [item_id], "morning", {item_id})
            mark_delivered(conn, [item_id], "morning", {item_id})

            self.assertEqual(count_llm_calls_today(conn, "2026-07-06"), 2)
            row = conn.execute("SELECT is_backfill FROM deliveries WHERE item_id=?", (item_id,)).fetchone()
            self.assertEqual(row["is_backfill"], 1)
            count = conn.execute("SELECT COUNT(*) AS count FROM deliveries WHERE item_id=?", (item_id,)).fetchone()
            self.assertEqual(count["count"], 1)


if __name__ == "__main__":
    unittest.main()
