import unittest
import json
from collections import Counter
from pathlib import Path

from news_keep_up.models import Source
from news_keep_up.sources import parse_rss_or_atom


class SourcesTest(unittest.TestCase):
    def test_parse_rss_items_to_candidates(self):
        source = Source("Example Feed", "rss", "https://example.com/feed", "ai-engineering")
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title><![CDATA[AI agents for delivery teams]]></title>
            <link>https://example.com/post?utm_source=rss</link>
            <description><![CDATA[<p>How coding agents change software teams.</p>]]></description>
            <author>author@example.com</author>
            <pubDate>Mon, 06 Jul 2026 03:00:00 GMT</pubDate>
          </item>
        </channel></rss>
        """

        items = parse_rss_or_atom(xml, source)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "AI agents for delivery teams")
        self.assertEqual(items[0].canonical_url, "https://example.com/post")
        self.assertEqual(items[0].summary, "How coding agents change software teams.")
        self.assertEqual(items[0].source_name, "Example Feed")

    def test_parse_atom_entries_to_candidates(self):
        source = Source("Atom Feed", "rss", "https://example.com/atom", "discussion")
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>New MCP workflow pattern</title>
            <link href="https://example.com/atom-post#comments" />
            <summary>Discussion about agent tools and MCP.</summary>
            <updated>2026-07-06T09:00:00Z</updated>
          </entry>
        </feed>
        """

        items = parse_rss_or_atom(xml, source)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].canonical_url, "https://example.com/atom-post")
        self.assertEqual(items[0].published_at, "2026-07-06T09:00:00Z")
        self.assertEqual(items[0].source_category, "discussion")

    def test_engineer_sources_are_expanded_toward_ai_agentic_workflows(self):
        sources = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
        categories = Counter(source["category"] for source in sources if source.get("enabled", True))
        ai_categories = {
            "ai-engineering",
            "agentic-engineering",
            "ai-product",
            "ai-research",
            "agent-frameworks",
            "agent-orchestration",
            "ai-automation",
            "ai-observability",
            "llm-ops",
        }

        self.assertGreaterEqual(len(sources), 150)
        self.assertGreaterEqual(sum(categories[category] for category in ai_categories), 50)
        self.assertGreaterEqual(categories["software-engineering"], 13)

    def test_fde_interview_sources_cover_one_hundred_interview_prep_signals(self):
        sources = json.loads(Path("config/fde_interview_sources.json").read_text(encoding="utf-8"))
        categories = Counter(source["category"] for source in sources if source.get("enabled", True))

        self.assertGreaterEqual(len(sources), 100)
        self.assertGreaterEqual(categories["fde-interview"], 10)
        self.assertGreaterEqual(categories["agentic-interview"], 5)
        self.assertTrue(all(source["type"] in {"rss", "hackernews"} for source in sources))


if __name__ == "__main__":
    unittest.main()
