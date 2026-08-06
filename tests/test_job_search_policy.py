import json
import tempfile
import unittest
from pathlib import Path

from news_keep_up.job_search_policy import evaluate_job_text, load_job_search_policy


class JobSearchPolicyTest(unittest.TestCase):
    def test_default_policy_has_approved_role_order_and_decisions(self):
        policy = load_job_search_policy()

        self.assertEqual(
            [family.id for family in policy.role_families],
            [
                "forward_deployed_engineering",
                "solutions_engineering_architecture",
                "ai_consulting",
                "technical_presales",
                "technical_account_management",
            ],
        )
        self.assertEqual(
            policy.decisions,
            ("APPLY_NOW", "VERIFY_FIRST", "DM_FIRST", "WATCH", "REJECT"),
        )
        self.assertIn("enterprise saas", policy.domain_terms)
        self.assertEqual(policy.base_location, "Ho Chi Minh City, Vietnam")

    def test_policy_rejects_missing_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-policy.json"
            path.write_text(json.dumps({"version": 1}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing policy keys"):
                load_job_search_policy(path)

    def test_policy_rejects_duplicate_role_ids_and_priorities(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = json.loads(
                Path("config/job_search_policy.json").read_text(encoding="utf-8")
            )
            raw["role_families"][1]["id"] = raw["role_families"][0]["id"]
            raw["role_families"][1]["priority"] = raw["role_families"][0][
                "priority"
            ]
            path = Path(tmp) / "duplicate-policy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unique"):
                load_job_search_policy(path)

    def test_all_approved_role_families_match(self):
        cases = {
            "Senior Forward Deployed Engineer": "Forward Deployed Engineering",
            "Staff Solutions Architect": "Solutions Engineering and Architecture",
            "Senior AI Implementation Consultant": "AI Consulting",
            "Lead Presales Engineer": "Technical Presales",
            "Senior Technical Account Manager": "Technical Account Management",
        }

        for title, expected in cases.items():
            with self.subTest(title=title):
                match = evaluate_job_text(
                    title,
                    "Enterprise SaaS customer work with architecture, API integration, "
                    "demo, PoC, implementation guidance, troubleshooting, and production "
                    "deployment.",
                )
                self.assertTrue(match.is_eligible, match.reject_reason)
                self.assertEqual(match.role_family_label, expected)

    def test_pure_quota_presales_and_tam_are_rejected_without_technical_evidence(self):
        presales = evaluate_job_text(
            "Senior Presales Engineer",
            "Enterprise SaaS quota carrying, cold calling, prospecting, and pipeline "
            "ownership.",
        )
        tam = evaluate_job_text(
            "Technical Account Manager",
            "Enterprise SaaS renewals, upsell, relationship management, and quota "
            "carrying.",
        )

        self.assertEqual(
            presales.reject_reason, "insufficient-technical-evidence"
        )
        self.assertEqual(tam.reject_reason, "insufficient-technical-evidence")

    def test_unknown_seniority_is_verify_not_reject(self):
        match = evaluate_job_text(
            "Solutions Engineer",
            "Enterprise SaaS architecture, demo, API integration, and customer "
            "implementation.",
        )

        self.assertTrue(match.is_eligible)
        self.assertEqual(match.seniority, "unknown")

    def test_junior_manager_and_non_target_engineering_roles_are_rejected(self):
        self.assertEqual(
            evaluate_job_text(
                "Junior Solutions Engineer",
                "Enterprise SaaS API integration and demos.",
            ).reject_reason,
            "disallowed-seniority",
        )
        self.assertEqual(
            evaluate_job_text(
                "Solutions Engineering Manager",
                "Enterprise SaaS API integration and demos.",
            ).reject_reason,
            "disallowed-seniority",
        )
        self.assertEqual(
            evaluate_job_text(
                "Senior Backend Engineer",
                "Enterprise AI platform APIs.",
            ).reject_reason,
            "offtopic-title",
        )


if __name__ == "__main__":
    unittest.main()
