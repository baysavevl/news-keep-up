import unittest
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from news_keep_up.db import (
    connect_database,
    count_llm_calls_today,
    init_db,
    mark_delivered,
    upsert_enrichment,
    upsert_item,
)
from news_keep_up.digest import (
    _load_digest_candidates,
    _load_digest_candidates_for_slot,
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
    def test_engineer_selection_policy_targets_two_to_three_items(self):
        self.assertEqual(_selection_policy("engineer"), (2, 3, 1))

    def test_fde_selection_policy_targets_three_to_five_items(self):
        self.assertEqual(_selection_policy("fde"), (3, 5, 1))

    def test_fde_selection_returns_five_items_when_available(self):
        rows = [candidate(index, 95 - index, "fde-industry") for index in range(1, 10)]

        selections = select_digest_items(rows, min_items=3, max_items=5, discussion_limit=1)

        self.assertEqual(len(selections), 5)

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

    def test_selection_ranks_final_candidates_by_trust_and_content_quality(self):
        trusted = DigestCandidate(
            **{
                **candidate(1, 88, "ai-engineering").__dict__,
                "source_name": "OpenAI News",
                "title": "Production patterns for AI agents in product workflows",
                "enrichment": Enrichment(
                    **{
                        **enrichment(88, "ai-engineering", "agent-workflow").__dict__,
                        "summary": "Teams use evals, guardrails, observability, rollout metrics, and workflow automation to ship safer agent features.",
                        "why_it_matters": "Impact: turns agent adoption into a measurable engineering practice.",
                    }
                ),
            }
        )
        generic = DigestCandidate(
            **{
                **candidate(2, 95, "discussion").__dict__,
                "source_name": "Hacker News Generic AI",
                "title": "New agent model API is now in public beta",
                "enrichment": Enrichment(
                    **{
                        **enrichment(95, "discussion", "agent-api").__dict__,
                        "summary": "The announcement covers model availability, benchmark scores, API features, and cloud regions.",
                        "why_it_matters": "General AI announcement.",
                    }
                ),
            }
        )

        selections = select_digest_items([generic, trusted], min_items=1, max_items=1, discussion_limit=1)

        self.assertEqual([selection.candidate.item_id for selection in selections], [1])

    def test_format_uses_scan_first_telegram_html(self):
        selections = [
            select_digest_items([candidate(1, 95, "ai-engineering", is_backfill=True)], 1, 5, 1)[0]
        ]
        now = datetime(2026, 7, 6, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

        message = format_digest("news", selections, now=now)

        self.assertIn("<b>AI/FDE/SWE Digest</b>", message)
        self.assertIn("News · 06 Jul 10:00 ICT", message)
        self.assertRegex(message, r"<b>1\. .+ English title 1</b>")
        self.assertIn("Source: Test Source", message)
        self.assertIn("Topic: ai-engineering / coding-agents", message)
        self.assertIn("Fit:", message)
        self.assertIn("Why read:", message)
        self.assertIn("Scan:", message)
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
        self.assertIn("FDE ·", message)

    def test_format_includes_richer_scan_fields(self):
        selections = [
            select_digest_items([candidate(1, 92, "fde-industry")], 1, 5, 1)[0]
        ]

        message = format_digest("fde", selections)

        self.assertIn("Topic:", message)
        self.assertIn("Fit:", message)
        self.assertIn("Why read:", message)
        self.assertIn("Scan:", message)
        self.assertNotIn("Ý chính:", message)
        self.assertRegex(message, r"<b>1\. .+ English title 1</b>")
        self.assertIn("Source:", message)
        self.assertNotIn("Summary:", message)
        self.assertNotIn("Why:", message)

    def test_fde_format_uses_five_highlights_without_key_idea_section(self):
        item = candidate(1, 95, "fde-industry")
        item = DigestCandidate(
            **{
                **item.__dict__,
                "enrichment": Enrichment(
                    **{
                        **item.enrichment.__dict__,
                        "summary": (
                            "Customer discovery exposes the real rollout blocker. "
                            "The team maps stakeholder owners before integration. "
                            "Launch gates include evals and rollback criteria. "
                            "Observability tracks failed handoffs and support escalations. "
                            "The reusable playbook shortens the next enterprise deployment."
                        ),
                        "why_it_matters": "Impact: FDEs can turn this into a customer rollout checklist.",
                    }
                ),
            }
        )

        message = format_digest("fde", [DigestSelection(candidate=item, position=1)])
        bullets = [line for line in message.splitlines() if line.startswith("• ")]

        self.assertNotIn("Ý chính:", message)
        self.assertEqual(len(bullets), 5)
        self.assertIn("Customer discovery exposes", bullets[0])

    def test_format_places_compact_meta_before_item_body(self):
        message = format_digest("fde", [DigestSelection(candidate=candidate(1, 92, "fde-industry"), position=1)])

        self.assertLess(message.index("Fit:"), message.index("Why read:"))
        self.assertLess(message.index("Why read:"), message.index("Scan:"))
        self.assertLess(message.index("Scan:"), message.index("Read:"))

    def test_format_splits_digest_into_two_item_messages(self):
        selections = [
            DigestSelection(candidate=candidate(index, 95 - index, "fde-industry"), position=index)
            for index in range(1, 6)
        ]

        messages = format_digest_messages("fde", selections)

        self.assertEqual(len(messages), 3)
        self.assertIn("Part 1/3", messages[0])
        self.assertIn("Part 3/3", messages[2])
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

    def test_format_drops_medium_continue_reading_fragments(self):
        item = candidate(1, 95, "fde-industry")
        item = DigestCandidate(
            **{
                **item.__dict__,
                "enrichment": Enrichment(
                    **{
                        **item.enrichment.__dict__,
                        "summary": "Forward deployed teams need discovery gates. Continue reading on Medium »",
                    }
                ),
            }
        )

        message = format_digest("fde", [DigestSelection(candidate=item, position=1)])

        self.assertNotIn("Continue reading", message)
        self.assertIn("discovery gates", message)

    def test_format_skips_hacker_news_intro_for_key_idea(self):
        item = candidate(1, 95, "ai-engineering")
        item = DigestCandidate(
            **{
                **item.__dict__,
                "title": "Launch HN: Context.dev - API to get structured data from any website",
                "source_name": "Hacker News RAG Agents",
                "enrichment": Enrichment(
                    **{
                        **item.enrichment.__dict__,
                        "summary": (
                            "Hi Hacker News, I'm Yahia. "
                            "I built Context.dev to make it really easy to integrate web data into your products and agents. "
                            "Here's a demo video: https://www.tella.tv/video/build-faster-with-context-dev-api. "
                            "Since it's an API, here are the docs: https://docs.context.dev/quickstart. "
                            "You can send us a URL and get back clean Markdown, rendered HTML, screenshots, extracted images, etc."
                        ),
                    }
                ),
            }
        )

        message = format_digest("engineer", [DigestSelection(candidate=item, position=1)])

        self.assertNotIn("Ý chính: Hi Hacker News", message)
        self.assertIn("Why read: I built Context.dev", message)
        self.assertNotIn("demo video", message)
        self.assertNotIn("here are the docs", message)

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

    def test_run_digest_sends_no_news_heartbeat_when_no_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_path = Path(tmp) / "sources.json"
            sources_path.write_text(json.dumps([{
                "name": "Empty Feed",
                "type": "rss",
                "url": "https://example.com/feed.xml",
                "category": "ai-engineering",
                "enabled": True,
            }]), encoding="utf-8")
            settings = Settings(
                db_path=Path(tmp) / "test.db",
                telegram_bot_token="token",
                telegram_chat_id="-100123",
            )

            with (
                patch("news_keep_up.digest.fetch_source", return_value=[]),
                patch("news_keep_up.digest.send_telegram_message") as send,
                patch("news_keep_up.digest.mark_delivered") as mark,
            ):
                message = run_digest(settings, "engineer", dry_run=False, sources_path=sources_path)

        self.assertIn("Scheduler OK", message)
        self.assertIn("No qualifying items found", message)
        send.assert_called_once()
        mark.assert_not_called()

    def test_engineer_digest_does_not_select_fde_only_source_from_shared_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_path = Path(tmp) / "engineer_sources.json"
            sources_path.write_text(json.dumps([{
                "name": "Engineer AI Feed",
                "type": "rss",
                "url": "https://example.com/engineer.xml",
                "category": "ai-engineering",
                "enabled": True,
            }]), encoding="utf-8")
            settings = Settings(db_path=Path(tmp) / "test.db", gemini_api_key="")
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="FDE Only Feed",
                source_kind="rss",
                source_category="fde-industry",
                title="Customer rollout playbook for forward deployed AI teams",
                url="https://example.com/fde-only",
                canonical_url="https://example.com/fde-only",
                summary="Customer-facing AI rollout needs evals, guardrails, integration owners, and launch gates.",
                published_at=now_ict().isoformat(),
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, item_id, enrichment(98, "fde-industry", "customer-rollout"))

            with patch("news_keep_up.digest.fetch_source", return_value=[]):
                message = run_digest(settings, "engineer", dry_run=True, sources_path=sources_path)

        self.assertIn("No qualifying items found", message)
        self.assertNotIn("Customer rollout playbook", message)

    def test_engineer_digest_does_not_select_item_already_delivered_to_fde(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_path = Path(tmp) / "engineer_sources.json"
            sources_path.write_text(json.dumps([{
                "name": "Shared AI Feed",
                "type": "rss",
                "url": "https://example.com/shared.xml",
                "category": "ai-engineering",
                "enabled": True,
            }]), encoding="utf-8")
            settings = Settings(db_path=Path(tmp) / "test.db", gemini_api_key="")
            conn = connect_database(settings)
            init_db(conn)
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Shared AI Feed",
                source_kind="rss",
                source_category="ai-engineering",
                title="Agentic engineering patterns for AI teams",
                url="https://example.com/shared-ai",
                canonical_url="https://example.com/shared-ai",
                summary="Coding agents, evals, and workflow automation for delivery teams.",
                published_at=now_ict().isoformat(),
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, item_id, enrichment(96, "ai-engineering", "coding-agents"))
            mark_delivered(conn, [item_id], "fde", set())

            with patch("news_keep_up.digest.fetch_source", return_value=[]):
                message = run_digest(settings, "engineer", dry_run=True, sources_path=sources_path)

        self.assertIn("No qualifying items found", message)
        self.assertNotIn("Agentic engineering patterns", message)

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

    def test_fde_backfill_expands_to_fourteen_days_when_recent_window_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db", backfill_lookback_days=7)
            conn = connect_database(settings)
            init_db(conn)
            twelve_days_ago = (now_ict() - timedelta(days=12)).astimezone(ZoneInfo("UTC")).isoformat()
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="FDE Voice",
                source_kind="rss",
                source_category="fde-industry",
                title="Customer rollout playbook for forward deployed AI teams",
                url="https://example.com/fde-rollout",
                canonical_url="https://example.com/fde-rollout",
                summary="Customer-facing AI rollout needs evals, guardrails, integration owners, and launch gates.",
                published_at=twelve_days_ago,
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, item_id, enrichment(95, "fde-industry", "customer-rollout"))

            base_rows = _load_digest_candidates(conn, settings, set())
            fde_rows = _load_digest_candidates_for_slot(conn, settings, "fde", set())

        self.assertEqual(base_rows, [])
        self.assertEqual([row.item_id for row in fde_rows], [item_id])

    def test_fde_backfill_rechecks_slot_relevance_for_stored_generic_ai_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db", backfill_lookback_days=10)
            conn = connect_database(settings)
            init_db(conn)
            generic_id, _ = upsert_item(conn, CandidateItem(
                source_name="Sourcegraph Blog",
                source_kind="rss",
                source_category="ai-engineering",
                title="Agentic Batch Changes is now in public beta",
                url="https://example.com/sourcegraph-agentic-batch",
                canonical_url="https://example.com/sourcegraph-agentic-batch",
                summary="Coding agents automate pull requests and developer productivity workflows.",
                published_at=now_ict().isoformat(),
                fetched_at=now_ict().isoformat(),
            ))
            rollout_id, _ = upsert_item(conn, CandidateItem(
                source_name="FDE Voice",
                source_kind="rss",
                source_category="fde-industry",
                title="Customer rollout playbook for forward deployed AI teams",
                url="https://example.com/fde-rollout",
                canonical_url="https://example.com/fde-rollout",
                summary="Customer-facing deployment teams use evals, guardrails, rollout metrics, and workflow integration.",
                published_at=now_ict().isoformat(),
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, generic_id, enrichment(90, "developer-tools", "coding-agents"))
            upsert_enrichment(conn, rollout_id, enrichment(91, "fde-industry", "customer-rollout"))

            rows = _load_digest_candidates_for_slot(
                conn,
                settings,
                "fde",
                set(),
                allowed_source_names={"Sourcegraph Blog", "FDE Voice"},
            )

        self.assertEqual([row.item_id for row in rows], [rollout_id])

    def test_engineer_backfill_expands_to_twenty_one_days_when_still_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db", backfill_lookback_days=7)
            conn = connect_database(settings)
            init_db(conn)
            eighteen_days_ago = (now_ict() - timedelta(days=18)).astimezone(ZoneInfo("UTC")).isoformat()
            item_id, _ = upsert_item(conn, CandidateItem(
                source_name="Engineer AI Feed",
                source_kind="rss",
                source_category="ai-engineering",
                title="Agentic engineering workflow from two weeks ago",
                url="https://example.com/agentic-backfill",
                canonical_url="https://example.com/agentic-backfill",
                summary="Coding agents, evals, and workflow automation remain relevant for engineering teams.",
                published_at=eighteen_days_ago,
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, item_id, enrichment(93, "ai-engineering", "coding-agents"))

            rows = _load_digest_candidates_for_slot(
                conn,
                settings,
                "engineer",
                set(),
                allowed_source_names={"Engineer AI Feed"},
                min_items=5,
            )

        self.assertEqual([row.item_id for row in rows], [item_id])

    def test_engineer_backfill_rechecks_practical_ai_agent_relevance(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "test.db", backfill_lookback_days=10)
            conn = connect_database(settings)
            init_db(conn)
            generic_id, _ = upsert_item(conn, CandidateItem(
                source_name="Sourcegraph Blog",
                source_kind="rss",
                source_category="developer-tools",
                title="Agentic Batch Changes is now in public beta",
                url="https://example.com/agentic-batch-beta",
                canonical_url="https://example.com/agentic-batch-beta",
                summary="A developer-tool launch announcement for running coding agents across repositories.",
                published_at=now_ict().isoformat(),
                fetched_at=now_ict().isoformat(),
            ))
            practical_id, _ = upsert_item(conn, CandidateItem(
                source_name="Engineer AI Feed",
                source_kind="rss",
                source_category="ai-engineering",
                title="Production patterns for AI agents in product workflows",
                url="https://example.com/practical-agent-workflow",
                canonical_url="https://example.com/practical-agent-workflow",
                summary="Teams use evals, guardrails, observability, rollout metrics, and workflow automation to ship safer agent features.",
                published_at=now_ict().isoformat(),
                fetched_at=now_ict().isoformat(),
            ))
            upsert_enrichment(conn, generic_id, enrichment(95, "ai-engineering", "agent-api"))
            upsert_enrichment(conn, practical_id, enrichment(94, "ai-engineering", "agent-workflow"))

            rows = _load_digest_candidates_for_slot(
                conn,
                settings,
                "engineer",
                set(),
                allowed_source_names={"Sourcegraph Blog", "Engineer AI Feed"},
            )

        self.assertEqual([row.item_id for row in rows], [practical_id])

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

    def test_run_digest_rechecks_fde_role_fit_after_gemini_review(self):
        research_tool = DigestCandidate(
            **{
                **candidate(1, 95, "discussion").__dict__,
                "source_name": "Reddit Machine Learning",
                "title": (
                    "Hundreds of papers hit arXiv every day and maybe 3 matter to my research, "
                    "so I built an open-source tool that finds them [P]"
                ),
                "enrichment": Enrichment(
                    **{
                        **enrichment(95, "discussion", "ai-tools").__dict__,
                        "summary": (
                            "Left: Telegram digest. Right: detailed digest on HTML. "
                            "Research Radar fetches arXiv RSS and API, then scores abstracts "
                            "against a markdown file describing research interests."
                        ),
                        "why_it_matters": "Worth scanning for architecture, delivery, or productization impact.",
                        "takeaway_vi": "Đọc nhanh để lấy ý chính và cân nhắc áp dụng vào delivery.",
                    }
                ),
            }
        )
        reviewed = Enrichment(**{
            **research_tool.enrichment.__dict__,
            "model": "gemini-review",
            "relevance_score": 92,
            "summary": (
                "Left: Telegram digest. Right: detailed digest on HTML. "
                "Skimming arXiv listings takes 30-60 minutes a day. "
                "The cron job fetches new papers from arXiv RSS and API. "
                "It scores abstracts against a markdown file of research interests. "
                "The HTML view gives a more detailed digest."
            ),
            "why_it_matters": "Impact: generic research tooling, not a customer deployment workflow.",
            "should_send": True,
        })

        with (
            patch("news_keep_up.digest._fetch_store_and_enrich", return_value={1}),
            patch("news_keep_up.digest._load_digest_candidates", return_value=[research_tool]),
            patch("news_keep_up.digest.GeminiClient.review_digest_candidates", return_value={1: reviewed}),
        ):
            message = run_digest(Settings(gemini_api_key="key"), "fde", dry_run=True)

        self.assertIn("No qualifying items found", message)
        self.assertNotIn("Hundreds of papers hit arXiv", message)

    def test_run_digest_does_not_let_review_topic_create_fde_relevance(self):
        computer_use_api = DigestCandidate(
            **{
                **candidate(1, 95, "ai-engineering").__dict__,
                "source_name": "Hacker News Production AI Agents",
                "title": "Launch HN: Coasty (YC S26) - An API for computer-use agents",
                "enrichment": Enrichment(
                    **{
                        **enrichment(95, "ai-engineering", "coding-agents").__dict__,
                        "summary": (
                            "Computer-use agents complete workflows inside legacy desktop software and web applications. "
                            "Developers send a natural-language task, credentials, and files; the agent verifies the result "
                            "and returns structured run records."
                        ),
                        "why_it_matters": "Generic agent tooling without a customer rollout or field delivery lesson.",
                    }
                ),
            }
        )
        reviewed = Enrichment(**{
            **computer_use_api.enrichment.__dict__,
            "model": "gemini-review",
            "relevance_score": 92,
            "category": "ai-engineering",
            "topic": "enterprise-rollout",
            "summary": (
                "Computer-use agents complete workflows inside legacy desktop software and web applications. "
                "The API accepts credentials and files. "
                "The agent operates screenshots, mouse, and keyboard. "
                "It verifies results and returns structured run records. "
                "This is agent infrastructure, not customer deployment practice."
            ),
            "why_it_matters": "Impact: generic agent API, not a concrete FDE rollout playbook.",
            "should_send": True,
        })

        with (
            patch("news_keep_up.digest._fetch_store_and_enrich", return_value={1}),
            patch("news_keep_up.digest._load_digest_candidates", return_value=[computer_use_api]),
            patch("news_keep_up.digest.GeminiClient.review_digest_candidates", return_value={1: reviewed}),
        ):
            message = run_digest(Settings(gemini_api_key="key"), "fde", dry_run=True)

        self.assertIn("No qualifying items found", message)
        self.assertNotIn("Coasty", message)

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

        self.assertEqual(send.call_count, 3)
        self.assertIn("FDE News Thread", send.call_args_list[0].args[0])
        self.assertIn("Schedule: every 2 hours", send.call_args_list[0].args[0])
        self.assertIn("Selected: 4 items", send.call_args_list[0].args[0])
        self.assertIn("<b>FDE Digest</b>", send.call_args_list[1].args[0])
        self.assertEqual(mark.call_count, 2)
        self.assertEqual(mark.call_args_list[0].args[1], [1, 2])
        self.assertEqual(mark.call_args_list[1].args[1], [3, 4])


if __name__ == "__main__":
    unittest.main()
