from __future__ import annotations

from datetime import datetime, timedelta

from .db import row_value
from .interactions import (
    EngagementDelivery,
    InteractionResult,
    InteractionSubject,
    QueueEntry,
    WeeklyMetrics,
    allowed_actions,
    queue_transition,
)

OPEN_ACTIONS = {"save", "apply", "verify", "repeat"}
SENTIMENT_ACTIONS = {"useful", "noise"}
TOASTS = {
    "useful": "Đã ghi nhận 👍",
    "noise": "Đã ghi nhận 👎",
    "save": "Đã lưu vào /queue",
    "done": "Đã hoàn thành",
    "apply": "Đã thêm Apply vào /queue",
    "verify": "Đã thêm Verify vào /queue",
    "dismiss": "Đã bỏ",
    "repeat": "Đã thêm Nhắc lại vào /queue",
}


def _delivery_from_row(row) -> EngagementDelivery:
    return EngagementDelivery(
        id=int(row_value(row, "id", 0)),
        profile=str(row_value(row, "profile", 1)),
        subject_type=str(row_value(row, "subject_type", 2)),
        subject_id=str(row_value(row, "subject_id", 3)),
        delivery_kind=str(row_value(row, "delivery_kind", 4)),
        chat_id=str(row_value(row, "chat_id", 5)),
        delivery_state=str(row_value(row, "delivery_state", 6)),
        telegram_message_id=str(row_value(row, "telegram_message_id", 7) or ""),
        created_at=str(row_value(row, "created_at", 8)),
        delivered_at=str(row_value(row, "delivered_at", 9) or ""),
    )


def _queue_from_row(row) -> QueueEntry:
    return QueueEntry(
        profile=str(row_value(row, "profile", 0)),
        chat_id=str(row_value(row, "chat_id", 1)),
        actor_user_id=str(row_value(row, "actor_user_id", 2)),
        subject_type=str(row_value(row, "subject_type", 3)),
        subject_id=str(row_value(row, "subject_id", 4)),
        queue_action=str(row_value(row, "queue_action", 5)),
        status=str(row_value(row, "status", 6)),
        created_at=str(row_value(row, "created_at", 7)),
        updated_at=str(row_value(row, "updated_at", 8)),
        completed_at=str(row_value(row, "completed_at", 9) or ""),
    )


