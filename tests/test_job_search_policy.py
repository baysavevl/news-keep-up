import json
import tempfile
import unittest
from pathlib import Path

from news_keep_up.job_search_policy import load_job_search_policy


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


if __name__ == "__main__":
    unittest.main()
