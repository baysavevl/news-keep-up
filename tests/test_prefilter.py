import unittest

from news_keep_up.models import CandidateItem
from news_keep_up.prefilter import is_candidate_relevant, prefilter_score


def item(title: str, summary: str = "", category: str = "ai-engineering") -> CandidateItem:
    return CandidateItem(
        source_name="Test",
        source_kind="rss",
        source_category=category,
        title=title,
        url="https://example.com/post",
        canonical_url="https://example.com/post",
        summary=summary,
    )


class PrefilterTest(unittest.TestCase):
    def test_ai_agent_engineering_item_scores_as_relevant(self):
        candidate = item(
            "Agentic engineering patterns for software teams",
            "Claude Code, Codex, and Gemini CLI change delivery workflows.",
        )

        self.assertGreaterEqual(prefilter_score(candidate), 50)
        self.assertTrue(is_candidate_relevant(candidate))

    def test_generic_job_ad_is_excluded_even_with_engineering_words(self):
        candidate = item(
            "Senior software engineer job opening",
            "Apply now for a remote AI engineer role with great benefits.",
        )

        self.assertEqual(prefilter_score(candidate), 0)
        self.assertFalse(is_candidate_relevant(candidate))

    def test_discussion_items_need_strong_ai_signal(self):
        weak = item("What monitor should I buy?", "General programming desk setup.", "discussion")
        strong = item("HN discussion: AI coding agents in production", "Teams compare evals and RAG workflows.", "discussion")

        self.assertFalse(is_candidate_relevant(weak))
        self.assertTrue(is_candidate_relevant(strong))

    def test_forward_deployed_engineering_item_scores_as_relevant(self):
        candidate = item(
            "Forward deployed engineers move enterprise AI from pilot to production",
            "Customer-embedded engineering, evals, integrations, and workflow rollout.",
            "fde-industry",
        )

        self.assertGreaterEqual(prefilter_score(candidate), 50)
        self.assertTrue(is_candidate_relevant(candidate))


if __name__ == "__main__":
    unittest.main()
