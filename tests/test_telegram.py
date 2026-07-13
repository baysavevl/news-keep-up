import json
import unittest
from unittest.mock import patch

from news_keep_up.models import Settings
from news_keep_up.telegram import send_telegram_message


class TelegramTest(unittest.TestCase):
    def test_send_telegram_message_uses_html_parse_mode(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return Response()

        settings = Settings(telegram_bot_token="token", telegram_chat_id="123")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            send_telegram_message("<b>Digest</b>", settings)

        self.assertEqual(captured["body"]["parse_mode"], "HTML")
        self.assertEqual(captured["body"]["text"], "<b>Digest</b>")
        self.assertTrue(captured["body"]["disable_web_page_preview"])
        self.assertEqual(captured["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
