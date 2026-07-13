import json
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path

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
        self.assertEqual(settings.backfill_lookback_days, 7)

    def test_load_settings_accepts_env_overrides(self):
        settings = load_settings({
            "GEMINI_API_KEY": "gemini-key",
            "TELEGRAM_BOT_TOKEN": "tg-token",
            "TELEGRAM_CHAT_ID": "123",
            "MAX_LLM_ITEMS_PER_RUN": "7",
            "MAX_LLM_CALLS_PER_DAY": "9",
            "DB_PATH": "/tmp/custom.db",
        })

        self.assertEqual(settings.gemini_api_key, "gemini-key")
        self.assertEqual(settings.telegram_bot_token, "tg-token")
        self.assertEqual(settings.telegram_chat_id, "123")
        self.assertEqual(settings.max_llm_items_per_run, 7)
        self.assertEqual(settings.max_llm_calls_per_day, 9)
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

    def test_fde_sources_include_at_least_50_trusted_enabled_sources(self):
        sources = load_sources("config/fde_sources.json")

        self.assertGreaterEqual(len(sources), 50)
        self.assertTrue(all(source.enabled for source in sources))
        self.assertTrue(all(source.category.startswith(("fde", "ai", "enterprise", "field", "discussion")) for source in sources))


if __name__ == "__main__":
    unittest.main()
