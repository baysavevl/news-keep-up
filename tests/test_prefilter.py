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

    def test_engineer_slot_rejects_generic_ai_agent_announcements(self):
        model_launch = item(
            "New agent model API is now in public beta",
            "The announcement covers model availability, benchmark scores, API features, and cloud regions.",
            "ai-engineering",
        )
        product_launch = item(
            "Agentic Batch Changes is now in public beta",
            "A developer-tool launch announcement for running coding agents across repositories.",
            "developer-tools",
        )

        self.assertFalse(is_candidate_relevant_for_slot(model_launch, "engineer"))
        self.assertFalse(is_candidate_relevant_for_slot(product_launch, "engineer"))

    def test_engineer_slot_accepts_practical_ai_agent_workflow_items(self):
        candidate = item(
            "Production patterns for AI agents in product workflows",
            "Teams use evals, guardrails, observability, rollout metrics, and workflow automation to ship safer agent features.",
            "ai-engineering",
        )

        self.assertTrue(is_candidate_relevant_for_slot(candidate, "engineer"))

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
        coding_policy = item(
            "Show HN: Policy enforcement for Claude Code, Cursor, and Codex",
            "Runtime authorization intercepts AI agent tool calls and evaluates them against deterministic policies.",
            "discussion-fde",
        )

        self.assertFalse(is_candidate_relevant_for_slot(generic, "fde"))
        self.assertFalse(is_candidate_relevant_for_slot(generic_thread, "fde"))
        self.assertFalse(is_candidate_relevant_for_slot(coding_policy, "fde"))

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

    def test_fde_slot_rejects_personal_research_digest_tooling(self):
        research_radar = item(
            "Hundreds of papers hit arXiv every day and maybe 3 matter to my research, so I built an open-source tool that finds them [P]",
            (
                "Left: Telegram digest. Right: detailed digest on HTML. "
                "Skimming arXiv listings takes 30-60 minutes a day, 95% is irrelevant to my research. "
                "Research Radar is a daily cron job that fetches new papers from arXiv RSS and API, "
                "then scores every abstract against a markdown file describing research interests."
            ),
            "discussion",
        )

        self.assertFalse(is_candidate_relevant_for_slot(research_radar, "fde"))

    def test_fde_slot_rejects_generic_agent_product_and_platform_items(self):
        generic_items = [
            item(
                "Launch HN: Coasty (YC S26) - An API for computer-use agents",
                (
                    "Computer-use agents complete workflows inside legacy desktop software and web applications "
                    "without usable APIs. Developers send a natural-language task, credentials, and files; "
                    "the agent operates screenshots, mouse, and keyboard, verifies the result, and returns run records."
                ),
                "ai-engineering",
            ),
            item(
                "Ask HN: Who build production apps without seeing code?",
                "A discussion about Cursor, Claude Code, Codex, agentic mode, and whether builders still need a code editor.",
                "ai-engineering",
            ),
            item(
                "Show HN: Vendo (YC S26) - Let your users add their own features to your product",
                (
                    "Users create personal micro-apps and features on top of a product. "
                    "Agents personalize dashboards, UIs, workflows, outcomes, and views for each user."
                ),
                "ai-engineering",
            ),
            item(
                "Agents need their own computer. Here's how to give them one safely.",
                (
                    "Sandboxes give every agent an isolated computer for iteration, verification, and access "
                    "to tools a person would normally use."
                ),
                "agent-frameworks",
            ),
            item(
                "New in Fleet: Deploy AI agents to Slack in one click",
                "Give agents custom identities, use them in Slack channels and threads, and keep work moving.",
                "agent-frameworks",
            ),
            item(
                "Agentic vision: Building visual intelligence with Amazon Bedrock and MCP servers",
                (
                    "A Computer Vision MCP Server shows how AI systems process visual information through "
                    "a standardized integration path for broader applications and developers."
                ),
                "ai-engineering",
            ),
        ]

        for candidate in generic_items:
            with self.subTest(candidate.title):
                self.assertFalse(is_candidate_relevant_for_slot(candidate, "fde"))

    def test_fde_slot_rejects_generic_ai_roundups_without_field_delivery_signal(self):
        weekly_roundup = item(
            "AWS Weekly Roundup: Claude Sonnet 5 on AWS, Amazon WorkSpaces for AI agents, AWS service availability updates",
            "A weekly roundup about startup stories, launches, service availability, and general AWS updates.",
            "enterprise-ai",
        )
        managed_agents = item(
            "Expanding Managed Agents in Gemini API: background tasks, remote MCP and more",
            "Managed agents feature bundle launch for developers using API background tasks.",
            "enterprise-ai",
        )

        self.assertFalse(is_candidate_relevant_for_slot(weekly_roundup, "fde"))
        self.assertFalse(is_candidate_relevant_for_slot(managed_agents, "fde"))

    def test_fde_slot_rejects_generic_enterprise_ai_model_and_api_news(self):
        model_launch = item(
            "Enterprise AI model API launches with faster coding-agent tools",
            "The announcement covers model availability, API features, benchmarks, and cloud deployment options.",
            "enterprise-ai",
        )

        self.assertFalse(is_candidate_relevant_for_slot(model_launch, "fde"))

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
        enterprise_governance = item(
            "Enterprise AI agent governance for customer rollouts",
            "Customer-facing AI agents need policy controls, audit logs, evals, and phased production rollout.",
            "discussion-fde",
        )

        self.assertTrue(is_candidate_relevant_for_slot(production_patterns, "fde"))
        self.assertTrue(is_candidate_relevant_for_slot(enterprise_governance, "fde"))


if __name__ == "__main__":
    unittest.main()
