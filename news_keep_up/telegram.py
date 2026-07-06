from __future__ import annotations

import json
import urllib.error
import urllib.request

from .models import Settings


def send_telegram_message(text: str, settings: Settings) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("Telegram is not configured: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    body = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram sendMessage failed: {exc.code} {detail}") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {payload}")
