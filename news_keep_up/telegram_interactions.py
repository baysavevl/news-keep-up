from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .interaction_store import (
    load_engagement_delivery,
    mark_engagement_delivered,
    mark_engagement_failed,
    plan_engagement_deliveries,
)
from .interactions import (
    EngagementDelivery,
    InteractionSubject,
    allowed_actions,
)
from .models import Settings
from .telegram import send_telegram_message
from .utils import ICT, now_ict

ACTION_TO_CODE = {
    "useful": "u",
    "noise": "n",
    "save": "s",
    "done": "d",
    "apply": "a",
    "verify": "v",
    "dismiss": "x",
    "repeat": "r",
}
CODE_TO_ACTION = {code: action for action, code in ACTION_TO_CODE.items()}
CALLBACK_VERSION = "i1"
CALLBACK_DATA_LIMIT = 64


@dataclass(frozen=True)
class ButtonSpec:
    text: str
    action: str


@dataclass(frozen=True)
class InteractiveSubject:
    subject: InteractionSubject
    buttons: tuple[ButtonSpec, ...]


def encode_callback(delivery_id: int, action: str) -> str:
    try:
        identifier = int(delivery_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Callback delivery ID must be a positive integer") from exc
    if identifier <= 0:
        raise ValueError("Callback delivery ID must be a positive integer")
    code = ACTION_TO_CODE.get(action)
    if code is None:
        raise ValueError("Unknown callback action")
    payload = f"{CALLBACK_VERSION}|{identifier}|{code}"
    if len(payload.encode("utf-8")) > CALLBACK_DATA_LIMIT:
        raise ValueError("Callback payload exceeds Telegram's 64-byte limit")
    return payload


def decode_callback(payload: str) -> tuple[int, str]:
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > CALLBACK_DATA_LIMIT:
        raise ValueError("Invalid callback payload")
    parts = payload.split("|")
    if len(parts) != 3 or parts[0] != CALLBACK_VERSION:
        raise ValueError("Unsupported callback payload")
    raw_id, code = parts[1], parts[2]
    if not raw_id.isascii() or not raw_id.isdigit() or raw_id.startswith("0"):
        raise ValueError("Invalid callback delivery ID")
    action = CODE_TO_ACTION.get(code)
    if action is None:
        raise ValueError("Unknown callback action code")
    return int(raw_id), action


def _validate_subject(interactive: InteractiveSubject) -> None:
    actions = allowed_actions(interactive.subject.subject_type)
    if not actions:
        raise ValueError("Unknown interaction subject type")
    if not interactive.buttons:
        raise ValueError("Interactive subjects require at least one button")
    for button in interactive.buttons:
        if not button.text.strip():
            raise ValueError("Interaction button labels cannot be empty")
        if button.action not in actions:
            raise ValueError("Button action is not allowed for its subject")


def build_inline_keyboard(
    deliveries: list[EngagementDelivery],
    subjects: list[InteractiveSubject],
    *,
    numbered: bool = False,
) -> dict:
    if not deliveries or len(deliveries) != len(subjects):
        raise ValueError("Deliveries and interactive subjects must be non-empty and aligned")

    rows: list[list[dict[str, str]]] = []
    for index, (delivery, interactive) in enumerate(zip(deliveries, subjects), start=1):
        _validate_subject(interactive)
        if (
            delivery.subject_type != interactive.subject.subject_type
            or delivery.subject_id != interactive.subject.subject_id
        ):
            raise ValueError("Delivery target does not match its interactive subject")
        row = []
        for button in interactive.buttons:
            label = f"{index} {button.text}" if numbered else button.text
            row.append(
                {
                    "text": label,
                    "callback_data": encode_callback(delivery.id, button.action),
                }
            )
        rows.append(row)
    return {"inline_keyboard": rows}


def send_interactive_message(
    conn,
    settings: Settings,
    profile: str,
    text: str,
    subjects: list[InteractiveSubject],
    *,
    delivery_kind: str = "content",
    numbered: bool = False,
    chat_id: str | None = None,
    reply_to_message_id: int | None = None,
    current: datetime | None = None,
) -> list[EngagementDelivery]:
    target_chat_id = str(chat_id or settings.telegram_chat_id)
    if not settings.telegram_bot_token or not target_chat_id:
        raise RuntimeError(
            "Telegram is not configured: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"
        )
    for subject in subjects:
        _validate_subject(subject)

    value = current or now_ict()
    local = value.replace(tzinfo=ICT) if value.tzinfo is None else value.astimezone(ICT)
    timestamp = local.isoformat()
    planned = plan_engagement_deliveries(
        conn,
        profile,
        target_chat_id,
        [interactive.subject for interactive in subjects],
        delivery_kind,
        timestamp,
    )
    delivery_ids = [row.id for row in planned]

    try:
        markup = build_inline_keyboard(planned, subjects, numbered=numbered)
        results = send_telegram_message(
            text,
            settings,
            chat_id=target_chat_id,
            reply_to_message_id=reply_to_message_id,
            reply_markup=markup,
        )
        if len(results) != 1 or not results[0].get("message_id"):
            raise RuntimeError("Telegram sendMessage did not return one message ID")
        message_id = str(results[0]["message_id"])
        mark_engagement_delivered(conn, delivery_ids, message_id, timestamp)
    except Exception:
        try:
            mark_engagement_failed(conn, delivery_ids)
        except Exception:
            pass
        raise

    refreshed = [load_engagement_delivery(conn, delivery_id) for delivery_id in delivery_ids]
    if any(row is None for row in refreshed):
        raise RuntimeError("An engagement delivery disappeared after Telegram send")
    return [row for row in refreshed if row is not None]
