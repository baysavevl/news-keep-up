from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .interaction_store import (
    load_engagement_delivery,
    load_stored_subject,
    mark_engagement_delivered,
    mark_engagement_failed,
    plan_engagement_deliveries,
    promote_planned_engagement_delivery,
    record_interaction,
)
from .interactions import (
    EngagementDelivery,
    InteractionSubject,
    allowed_actions,
)
from .models import Settings
from .telegram import answer_telegram_callback, send_telegram_message
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


def _callback_result(reason: str) -> dict:
    return {
        "ok": True,
        "callback": True,
        "ignored": True,
        "reason": reason,
    }


def _reject_callback(
    callback_query_id: str,
    reason: str,
    toast: str,
    settings: Settings,
) -> dict:
    if callback_query_id:
        answer_telegram_callback(callback_query_id, toast, settings, show_alert=True)
    return _callback_result(reason)


def _subject_exists(conn, subject_type: str, subject_id: str) -> bool:
    if subject_type in {"news", "job"}:
        return load_stored_subject(conn, subject_type, subject_id) is not None
    if subject_type == "interview":
        from .interview import FDE_INTERVIEW_GUIDELINES

        return subject_id in {card.slug for card in FDE_INTERVIEW_GUIDELINES}
    return False


def handle_interaction_callback(
    callback_query: dict,
    *,
    profile: str,
    settings: Settings,
    current: datetime | None = None,
) -> dict:
    callback_query_id = str(callback_query.get("id") or "")
    actor = callback_query.get("from") or {}
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    actor_user_id = str(actor.get("id") or "")
    chat_id = str(chat.get("id") or "")
    message_id = str(message.get("message_id") or "")

    if not callback_query_id or not actor_user_id or not chat_id or not message_id:
        return _reject_callback(
            callback_query_id,
            "malformed_callback",
            "Action không hợp lệ",
            settings,
        )
    configured_chat = str(settings.telegram_chat_id or "")
    if not configured_chat or chat_id != configured_chat:
        return _reject_callback(
            callback_query_id,
            "unauthorized_chat",
            "Action không thuộc chat này",
            settings,
        )
    try:
        delivery_id, action = decode_callback(str(callback_query.get("data") or ""))
    except ValueError:
        return _reject_callback(
            callback_query_id,
            "malformed_callback",
            "Action không hợp lệ",
            settings,
        )

    from .db import connect_database, init_db

    value = current or now_ict()
    local = value.replace(tzinfo=ICT) if value.tzinfo is None else value.astimezone(ICT)
    occurred_at = local.isoformat()
    conn = connect_database(settings)
    try:
        init_db(conn)
        delivery = load_engagement_delivery(conn, delivery_id)
        if delivery is None:
            return _reject_callback(
                callback_query_id,
                "missing_delivery",
                "Action đã hết hạn",
                settings,
            )
        if delivery.profile != profile or delivery.chat_id != chat_id:
            return _reject_callback(
                callback_query_id,
                "target_mismatch",
                "Action không thuộc nội dung này",
                settings,
            )
        if delivery.delivery_state not in {"planned", "delivered"}:
            return _reject_callback(
                callback_query_id,
                "inactive_delivery",
                "Action đã hết hạn",
                settings,
            )
        if delivery.telegram_message_id and delivery.telegram_message_id != message_id:
            return _reject_callback(
                callback_query_id,
                "stale_message",
                "Action đã hết hạn",
                settings,
            )
        if action not in allowed_actions(delivery.subject_type):
            return _reject_callback(
                callback_query_id,
                "incompatible_action",
                "Action không phù hợp nội dung",
                settings,
            )
        if not _subject_exists(conn, delivery.subject_type, delivery.subject_id):
            return _reject_callback(
                callback_query_id,
                "missing_subject",
                "Nội dung không còn khả dụng",
                settings,
            )
        if delivery.delivery_state == "planned":
            delivery = promote_planned_engagement_delivery(
                conn,
                delivery.id,
                message_id,
                occurred_at,
            )
        if (
            delivery is None
            or delivery.delivery_state != "delivered"
            or delivery.telegram_message_id != message_id
        ):
            return _reject_callback(
                callback_query_id,
                "stale_message",
                "Action đã hết hạn",
                settings,
            )
        result = record_interaction(
            conn,
            delivery.id,
            action,
            actor_user_id,
            callback_query_id,
            occurred_at,
        )
    except Exception:
        return _reject_callback(
            callback_query_id,
            "retry",
            "Chưa lưu được, hãy thử lại",
            settings,
        )
    finally:
        conn.close()

    answer_telegram_callback(callback_query_id, result.toast, settings)
    return {
        "ok": True,
        "callback": True,
        "action": action,
        "duplicate": result.duplicate,
        "changed": result.changed,
    }
