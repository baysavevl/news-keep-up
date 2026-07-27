import unittest

from news_keep_up.gemini import (
    build_job_classification_prompt,
    build_digest_review_prompt,
    build_prompt,
    fallback_enrichment,
    fallback_job_opportunities,
    parse_job_classification_response,
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
            max_items=5,
        )

        self.assertIn("rank", prompt.lower())
        self.assertIn("impact", prompt.lower())
        self.assertIn("emoji", prompt.lower())
        self.assertIn("exactly 5 specific highlights", prompt.lower())
        self.assertIn("no separate key idea", prompt.lower())
        self.assertIn("do not repeat the title", prompt.lower())
        self.assertIn("Forward Deployed Engineer", prompt)
        self.assertIn("Before marking should_send=true", prompt)
        self.assertIn("personal research triage", prompt)
        self.assertIn("arXiv/news digest tools", prompt)
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

    def test_job_classification_prompt_is_compact_and_alerts_non_closed_non_reject(self):
        prompt = build_job_classification_prompt(
            [(7, make_item())],
            crawled_at="2026-07-27",
        )

        self.assertIn("Ho Chi Minh City", prompt)
        self.assertIn("non-Reject", prompt)
        self.assertIn("status is not closed", prompt)
        self.assertIn("should_alert=true", prompt)
        self.assertIn("Do not assume APAC", prompt)
        self.assertIn('"candidate_id": 7', prompt)
        self.assertLess(len(prompt), 7000)

    def test_parse_job_classification_response_sets_alert_for_high_and_medium(self):
        candidate = CandidateItem(
            source_name="Bing FDE Search",
            source_kind="rss",
            source_category="fde-job-search",
            title="Wonderful is hiring a Forward Deployed Engineer in Vietnam",
            url="https://example.com/jobs/wonderful-fde",
            canonical_url="https://example.com/jobs/wonderful-fde",
            summary="Official listing says Vietnam remote candidates can apply.",
            fingerprint="abc123",
        )
        response = """```json
        {
          "items": [
            {
              "candidate_id": 7,
              "id": "wonderful-forward-deployed-engineer-vietnam",
              "priority": "Medium",
              "company": "Wonderful",
              "role_title": "Forward Deployed Engineer",
              "category": "Exact FDE Role",
              "location": "Vietnam",
              "remote_policy": "Remote Vietnam",
              "vietnam_eligibility": "explicit_yes",
              "evidence_type": "Hard",
              "status": "open",
              "posted_date": "",
              "source_type": "ATS",
              "source_url": "https://example.com/jobs/wonderful-fde",
              "apply_url": "https://example.com/jobs/wonderful-fde/apply",
              "contact_person": "",
              "contact_url": "",
              "why_it_fits": "Exact FDE role with Vietnam eligibility.",
              "what_to_verify": ["Compensation range"],
              "required_seniority": "Senior",
              "required_skills": ["LLM", "customer deployment"],
              "domain": ["enterprise AI"],
              "company_expansion_signal": "",
              "linkedin_post_signal": "",
              "recommended_action": "apply_now",
              "outreach_angle": "Lead with customer-facing AI deployment work.",
              "confidence_score": 82,
              "should_alert": false
            }
          ]
        }
        ```"""

        opportunities = parse_job_classification_response(response, {7: candidate}, "gemini-test", "2026-07-27")

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].priority, "Medium")
        self.assertTrue(opportunities[0].should_alert)
        self.assertEqual(opportunities[0].source_fingerprint, "abc123")
        self.assertIn("priority=Medium", opportunities[0].alert_fingerprint)

    def test_parse_job_classification_response_sets_alert_for_low_watch_state(self):
        candidate = CandidateItem(
            source_name="Bing FDE Search",
            source_kind="rss",
            source_category="fde-job-search",
            title="APAC AI deployment company expanding field engineering",
            url="https://example.com/jobs/watch",
            canonical_url="https://example.com/jobs/watch",
            summary="No exact open role yet, but there is a relevant APAC field engineering signal.",
            fingerprint="watch123",
        )
        response = """```json
        {
          "items": [
            {
              "candidate_id": 8,
              "id": "apac-ai-deployment-watch",
              "priority": "Low",
              "company": "Example AI",
              "role_title": "AI Deployment Hiring Signal",
              "category": "Watchlist Company",
              "location": "Remote APAC",
              "remote_policy": "Remote APAC",
              "vietnam_eligibility": "verify",
              "evidence_type": "Weak",
              "status": "watch",
              "posted_date": "",
              "source_type": "company_blog",
              "source_url": "https://example.com/jobs/watch",
              "apply_url": "",
              "contact_person": "",
              "contact_url": "",
              "why_it_fits": "Weak but relevant FDE-adjacent expansion signal.",
              "what_to_verify": ["Vietnam-based remote eligibility"],
              "required_seniority": "",
              "required_skills": [],
              "domain": ["enterprise AI"],
              "company_expansion_signal": "APAC field engineering expansion.",
              "linkedin_post_signal": "",
              "recommended_action": "set_alert",
              "outreach_angle": "",
              "confidence_score": 25,
              "should_alert": false
            }
          ]
        }
        ```"""

        opportunities = parse_job_classification_response(response, {8: candidate}, "gemini-test", "2026-07-27")

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].priority, "Low")
        self.assertEqual(opportunities[0].status, "watch")
        self.assertTrue(opportunities[0].should_alert)

    def test_fallback_job_opportunities_uses_parsed_job_board_metadata(self):
        candidate = CandidateItem(
            source_name="FWDDeploy Remote Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Founding Forward Deployed Engineer",
            url="https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
            canonical_url="https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
            summary="Company: Clera. Location: Remote APAC. Employment: Full-time. Posted: 6 days.",
            fingerprint="fde-card-1",
            raw={
                "company": "Clera",
                "location": "Remote APAC",
                "remote_policy": "Remote",
                "employment_type": "Full-time",
                "posted_age": "6 days",
                "source_type": "job_board",
            },
        )

        opportunities = fallback_job_opportunities([(42, candidate)], "2026-07-27")

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].company, "Clera")
        self.assertEqual(opportunities[0].role_title, "Founding Forward Deployed Engineer")
        self.assertEqual(opportunities[0].location, "Remote APAC")
        self.assertEqual(opportunities[0].remote_policy, "Remote")
        self.assertEqual(opportunities[0].status, "likely_open")
        self.assertGreaterEqual(opportunities[0].confidence_score, 70)
        self.assertIn("Clera", opportunities[0].why_it_fits)

    def test_fallback_job_opportunities_rejects_onsite_non_vietnam_roles(self):
        candidate = CandidateItem(
            source_name="FWDDeploy All Jobs",
            source_kind="html",
            source_category="fde-job-board",
            title="Senior Forward Deployed Engineer",
            url="https://www.fwddeploy.com/jobs/senior-forward-deployed-engineer-68be6b58",
            canonical_url="https://www.fwddeploy.com/jobs/senior-forward-deployed-engineer-68be6b58",
            summary="Company: Handshake. Location: On-site Bengaluru, Karnataka, India. Employment: Full-time.",
            fingerprint="fde-india-1",
            raw={
                "company": "Handshake",
                "location": "On-site Bengaluru, Karnataka, India",
                "employment_type": "Full-time",
                "source_type": "job_board",
            },
        )

        self.assertEqual(fallback_job_opportunities([(43, candidate)], "2026-07-27"), [])


if __name__ == "__main__":
    unittest.main()
