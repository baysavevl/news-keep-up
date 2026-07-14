import unittest
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from news_keep_up.db import connect_database, count_llm_calls_today, init_db, upsert_enrichment, upsert_item
from news_keep_up.digest import (
    _load_digest_candidates,
    _selection_policy,
    format_digest,
    format_digest_messages,
    run_digest,
    select_digest_items,
)
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
        author=f"Author {item_id}",
        enrichment=enrichment(score, source_category),
        is_backfill=is_backfill,
    )


class DigestTest(unittest.TestCase):
    def test_fde_selection_policy_targets_eight_items(self):
        self.assertEqual(_selection_policy("fde"), (8, 8, 2))

    def test_fde_selection_returns_eight_items_when_available(self):
        rows = [candidate(index, 95 - index, "fde-industry") for index in range(1, 10)]

        selections = select_digest_items(rows, min_items=6, max_items=8, discussion_limit=2)

        self.assertEqual(len(selections), 8)

    def test_selection_caps_discussion_profile_categories(self):
        rows = [
            candidate(1, 95, "discussion-fde"),
            candidate(2, 94, "discussion-fde"),
            candidate(3, 93, "discussion-fde"),
            candidate(4, 92, "fde-industry"),
            candidate(5, 91, "fde-industry"),
        ]

        selections = select_digest_items(rows, min_items=3, max_items=5, discussion_limit=2)

        self.assertEqual(len(selections), 4)
        self.assertEqual(sum(1 for s in selections if s.candidate.source_category == "discussion-fde"), 2)

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

    def test_selection_prefers_newer_items_with_similar_impact(self):
        older = candidate(1, 94, "ai-engineering")
        newer = DigestCandidate(
            **{
                **candidate(2, 91, "ai-engineering").__dict__,
                "published_at": "2026-07-13T03:00:00+00:00",
                "fetched_at": "2026-07-13T03:01:00+00:00",
            }
        )

        selections = select_digest_items([older, newer], min_items=1, max_items=2, discussion_limit=1)

        self.assertEqual([selection.candidate.item_id for selection in selections], [2, 1])

    def test_format_uses_compact_telegram_html(self):
        selections = [
            select_digest_items([candidate(1, 95, "ai-engineering", is_backfill=True)], 1, 5, 1)[0]
        ]
        now = datetime(2026, 7, 6, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

        message = format_digest("news", selections, now=now)

        self.assertIn("<b>AI/FDE/SWE Digest</b>", message)
        self.assertIn("News | 06 Jul 2026 10:00 ICT", message)
        self.assertRegex(message, r"<b>1\. .+ English title 1</b>")
        self.assertIn("Source: Test Source |", message)
        self.assertIn("Author: Author 1", message)
        self.assertIn("Category: ai-engineering / coding-agents", message)
        self.assertIn("Popularity:", message)
        self.assertIn("Ý chính:", message)
        self.assertIn("Highlights:", message)
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

    def test_format_includes_richer_scan_fields(self):
        selections = [
            select_digest_items([candidate(1, 92, "fde-industry")], 1, 5, 1)[0]
        ]

        message = format_digest("fde", selections)

        self.assertIn("Category:", message)
        self.assertIn("Popularity:", message)
        self.assertIn("Importance:", message)
        self.assertIn("Ý chính:", message)
        self.assertIn("Highlights:", message)
        self.assertRegex(message, r"<b>1\. .+ English title 1</b>")
        self.assertIn("Source:", message)
        self.assertNotIn("Summary:", message)
        self.assertNotIn("Why:", message)

    def test_format_places_ranking_after_separator_at_item_bottom(self):
        message = format_digest("fde", [DigestSelection(candidate=candidate(1, 92, "fde-industry"), position=1)])

        self.assertIn("\n\n-----\n🔥 Popularity:", message)
        self.assertLess(message.index("🔗 Read:"), message.index("-----"))
        self.assertLess(message.index("-----"), message.index("Importance:"))

    def test_format_splits_digest_into_two_item_messages(self):
        selections = [
            DigestSelection(candidate=candidate(index, 95 - index, "fde-industry"), position=index)
            for index in range(1, 9)
        ]

        messages = format_digest_messages("fde", selections)

        self.assertEqual(len(messages), 4)
        self.assertIn("Part 1/4", messages[0])
        self.assertIn("Part 4/4", messages[3])
        self.assertIn("1.", messages[0])
        self.assertIn("2.", messages[0])
        self.assertNotIn("3.", messages[0])

    def test_format_includes_source_trust_and_impact_ranking(self):
        selections = [
            select_digest_items([candidate(1, 92, "fde-industry")], 1, 5, 1)[0]
        ]

        message = format_digest("fde", selections)

        self.assertIn("Trust:", message)
        self.assertIn("Impact:", message)
        self.assertRegex(message, r"Trust: (High|Medium|Emerging) \([0-9]+/100\)")
        self.assertRegex(message, r"Impact: (High|Medium|Niche) \([0-9]+/100\)")

    def test_format_drops_feed_footer_fragments_from_highlights(self):
        item = candidate(1, 95, "ai-engineering")
        item = DigestCandidate(
            **{
                **item.__dict__,
                "enrichment": Enrichment(
                    **{
                        **item.enrichment.__dict__,
                        "summary": "Agents need identity and evals. It lets... The post Agents appeared first on Example.",
                    }
                ),
            }
        )

        message = format_digest("fde", [DigestSelection(candidate=item, position=1)])

        self.assertNotIn("It lets", message)
        self.assertNotIn("appeared first", message)

    def test_format_replaces_title_repeated_highlights_with_role_specific_bullets(self):
        title = "One Contract, Every Model: An Operating Standard for AI Coding Agents"
        item = candidate(1, 95, "ai-engineering")
        item = DigestCandidate(
            **{
                **item.__dict__,
                "title": title,
                "enrichment": Enrichment(
                    **{
                        **item.enrichment.__dict__,
                        "summary": f"{title}. {title}.",
                        "why_it_matters": f"{title}.",
                    }
                ),
            }
        )

        message = format_digest("engineer", [DigestSelection(candidate=item, position=1)])
        bullets = [line for line in message.splitlines() if line.startswith("• ")]

        self.assertGreaterEqual(len(bullets), 3)
        self.assertTrue(all(title not in bullet for bullet in bullets))
        self.assertIn("eval", message.lower())

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

        self.assertIn("Agent &lt;tools&gt; &amp; repos</b>", message)
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

    def test_run_digest_uses_configured_source_fetch_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_path = Path(tmp) / "sources.json"
            sources_path.write_text(json.dumps([{
                "name": "Local Feed",
                "type": "rss",
                "url": "https://example.com/feed.xml",
                "category": "ai-engineering",
                "enabled": True,
            }]), encoding="utf-8")
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                source_fetch_timeout_seconds=2,
                max_source_workers=1,
            )

            with patch("news_keep_up.digest.fetch_source", return_value=[]) as fetch:
                run_digest(settings, "engineer", dry_run=True, sources_path=sources_path)

        self.assertEqual(fetch.call_args.args[2], 2)

    def test_cached_fallback_is_refreshed_when_model_key_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp) / "feed.xml"
            feed_path.write_text("""<?xml version="1.0"?>
            <rss version="2.0"><channel>
              <item>
                <title>Enterprise AI deployment playbook for FDE teams</title>
                <link>https://example.com/fde</link>
                <description>Customer-facing rollout, evals, guardrails, and workflow integration.</description>
                <pubDate>Mon, 13 Jul 2026 03:00:00 GMT</pubDate>
              </item>
            </channel></rss>
            """, encoding="utf-8")
            sources_path = Path(tmp) / "sources.json"
            sources_path.write_text(json.dumps([{
                "name": "Local FDE Feed",
                "type": "rss",
                "url": feed_path.as_uri(),
                "category": "fde-industry",
                "enabled": True,
            }]), encoding="utf-8")
            db_path = Path(tmp) / "test.db"

            run_digest(Settings(db_path=db_path, gemini_api_key=""), "fde", dry_run=True, sources_path=sources_path)
            refreshed = enrichment(96, "fde-industry", "enterprise-rollout")
            refreshed = Enrichment(**{**refreshed.__dict__, "model": "gemini-test", "summary": "Key idea. Concrete highlight."})

            with patch("news_keep_up.digest.GeminiClient.enrich", return_value=refreshed) as enrich:
                run_digest(Settings(db_path=db_path, gemini_api_key="key"), "fde", dry_run=True, sources_path=sources_path)

            conn = connect_database(Settings(db_path=db_path))
            row = conn.execute("SELECT model, summary FROM enrichments LIMIT 1").fetchone()

        self.assertEqual(row["model"], "gemini-test")
        self.assertEqual(row["summary"], "Key idea. Concrete highlight.")
        self.assertTrue(enrich.called)

    def test_old_published_items_are_not_selected_as_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db", backfill_lookback_days=10)
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

    def test_run_digest_uses_gemini_batch_review_before_selecting_items(self):
        generic = candidate(1, 80, "ai-engineering")
        rollout = candidate(2, 70, "fde-industry")
        reviewed_generic = Enrichment(**{
            **generic.enrichment.__dict__,
            "model": "gemini-review",
            "relevance_score": 20,
            "summary": "Generic AI launch.",
            "should_send": False,
        })
        reviewed_rollout = Enrichment(**{
            **rollout.enrichment.__dict__,
            "model": "gemini-review",
            "relevance_score": 98,
            "icon": "🧭",
            "summary": "Key idea: customer rollout depends on eval gates. Use acceptance criteria before launch.",
            "why_it_matters": "Impact: FDEs can turn this into a production launch gate.",
            "takeaway_vi": "Ưu tiên eval gate trước rollout.",
            "should_send": True,
        })

        with (
            patch("news_keep_up.digest._fetch_store_and_enrich", return_value={1, 2}),
            patch("news_keep_up.digest._load_digest_candidates", return_value=[generic, rollout]),
            patch("news_keep_up.digest.GeminiClient.review_digest_candidates", return_value={
                1: reviewed_generic,
                2: reviewed_rollout,
            }) as review,
        ):
            message = run_digest(Settings(gemini_api_key="key"), "fde", dry_run=True)

        self.assertTrue(review.called)
        self.assertIn("English title 2", message)
        self.assertNotIn("English title 1", message)
        self.assertIn("98/100", message)

    def test_run_digest_sends_and_marks_each_message_chunk(self):
        rows = [candidate(index, 95 - index, "fde-industry") for index in range(1, 5)]

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )
            with (
                patch("news_keep_up.digest._fetch_store_and_enrich", return_value={1, 2, 3, 4}),
                patch("news_keep_up.digest._load_digest_candidates", return_value=rows),
                patch("news_keep_up.digest.send_telegram_message") as send,
                patch("news_keep_up.digest.mark_delivered") as mark,
            ):
                run_digest(settings, "fde", dry_run=False)

        self.assertEqual(send.call_count, 2)
        self.assertEqual(mark.call_count, 2)
        self.assertEqual(mark.call_args_list[0].args[1], [1, 2])
        self.assertEqual(mark.call_args_list[1].args[1], [3, 4])


if __name__ == "__main__":
    unittest.main()
