import unittest

from news_keep_up.gemini import (
    build_digest_review_prompt,
    build_prompt,
    fallback_enrichment,
    parse_digest_review_response,
    parse_enrichment_response,
)
from news_keep_up.models import CandidateItem, DigestCandidate, Enrichment


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


def make_candidate(item_id: int, title: str, source_category: str = "ai-engineering") -> DigestCandidate:
    return DigestCandidate(
        item_id=item_id,
        title=title,
        url=f"https://example.com/{item_id}",
        source_name="Example Source",
        source_category=source_category,
        published_at="2026-07-13T03:00:00+00:00",
        fetched_at="2026-07-13T03:01:00+00:00",
        enrichment=Enrichment(
            model="gemini-test",
            relevance_score=70,
            category=source_category,
            topic="coding-agents",
            icon="🤖",
            title_vi="",
            summary="Initial summary.",
            why_it_matters="Initial impact.",
            takeaway_vi="Takeaway.",
            should_send=True,
        ),
    )


class GeminiTest(unittest.TestCase):
    def test_build_prompt_requests_vietnamese_title_translation(self):
        prompt = build_prompt(make_item())

        self.assertIn("title_vi", prompt)
        self.assertIn("Vietnamese title translation", prompt)
        self.assertIn("Agentic engineering patterns", prompt)
        self.assertIn("key idea", prompt.lower())
        self.assertIn("highlights", prompt.lower())
        self.assertIn("3-5 concrete highlights", prompt.lower())
        self.assertIn("do not copy the article title", prompt.lower())
        self.assertIn("popularity", prompt.lower())
        self.assertIn("importance", prompt.lower())
        self.assertIn("source trust", prompt.lower())
        self.assertIn("impact", prompt.lower())
        self.assertIn("reject generic ai roundups", prompt.lower())

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

    def test_digest_review_prompt_requests_batch_ranking_and_formatting(self):
        prompt = build_digest_review_prompt(
            "fde",
            [
                make_candidate(1, "Generic model launch"),
                make_candidate(2, "Customer rollout with eval gates", "fde-industry"),
            ],
            max_items=8,
        )

        self.assertIn("rank", prompt.lower())
        self.assertIn("impact", prompt.lower())
        self.assertIn("emoji", prompt.lower())
        self.assertIn("3-5 specific highlights", prompt.lower())
        self.assertIn("do not repeat the title", prompt.lower())
        self.assertIn("Forward Deployed Engineer", prompt)
        self.assertIn('"item_id": 2', prompt)

    def test_parse_digest_review_response_updates_scores_and_filters_items(self):
        rows = [
            make_candidate(1, "Generic model launch"),
            make_candidate(2, "Customer rollout with eval gates", "fde-industry"),
        ]
        response = """```json
        {
          "items": [
            {
              "item_id": 2,
              "rank": 1,
              "relevance_score": 96,
              "category": "field-delivery",
              "topic": "customer-rollout",
              "icon": "🧭",
              "summary": "Key idea: rollout needs eval gates. The deployment note explains customer acceptance criteria.",
              "why_it_matters": "Impact: FDEs can turn this into a launch gate.",
              "takeaway_vi": "Ưu tiên eval gate trước rollout.",
              "should_send": true
            },
            {
              "item_id": 1,
              "rank": 9,
              "relevance_score": 30,
              "category": "generic-ai",
              "topic": "model-news",
              "icon": "🧠",
              "summary": "Generic announcement.",
              "why_it_matters": "Low FDE impact.",
              "takeaway_vi": "Bỏ qua nếu không có rollout.",
              "should_send": false
            }
          ]
        }
        ```"""

        reviewed = parse_digest_review_response(response, rows, "gemini-review")

        self.assertEqual(reviewed[2].relevance_score, 96)
        self.assertEqual(reviewed[2].icon, "🧭")
        self.assertTrue(reviewed[2].should_send)
        self.assertFalse(reviewed[1].should_send)


if __name__ == "__main__":
    unittest.main()
