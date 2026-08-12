import json
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from urllib.parse import urlparse

from news_keep_up.config import load_settings, load_sources


class ConfigTest(unittest.TestCase):
    def test_load_settings_uses_cost_control_defaults(self):
        settings = load_settings({})

        self.assertEqual(settings.gemini_model, "gemini-2.5-flash-lite")
        self.assertEqual(settings.gemini_fallback_model, "gemini-2.5-flash")
        self.assertEqual(settings.max_llm_items_per_run, 20)
        self.assertEqual(settings.max_llm_calls_per_day, 40)
        self.assertEqual(settings.max_candidates_per_source, 10)
        self.assertEqual(settings.min_relevance_score, 65)
        self.assertEqual(settings.backfill_lookback_days, 10)
        self.assertEqual(settings.source_fetch_timeout_seconds, 5)
        self.assertEqual(settings.max_source_workers, 12)

    def test_load_settings_accepts_env_overrides(self):
        settings = load_settings({
            "GEMINI_API_KEY": "gemini-key",
            "TELEGRAM_BOT_TOKEN": "tg-token",
            "TELEGRAM_CHAT_ID": "123",
            "MAX_LLM_ITEMS_PER_RUN": "7",
            "MAX_LLM_CALLS_PER_DAY": "9",
            "SOURCE_FETCH_TIMEOUT_SECONDS": "3",
            "MAX_SOURCE_WORKERS": "4",
            "DB_PATH": "/tmp/custom.db",
        })

        self.assertEqual(settings.gemini_api_key, "gemini-key")
        self.assertEqual(settings.telegram_bot_token, "tg-token")
        self.assertEqual(settings.telegram_chat_id, "123")
        self.assertEqual(settings.max_llm_items_per_run, 7)
        self.assertEqual(settings.max_llm_calls_per_day, 9)
        self.assertEqual(settings.source_fetch_timeout_seconds, 3)
        self.assertEqual(settings.max_source_workers, 4)
        self.assertEqual(settings.db_path, Path("/tmp/custom.db"))

    def test_load_settings_accepts_base64_secret_fallbacks(self):
        settings = load_settings({
            "GEMINI_API_KEY_B64": b64encode(b"gemini-key").decode("ascii"),
            "TELEGRAM_BOT_TOKEN_B64": b64encode(b"tg-token").decode("ascii"),
            "TELEGRAM_CHAT_ID": "123",
        })

        self.assertEqual(settings.gemini_api_key, "gemini-key")
        self.assertEqual(settings.telegram_bot_token, "tg-token")
        self.assertEqual(settings.telegram_chat_id, "123")

    def test_load_settings_accepts_profile_specific_telegram_env(self):
        settings = load_settings({
            "GEMINI_API_KEY": "gemini-key",
            "TELEGRAM_BOT_TOKEN": "default-token",
            "TELEGRAM_CHAT_ID": "default-chat",
            "FDE_TELEGRAM_BOT_TOKEN_B64": b64encode(b"fde-token").decode("ascii"),
            "FDE_TELEGRAM_CHAT_ID": "-100123",
        }, env_prefix="FDE")

        self.assertEqual(settings.gemini_api_key, "gemini-key")
        self.assertEqual(settings.telegram_bot_token, "fde-token")
        self.assertEqual(settings.telegram_chat_id, "-100123")

    def test_profile_specific_telegram_env_does_not_mix_default_chat(self):
        settings = load_settings({
            "TELEGRAM_BOT_TOKEN": "default-token",
            "TELEGRAM_CHAT_ID": "default-chat",
            "FDE_TELEGRAM_BOT_TOKEN_B64": b64encode(b"fde-token").decode("ascii"),
        }, env_prefix="FDE")

        self.assertEqual(settings.telegram_bot_token, "fde-token")
        self.assertEqual(settings.telegram_chat_id, "")

    def test_load_sources_filters_disabled_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "sources.json"
            source_path.write_text(json.dumps([
                {
                    "name": "Latent Space",
                    "type": "rss",
                    "url": "https://www.latent.space/feed",
                    "category": "ai-engineering",
                    "enabled": True,
                },
                {
                    "name": "Disabled",
                    "type": "rss",
                    "url": "https://example.com/feed",
                    "category": "ignore",
                    "enabled": False,
                },
            ]), encoding="utf-8")

            sources = load_sources(source_path)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "Latent Space")
        self.assertEqual(sources[0].kind, "rss")

    def test_fde_sources_include_at_least_150_enabled_sources(self):
        sources = load_sources("config/fde_sources.json")

        self.assertGreaterEqual(len(sources), 150)
        self.assertTrue(all(source.enabled for source in sources))
        self.assertTrue(all(source.category.startswith(("fde", "ai", "enterprise", "field", "discussion")) for source in sources))

    def test_fde_sources_include_validated_trusted_voice_expansion(self):
        sources = load_sources("config/fde_sources.json")
        names = {source.name for source in sources}
        expected_names = {
            "AI Realized Now",
            "AI Regeneration",
            "AI Supremacy",
            "AWS APN Blog",
            "AWS Startups Blog",
            "About Amazon AWS News",
            "Anthony Maio",
            "Barrett Restore",
            "Ben Sykes Enterprise AI",
            "Enterprise AI Weekly",
            "Enterprise Context Management",
            "Forward Feed",
            "Generative AI Revolution Medium",
            "Hands On AI Agent Mastery",
            "Last Week in AI",
            "Operational AI",
            "Product Impact Pod",
            "The AI Economy",
            "The Gradient",
            "Understanding AI",
        }

        self.assertGreaterEqual(len(names.intersection(expected_names)), len(expected_names))
        self.assertGreaterEqual(len(sources), 120)

    def test_fde_job_sources_include_upwork_search(self):
        sources = load_sources("config/fde_job_sources.json")
        names = {source.name for source in sources}

        self.assertIn("Bing Upwork FDE AI Deployment", names)
        self.assertIn("Upwork Artificial Intelligence Jobs", names)
        self.assertIn("FWDDeploy Remote Jobs", names)

    def test_fde_job_sources_cover_ai_consulting_and_enterprise_saas(self):
        sources = load_sources("config/fde_job_sources.json")
        names = {source.name for source in sources}

        self.assertIn("Bing AI Consultant APAC Remote", names)
        self.assertIn("Bing Enterprise SaaS Solutioning APAC", names)
        self.assertIn("Bing LinkedIn Enterprise SaaS Technical Hiring", names)

    def test_fde_job_source_catalog_has_340_unique_enabled_valid_entries(self):
        rows = json.loads(Path("config/fde_job_sources.json").read_text(encoding="utf-8"))
        sources = load_sources("config/fde_job_sources.json")

        self.assertEqual(len(rows), 340)
        self.assertEqual(len(sources), 340)
        self.assertEqual(len({row["name"].strip().casefold() for row in rows}), 340)
        self.assertEqual(len({row["url"].strip() for row in rows}), 340)

        allowed_kinds = {"rss", "json", "html", "hackernews"}
        allowed_source_types = {
            "ATS",
            "LinkedIn_post",
            "aggregator",
            "community",
            "job_board",
            "official_career_page",
            "social",
        }
        list_metadata_fields = {
            "text_exclude_any",
            "text_include_any",
            "title_exclude_any",
            "title_include_any",
            "url_exclude_any",
            "url_host_include_any",
            "url_include_any",
        }
        for row in rows:
            self.assertTrue(row["enabled"], row["name"])
            self.assertTrue(row["name"].strip())
            self.assertIn(row["type"], allowed_kinds, row["name"])
            self.assertTrue(row["category"].strip(), row["name"])
            self.assertIn(row["source_type"], allowed_source_types, row["name"])
            parsed_url = urlparse(row["url"])
            self.assertEqual(parsed_url.scheme, "https", row["name"])
            self.assertTrue(parsed_url.netloc, row["name"])
            for field in list_metadata_fields.intersection(row):
                self.assertIsInstance(row[field], list, f"{row['name']}:{field}")
                self.assertTrue(row[field], f"{row['name']}:{field}")
                self.assertTrue(
                    all(isinstance(value, str) and value.strip() for value in row[field]),
                    f"{row['name']}:{field}",
                )

    def test_fde_job_source_catalog_covers_all_source_categories_and_role_families(self):
        rows = json.loads(Path("config/fde_job_sources.json").read_text(encoding="utf-8"))
        category_groups = {
            "official company careers": {"company-careers", "company-careers-index"},
            "ATS searches": {"ats-direct-job", "ats-index-search"},
            "APAC and global-remote boards": {
                "apac-job-board",
                "fde-job-board",
                "freelance-job-board",
                "remote-job-board",
            },
            "hidden hiring and community": {
                "community-hiring-signal",
                "linkedin-hidden-hiring-search",
            },
        }
        minimum_category_counts = {
            "official company careers": 60,
            "ATS searches": 115,
            "APAC and global-remote boards": 90,
            "hidden hiring and community": 50,
        }
        for label, categories in category_groups.items():
            covered = sum(row["category"] in categories for row in rows)
            self.assertGreaterEqual(covered, minimum_category_counts[label], label)

        role_family_aliases = {
            "Forward Deployed Engineering": {
                "forward deployed engineer",
                "forward-deployed engineer",
                "forward deployment engineer",
                "deployment strategist",
                "ai deployment engineer",
                "fde",
            },
            "Solutions Engineering and Architecture": {
                "solution engineer",
                "solutions engineer",
                "customer engineer",
                "field engineer",
                "solution architect",
                "solutions architect",
                "customer success architect",
                "delivery solutions architect",
            },
            "AI Consulting": {
                "ai consultant",
                "genai consultant",
                "technical consultant",
                "implementation consultant",
                "ai implementation specialist",
                "ai automation specialist",
            },
            "Technical Presales": {
                "presales engineer",
                "pre-sales engineer",
                "sales engineer",
                "solutions consultant",
                "solution consultant",
            },
            "Technical Account Management": {
                "technical account manager",
                "technical success manager",
                "customer success engineer",
            },
        }
        for label, aliases in role_family_aliases.items():
            covered = sum(
                bool(aliases.intersection({value.casefold() for value in row.get("title_include_any", [])}))
                for row in rows
            )
            self.assertGreaterEqual(covered, 30, label)

    def test_known_blocked_job_boards_use_indexed_rss_searches(self):
        sources = load_sources("config/fde_job_sources.json")
        by_name = {source.name: source for source in sources}
        blocked_direct_names = {
            "Indeed Singapore FDE Jobs",
            "Upwork Artificial Intelligence Jobs",
            "Upwork Automation Jobs",
            "Upwork AI Automation Freelance Jobs",
            "Upwork AI Integration Freelance Jobs",
            "Upwork ChatGPT Freelance Jobs",
            "Upwork OpenAI Freelance Jobs",
            "Upwork Machine Learning Freelance Jobs",
            "Upwork n8n Automation Freelance Jobs",
        }

        self.assertEqual(set(by_name).intersection(blocked_direct_names), blocked_direct_names)
        for name in blocked_direct_names:
            source = by_name[name]
            self.assertEqual(source.kind, "rss")
            self.assertIn("bing.com/search", source.url)

    def test_fde_job_sources_include_freelance_boards_for_cron(self):
        sources = load_sources("config/fde_job_sources.json")
        by_name = {source.name: source for source in sources}
        expected_hosts = {
            "Freelancer Artificial Intelligence Jobs": "freelancer.com",
            "Freelancer Automation Jobs": "freelancer.com",
            "Guru AI Machine Learning Jobs": "guru.com",
            "PeoplePerHour AI Freelance Jobs": "peopleperhour.com",
            "Arc AI Remote Jobs": "arc.dev",
            "Braintrust AI Jobs": "usebraintrust.com",
            "RemoteOK AI API Jobs": "remoteok.com",
            "Remotive AI Remote Jobs": "remotive.com",
            "We Work Remotely All Jobs RSS": "weworkremotely.com",
        }

        self.assertEqual(set(by_name).intersection(expected_hosts), set(expected_hosts))
        for name, expected_host in expected_hosts.items():
            source = by_name[name]
            self.assertTrue(source.enabled)
            self.assertIn(source.kind, {"html", "json", "rss"})
            self.assertIn(expected_host, source.metadata["url_host_include_any"])
            self.assertEqual(source.metadata["remote_policy"], "Remote")
            self.assertEqual(source.metadata["source_type"], "job_board")
            self.assertTrue(source.metadata["text_include_any"])

    def test_fde_job_sources_include_stable_ai_job_apis_and_boards(self):
        sources = load_sources("config/fde_job_sources.json")
        by_name = {source.name: source for source in sources}
        expected = {
            "Jobicy Developer Remote Jobs": ("json", "jobicy.com"),
            "Jobicy Python Remote Jobs": ("json", "jobicy.com"),
            "Jobicy Machine Learning Remote Jobs": ("json", "jobicy.com"),
            "AIJobs.net Remote AI Jobs": ("html", "aijobs.net"),
            "Working Nomads AI Jobs": ("html", "workingnomads.com"),
        }

        self.assertEqual(set(by_name).intersection(expected), set(expected))
        for name, (kind, host) in expected.items():
            source = by_name[name]
            self.assertTrue(source.enabled)
            self.assertEqual(source.kind, kind)
            self.assertEqual(source.category, "remote-job-board")
            if name == "AIJobs.net Remote AI Jobs":
                self.assertNotIn("remote_policy", source.metadata)
            else:
                self.assertEqual(source.metadata["remote_policy"], "Remote")
            self.assertIn(host, source.metadata["url_host_include_any"])
            self.assertTrue(source.metadata["text_include_any"])

    def test_fde_job_sources_include_remote_job_boards_for_cron(self):
        sources = load_sources("config/fde_job_sources.json")
        by_name = {source.name: source for source in sources}
        expected_kinds = {
            "Wellfound Remote Jobs": "rss",
            "RemoteOK API Jobs": "json",
            "We Work Remotely Programming Jobs RSS": "rss",
            "Jobspresso Remote Work RSS": "rss",
            "FlexJobs AI Remote Jobs": "rss",
            "Remotive Software Development API Jobs": "json",
            "Remote.co Developer Jobs": "rss",
            "Himalayas AI Remote Jobs": "rss",
            "Working Nomads Remote Tech Jobs": "html",
            "NoDesk Remote Jobs": "html",
        }

        self.assertEqual(set(by_name).intersection(expected_kinds), set(expected_kinds))
        for name, expected_kind in expected_kinds.items():
            source = by_name[name]
            self.assertTrue(source.enabled)
            self.assertEqual(source.kind, expected_kind)
            self.assertEqual(source.category, "remote-job-board")
            self.assertEqual(source.metadata["source_type"], "job_board")
            self.assertTrue(source.metadata["url_host_include_any"])
            self.assertTrue(source.metadata["text_include_any"])

    def test_engineer_sources_include_at_least_150_enabled_sources(self):
        sources = load_sources("config/sources.json")

        self.assertGreaterEqual(len(sources), 150)
        self.assertTrue(all(source.enabled for source in sources))
        self.assertTrue(all(source.category.startswith((
            "ai",
            "agent",
            "developer",
            "discussion",
            "product",
            "software",
            "systems",
            "security",
            "data",
            "infra",
            "llm",
        )) for source in sources))


if __name__ == "__main__":
    unittest.main()
