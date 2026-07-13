from __future__ import annotations

import json
import urllib.error
import urllib.request

from .models import Settings

TELEGRAM_MESSAGE_LIMIT = 4096


def send_telegram_message(text: str, settings: Settings) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("Telegram is not configured: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    for chunk in _message_chunks(text):
        body = {
            "chat_id": settings.telegram_chat_id,
            "text": chunk,
            "parse_mode": "HTML",
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


def _message_chunks(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        separator = "\n\n" if current else ""
        candidate = f"{current}{separator}{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(block) <= limit:
            current = block
            continue
        chunks.extend(_line_chunks(block, limit))

    if current:
        chunks.append(current)
    return chunks


def _line_chunks(block: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in block.splitlines():
        separator = "\n" if current else ""
        candidate = f"{current}{separator}{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks
