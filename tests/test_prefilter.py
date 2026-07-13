import unittest

from news_keep_up.models import CandidateItem
from news_keep_up.prefilter import is_candidate_relevant, is_candidate_relevant_for_slot, prefilter_score


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

    def test_fde_slot_rejects_generic_ai_infrastructure_items(self):
        generic = item(
            "How to price serverless GPUs",
            "To compare rates for serverless and reserved GPUs, look at peak-to-average ratio.",
            "ai-engineering",
        )
        generic_thread = item(
            "Show HN: Orchestrate parallel Claude Code and Codex agents",
            "I frequently run many coding agents in parallel and lose the picture of which subagent is working.",
            "discussion-fde",
        )

        self.assertFalse(is_candidate_relevant_for_slot(generic, "fde"))
        self.assertFalse(is_candidate_relevant_for_slot(generic_thread, "fde"))

    def test_fde_slot_rejects_generic_tooling_and_career_threads(self):
        generic_workbench = item(
            "Show HN: Rowboat - Open-source, local-first alternative to Claude Desktop",
            "Build your own work surfaces for agent workflows.",
            "discussion-fde",
        )
        job_hunt_agent = item(
            "I Built an AI Agent That Runs My Entire Job Hunt While I Sleep",
            "Ranked jobs, verified contacts, and ready-to-send outreach.",
            "fde-industry",
        )
        career_thread = item(
            "New CS grad, got two offers and I need to decide soon",
            "Offer A is a Solutions Architect presales role at Dell.",
            "discussion-fde",
        )

        self.assertFalse(is_candidate_relevant_for_slot(generic_workbench, "fde"))
        self.assertFalse(is_candidate_relevant_for_slot(job_hunt_agent, "fde"))
        self.assertFalse(is_candidate_relevant_for_slot(career_thread, "fde"))

    def test_fde_slot_accepts_enterprise_ai_delivery_items(self):
        candidate = item(
            "Building enterprise AI agents that are autonomous and reliable",
            "Customer-facing deployment teams use evals, guardrails, rollout metrics, and workflow integration.",
            "enterprise-ai",
        )

        self.assertTrue(is_candidate_relevant_for_slot(candidate, "fde"))

    def test_fde_slot_accepts_agent_governance_and_production_items(self):
        production_patterns = item(
            "3 production patterns for AI agents and how to evaluate each one",
            "A customer assistant and AI SRE need different harnesses, eval plans, and rollout paths.",
            "ai-engineering",
        )
        policy_enforcement = item(
            "Show HN: Policy enforcement for Claude Code, Cursor, and Codex",
            "Runtime authorization intercepts AI agent tool calls and evaluates them against deterministic policies.",
            "discussion-fde",
        )

        self.assertTrue(is_candidate_relevant_for_slot(production_patterns, "fde"))
        self.assertTrue(is_candidate_relevant_for_slot(policy_enforcement, "fde"))


if __name__ == "__main__":
    unittest.main()
