import json
import unittest
from unittest.mock import patch

from news_keep_up.models import Settings
from news_keep_up.telegram import answer_telegram_callback, send_telegram_message


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

    def test_send_telegram_message_includes_markup_and_returns_results(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 99}}'

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return Response()

        markup = {"inline_keyboard": [[{"text": "1 👍", "callback_data": "i1|1|u"}]]}
        settings = Settings(telegram_bot_token="token", telegram_chat_id="123")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            results = send_telegram_message("Digest", settings, reply_markup=markup)

        self.assertEqual(captured["body"]["reply_markup"], markup)
        self.assertEqual(results, [{"message_id": 99}])

    def test_marked_up_message_refuses_to_split_before_network_call(self):
        settings = Settings(telegram_bot_token="token", telegram_chat_id="123")

        with patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError):
                send_telegram_message(
                    "x" * 4097,
                    settings,
                    reply_markup={"inline_keyboard": []},
                )

        urlopen.assert_not_called()

    def test_answer_callback_uses_callback_endpoint_and_truncates_toast(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": true}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return Response()

        settings = Settings(telegram_bot_token="token", telegram_chat_id="123")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            answer_telegram_callback("cb-1", "x" * 250, settings, show_alert=True)

        self.assertTrue(captured["url"].endswith("/answerCallbackQuery"))
        self.assertEqual(captured["body"]["callback_query_id"], "cb-1")
        self.assertEqual(len(captured["body"]["text"]), 200)
        self.assertTrue(captured["body"]["show_alert"])

    def test_send_telegram_message_splits_long_messages(self):
        captured = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return Response()

        item_block = "<b>1. Item</b>\nÝ chính: " + ("x" * 700)
        message = "\n\n".join(["<b>FDE Digest</b>"] + [item_block.replace("1.", f"{index}.") for index in range(1, 9)])
        settings = Settings(telegram_bot_token="token", telegram_chat_id="123")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            send_telegram_message(message, settings)

        self.assertGreater(len(captured), 1)
        self.assertEqual("".join(body["text"] for body in captured).replace("\n\n", ""), message.replace("\n\n", ""))
        self.assertTrue(all(len(body["text"]) <= 4096 for body in captured))
        self.assertTrue(all(body["parse_mode"] == "HTML" for body in captured))


if __name__ == "__main__":
    unittest.main()
