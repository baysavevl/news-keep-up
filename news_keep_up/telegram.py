from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .models import Settings

TELEGRAM_MESSAGE_LIMIT = 4096


def send_telegram_message(
    text: str,
    settings: Settings,
    chat_id: str | None = None,
    reply_to_message_id: int | None = None,
) -> None:
    target_chat_id = chat_id or settings.telegram_chat_id
    if not settings.telegram_bot_token or not target_chat_id:
        raise RuntimeError("Telegram is not configured: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    for chunk in _message_chunks(text):
        body = {
            "chat_id": target_chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
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


def set_telegram_chat_photo(settings: Settings, photo_path: Path | str, chat_id: str | None = None) -> None:
    target_chat_id = chat_id or settings.telegram_chat_id
    if not settings.telegram_bot_token or not target_chat_id:
        raise RuntimeError("Telegram is not configured: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    path = Path(photo_path)
    payload = _telegram_multipart_request(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/setChatPhoto",
        fields={"chat_id": target_chat_id},
        files={"photo": path},
    )
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram setChatPhoto failed: {payload}")


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


def _telegram_multipart_request(
    url: str,
    fields: dict[str, str],
    files: dict[str, Path],
    timeout: int = 20,
) -> dict:
    boundary = f"----newskeepup{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for name, path in files.items():
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram request failed: {exc.code} {detail}") from exc


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
