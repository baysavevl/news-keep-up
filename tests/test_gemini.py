import unittest

from news_keep_up.gemini import build_prompt, fallback_enrichment, parse_enrichment_response
from news_keep_up.models import CandidateItem


def make_item() -> CandidateItem:
    return CandidateItem(
        source_name="Simon Willison",
        source_kind="rss",
        source_category="agentic-engineering",
        title="Agentic engineering patterns",
        url="https://example.com/agentic",
        canonical_url="https://example.com/agentic",
        summary="Patterns for using coding agents safely in delivery teams.",
    )


class GeminiTest(unittest.TestCase):
    def test_build_prompt_requests_vietnamese_title_translation(self):
        prompt = build_prompt(make_item())

        self.assertIn("title_vi", prompt)
        self.assertIn("Vietnamese title translation", prompt)
        self.assertIn("Agentic engineering patterns", prompt)
        self.assertIn("key idea", prompt.lower())
        self.assertIn("highlights", prompt.lower())
        self.assertIn("popularity", prompt.lower())
        self.assertIn("importance", prompt.lower())

    def test_parse_enrichment_response_extracts_json_and_clamps_score(self):
        response = """```json
        {
          "relevance_score": 123,
          "category": "ai-engineering",
          "topic": "coding-agents",
          "icon": "AI",
          "title_vi": "Các mẫu kỹ thuật agentic",
          "summary": "The article explains repeatable patterns for agent-assisted engineering.",
          "why_it_matters": "It helps FDEs structure coding-agent workflows with safer handoffs.",
          "takeaway_vi": "Nên chuẩn hóa cách giao việc cho coding agent.",
          "should_send": true
        }
        ```"""

        enrichment = parse_enrichment_response(response, make_item(), "gemini-test")

        self.assertEqual(enrichment.relevance_score, 100)
        self.assertEqual(enrichment.title_vi, "Các mẫu kỹ thuật agentic")
        self.assertEqual(enrichment.topic, "coding-agents")
        self.assertTrue(enrichment.should_send)

    def test_fallback_enrichment_keeps_item_usable_without_model(self):
        enrichment = fallback_enrichment(make_item(), "no-key")

        self.assertEqual(enrichment.model, "fallback:no-key")
        self.assertIn("Agentic engineering patterns", enrichment.title_vi)
        self.assertIn("Patterns for using coding agents", enrichment.summary)
        self.assertTrue(enrichment.should_send)


if __name__ == "__main__":
    unittest.main()