def plan_engagement_deliveries(
    conn,
    profile: str,
    chat_id: str,
    subjects: list[InteractionSubject],
    delivery_kind: str,
    created_at: str,
) -> list[EngagementDelivery]:
    if delivery_kind not in {"content", "queue"}:
        raise ValueError("Unsupported engagement delivery kind")
    if not subjects:
        raise ValueError("At least one interaction subject is required")

    ids: list[int] = []
    try:
        for subject in subjects:
            row = conn.execute(
                """INSERT INTO engagement_deliveries (
                       profile, subject_type, subject_id, delivery_kind, chat_id,
                       delivery_state, created_at
                   ) VALUES (?, ?, ?, ?, ?, 'planned', ?)
                   RETURNING id""",
                (
                    str(profile),
                    subject.subject_type,
                    subject.subject_id,
                    delivery_kind,
                    str(chat_id),
                    created_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Could not allocate engagement delivery ID")
            ids.append(int(row_value(row, "id", 0)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return [load_engagement_delivery(conn, delivery_id) for delivery_id in ids]


def mark_engagement_delivered(
    conn,
    delivery_ids: list[int],
    telegram_message_id: str,
    delivered_at: str,
) -> None:
    if not delivery_ids:
        return
    placeholders = ",".join("?" for _ in delivery_ids)
    try:
        conn.execute(
            f"""UPDATE engagement_deliveries
                SET delivery_state='delivered', telegram_message_id=?, delivered_at=?
                WHERE id IN ({placeholders}) AND delivery_state='planned'""",
            (str(telegram_message_id), delivered_at, *delivery_ids),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def mark_engagement_failed(conn, delivery_ids: list[int]) -> None:
    if not delivery_ids:
        return
    placeholders = ",".join("?" for _ in delivery_ids)
    try:
        conn.execute(
            f"""UPDATE engagement_deliveries
                SET delivery_state='failed'
                WHERE id IN ({placeholders}) AND delivery_state='planned'""",
            tuple(delivery_ids),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def load_engagement_delivery(conn, delivery_id: int) -> EngagementDelivery | None:
    row = conn.execute(
        """SELECT id, profile, subject_type, subject_id, delivery_kind, chat_id,
                  delivery_state, telegram_message_id, created_at, delivered_at
           FROM engagement_deliveries
           WHERE id=?""",
        (delivery_id,),
    ).fetchone()
    return _delivery_from_row(row) if row else None


def promote_planned_engagement_delivery(
    conn,
    delivery_id: int,
    telegram_message_id: str,
    delivered_at: str,
) -> EngagementDelivery | None:
    try:
        conn.execute(
            """UPDATE engagement_deliveries
               SET delivery_state='delivered', telegram_message_id=?, delivered_at=?
               WHERE id=? AND delivery_state='planned'
                 AND (telegram_message_id='' OR telegram_message_id=?)""",
            (
                str(telegram_message_id),
                delivered_at,
                delivery_id,
                str(telegram_message_id),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return load_engagement_delivery(conn, delivery_id)


def _current_action(conn, delivery: EngagementDelivery, actor_user_id: str, action: str):
    if action in SENTIMENT_ACTIONS:
        row = conn.execute(
            """SELECT events.action
               FROM interaction_events AS events
               JOIN engagement_deliveries AS deliveries
                 ON deliveries.id=events.engagement_delivery_id
               WHERE deliveries.profile=? AND deliveries.chat_id=?
                 AND deliveries.subject_type=? AND deliveries.subject_id=?
                 AND events.actor_user_id=?
                 AND events.action IN ('useful', 'noise')
               ORDER BY events.created_at DESC, events.id DESC
               LIMIT 1""",
            (
                delivery.profile,
                delivery.chat_id,
                delivery.subject_type,
                delivery.subject_id,
                actor_user_id,
            ),
        ).fetchone()
        return str(row_value(row, "action", 0)) if row else None

    row = conn.execute(
        """SELECT queue_action, status
           FROM action_queue
           WHERE profile=? AND chat_id=? AND actor_user_id=?
             AND subject_type=? AND subject_id=?""",
        (
            delivery.profile,
            delivery.chat_id,
            actor_user_id,
            delivery.subject_type,
            delivery.subject_id,
        ),
    ).fetchone()
    if not row:
        return None
    return (
        str(row_value(row, "queue_action", 0)),
        str(row_value(row, "status", 1)),
    )


def _upsert_queue(
    conn,
    delivery: EngagementDelivery,
    actor_user_id: str,
    action: str,
    status: str,
    occurred_at: str,
) -> None:
    completed_at = occurred_at if status == "completed" else ""
    conn.execute(
        """INSERT INTO action_queue (
               profile, chat_id, actor_user_id, subject_type, subject_id,
               queue_action, status, created_at, updated_at, completed_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(profile, chat_id, actor_user_id, subject_type, subject_id)
           DO UPDATE SET
               queue_action=excluded.queue_action,
               status=excluded.status,
               updated_at=excluded.updated_at,
               completed_at=excluded.completed_at""",
        (
            delivery.profile,
            delivery.chat_id,
            actor_user_id,
            delivery.subject_type,
            delivery.subject_id,
            action,
            status,
            occurred_at,
            occurred_at,
            completed_at,
        ),
    )


def record_interaction(
    conn,
    delivery_id: int,
    action: str,
    actor_user_id: str,
    callback_query_id: str,
    occurred_at: str,
) -> InteractionResult:
    duplicate = conn.execute(
        "SELECT id FROM interaction_events WHERE telegram_callback_query_id=?",
        (callback_query_id,),
    ).fetchone()
    if duplicate:
        return InteractionResult(duplicate=True, changed=False, toast="Đã ghi nhận trước đó")

    delivery = load_engagement_delivery(conn, delivery_id)
    if delivery is None:
        raise ValueError("Interaction delivery does not exist")
    if action not in allowed_actions(delivery.subject_type):
        raise ValueError("Action is not allowed for this subject")

    actor = str(actor_user_id)
    current = _current_action(conn, delivery, actor, action)
    transition = queue_transition(action)
    expected = transition if transition is not None else action
    changed = current != expected

    try:
        inserted = conn.execute(
            """INSERT OR IGNORE INTO interaction_events (
                   engagement_delivery_id, action, actor_user_id,
                   telegram_callback_query_id, created_at
               ) VALUES (?, ?, ?, ?, ?)
               RETURNING id""",
            (delivery_id, action, actor, callback_query_id, occurred_at),
        ).fetchone()
        if inserted is None:
            conn.rollback()
            return InteractionResult(duplicate=True, changed=False, toast="Đã ghi nhận trước đó")
        if transition is not None and changed:
            queue_action, status = transition
            _upsert_queue(conn, delivery, actor, queue_action, status, occurred_at)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return InteractionResult(
        duplicate=False,
        changed=changed,
        toast=TOASTS.get(action, "Đã ghi nhận"),
    )


def list_open_queue(
    conn,
    profile: str,
    chat_id: str,
    actor_user_id: str,
    limit: int = 8,
) -> list[QueueEntry]:
    safe_limit = max(1, min(int(limit), 8))
    rows = conn.execute(
        """SELECT profile, chat_id, actor_user_id, subject_type, subject_id,
                  queue_action, status, created_at, updated_at, completed_at
           FROM action_queue
           WHERE profile=? AND chat_id=? AND actor_user_id=? AND status='open'
           ORDER BY updated_at DESC
           LIMIT ?""",
        (profile, str(chat_id), str(actor_user_id), safe_limit),
    ).fetchall()
    return [_queue_from_row(row) for row in rows]


def mark_queue_unavailable(
    conn,
    profile: str,
    chat_id: str,
    actor_user_id: str,
    subject_type: str,
    subject_id: str,
    updated_at: str,
) -> None:
    conn.execute(
        """UPDATE action_queue
           SET status='unavailable', updated_at=?, completed_at=''
           WHERE profile=? AND chat_id=? AND actor_user_id=?
             AND subject_type=? AND subject_id=? AND status='open'""",
        (
            updated_at,
            profile,
            str(chat_id),
            str(actor_user_id),
            subject_type,
            str(subject_id),
        ),
    )
    conn.commit()


def load_stored_subject(conn, subject_type: str, subject_id: str) -> tuple[str, str] | None:
    if subject_type == "news":
        if not str(subject_id).isdigit():
            return None
        row = conn.execute(
            "SELECT title, url FROM items WHERE id=?",
            (int(subject_id),),
        ).fetchone()
        if not row:
            return None
        return (
            str(row_value(row, "title", 0)),
            str(row_value(row, "url", 1)),
        )

    if subject_type == "job":
        row = conn.execute(
            """SELECT role_title, company, apply_url, source_url
               FROM job_opportunities WHERE id=?""",
            (str(subject_id),),
        ).fetchone()
        if not row:
            return None
        title = f"{row_value(row, 'role_title', 0)} · {row_value(row, 'company', 1)}"
        url = row_value(row, "apply_url", 2) or row_value(row, "source_url", 3)
        return str(title), str(url or "")

    return None


def _events_for_period(
    conn,
    profile: str,
    chat_id: str,
    start_at: str,
    end_at: str,
    actor_user_id: str | None,
):
    sql = """SELECT events.id, events.action, events.actor_user_id,
                    events.engagement_delivery_id, events.created_at,
                    deliveries.subject_type, deliveries.subject_id
             FROM interaction_events AS events
             JOIN engagement_deliveries AS deliveries
               ON deliveries.id=events.engagement_delivery_id
             WHERE deliveries.profile=? AND deliveries.chat_id=?
               AND deliveries.delivery_state='delivered'
               AND events.created_at>=? AND events.created_at<?"""
    params: list[object] = [profile, str(chat_id), start_at, end_at]
    if actor_user_id is not None:
        sql += " AND events.actor_user_id=?"
        params.append(str(actor_user_id))
    sql += " ORDER BY events.created_at, events.id"
    return conn.execute(sql, tuple(params)).fetchall()


def weekly_metrics(
    conn,
    profile: str,
    chat_id: str,
    start_at: str,
    end_at: str,
    actor_user_id: str | None = None,
) -> WeeklyMetrics:
    deliveries = conn.execute(
        """SELECT id, subject_type, subject_id
           FROM engagement_deliveries
           WHERE profile=? AND chat_id=? AND delivery_kind='content'
             AND delivery_state='delivered'
             AND delivered_at>=? AND delivered_at<?""",
        (profile, str(chat_id), start_at, end_at),
    ).fetchall()
    content_subjects = {
        (
            str(row_value(row, "subject_type", 1)),
            str(row_value(row, "subject_id", 2)),
        )
        for row in deliveries
    }
    events = _events_for_period(
        conn,
        profile,
        str(chat_id),
        start_at,
        end_at,
        actor_user_id,
    )

    responded: set[tuple[str, str]] = set()
    sentiment: dict[tuple[str, str, str], str] = {}
    queued: set[tuple[str, str, str]] = set()
    completed: set[tuple[str, str, str]] = set()
    applies: set[tuple[str, str, str]] = set()
    verifies: set[tuple[str, str, str]] = set()
    repeats: set[tuple[str, str, str]] = set()

    for row in events:
        subject = (
            str(row_value(row, "subject_type", 5)),
            str(row_value(row, "subject_id", 6)),
        )
        if subject not in content_subjects:
            continue
        action = str(row_value(row, "action", 1))
        actor = str(row_value(row, "actor_user_id", 2))
        actor_subject = (actor, *subject)
        responded.add(subject)
        if action in SENTIMENT_ACTIONS:
            sentiment[actor_subject] = action
        if action in OPEN_ACTIONS:
            queued.add(actor_subject)
        if action == "done":
            completed.add(actor_subject)
        elif action == "apply":
            applies.add(actor_subject)
        elif action == "verify":
            verifies.add(actor_subject)
        elif action == "repeat":
            repeats.add(actor_subject)

    open_sql = """SELECT COUNT(*) AS count
                  FROM action_queue
                  WHERE profile=? AND chat_id=? AND status='open'"""
    open_params: list[object] = [profile, str(chat_id)]
    if actor_user_id is not None:
        open_sql += " AND actor_user_id=?"
        open_params.append(str(actor_user_id))
    open_row = conn.execute(open_sql, tuple(open_params)).fetchone()
    open_items = int(row_value(open_row, "count", 0) or 0) if open_row else 0

    return WeeklyMetrics(
        delivered=len(deliveries),
        responded=len(responded),
        useful=sum(action == "useful" for action in sentiment.values()),
        noise=sum(action == "noise" for action in sentiment.values()),
        queued=len(queued),
        completed=len(completed),
        open_items=open_items,
        apply=len(applies),
        verify=len(verifies),
        repeat=len(repeats),
    )


def reserve_weekly_report(
    conn,
    profile: str,
    chat_id: str,
    report_week: str,
    created_at: str,
) -> bool:
    try:
        inserted = conn.execute(
            """INSERT OR IGNORE INTO weekly_report_deliveries (
                   profile, chat_id, report_week, delivery_state, created_at
               ) VALUES (?, ?, ?, 'planned', ?)
               RETURNING profile""",
            (profile, str(chat_id), report_week, created_at),
        ).fetchone()
        if inserted is not None:
            conn.commit()
            return True

        existing = conn.execute(
            """SELECT delivery_state, created_at
               FROM weekly_report_deliveries
               WHERE profile=? AND chat_id=? AND report_week=?""",
            (profile, str(chat_id), report_week),
        ).fetchone()
        if not existing or str(row_value(existing, "delivery_state", 0)) == "delivered":
            conn.commit()
            return False

        previous = datetime.fromisoformat(str(row_value(existing, "created_at", 1)))
        current = datetime.fromisoformat(created_at)
        if current - previous <= timedelta(minutes=15):
            conn.commit()
            return False

        reclaimed = conn.execute(
            """UPDATE weekly_report_deliveries
               SET created_at=?, delivered_at=''
               WHERE profile=? AND chat_id=? AND report_week=?
                 AND delivery_state='planned' AND created_at=?
               RETURNING profile""",
            (
                created_at,
                profile,
                str(chat_id),
                report_week,
                str(row_value(existing, "created_at", 1)),
            ),
        ).fetchone()
        conn.commit()
        return reclaimed is not None
    except Exception:
        conn.rollback()
        raise


def complete_weekly_report(
    conn,
    profile: str,
    chat_id: str,
    report_week: str,
    delivered_at: str,
) -> None:
    conn.execute(
        """UPDATE weekly_report_deliveries
           SET delivery_state='delivered', delivered_at=?
           WHERE profile=? AND chat_id=? AND report_week=?
             AND delivery_state='planned'""",
        (delivered_at, profile, str(chat_id), report_week),
    )
    conn.commit()


def release_weekly_report(
    conn,
    profile: str,
    chat_id: str,
    report_week: str,
) -> None:
    conn.execute(
        """DELETE FROM weekly_report_deliveries
           WHERE profile=? AND chat_id=? AND report_week=?
             AND delivery_state='planned'""",
        (profile, str(chat_id), report_week),
    )
    conn.commit()
