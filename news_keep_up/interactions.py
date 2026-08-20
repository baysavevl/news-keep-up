from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .utils import ICT, now_ict

ACTIONS_BY_SUBJECT = {
    "news": {"useful", "noise", "save", "done"},
    "job": {"save", "apply", "verify", "dismiss"},
    "interview": {"done", "repeat", "dismiss"},
}
OPEN_QUEUE_ACTIONS = {"save", "apply", "verify", "repeat"}
CLOSE_QUEUE_ACTIONS = {"done": "completed", "dismiss": "dismissed"}


@dataclass(frozen=True)
class InteractionSubject:
    subject_type: str
    subject_id: str

    def __init__(self, subject_type: str, subject_id: object):
        object.__setattr__(self, "subject_type", str(subject_type))
        object.__setattr__(self, "subject_id", str(subject_id))


@dataclass(frozen=True)
class EngagementDelivery:
    id: int
    profile: str
    subject_type: str
    subject_id: str
    delivery_kind: str
    chat_id: str
    delivery_state: str
    telegram_message_id: str
    created_at: str
    delivered_at: str


@dataclass(frozen=True)
class QueueEntry:
    profile: str
    chat_id: str
    actor_user_id: str
    subject_type: str
    subject_id: str
    queue_action: str
    status: str
    created_at: str
    updated_at: str
    completed_at: str


@dataclass(frozen=True)
class ResolvedQueueEntry:
    queue: QueueEntry
    title: str
    url: str


@dataclass(frozen=True)
class InteractionResult:
    duplicate: bool
    changed: bool
    toast: str


@dataclass(frozen=True)
class WeeklyMetrics:
    delivered: int
    responded: int
    useful: int
    noise: int
    queued: int
    completed: int
    open_items: int
    apply: int
    verify: int
    repeat: int


@dataclass(frozen=True)
class ReportPeriod:
    start: datetime
    end: datetime
    report_week: str


def allowed_actions(subject_type: str, delivery_kind: str = "content") -> set[str]:
    if subject_type not in ACTIONS_BY_SUBJECT:
        return set()
    if delivery_kind == "queue":
        return {"done", "dismiss"}
    return set(ACTIONS_BY_SUBJECT[subject_type])


def queue_transition(action: str) -> tuple[str, str] | None:
    if action in OPEN_QUEUE_ACTIONS:
        return action, "open"
    if action in CLOSE_QUEUE_ACTIONS:
        return action, CLOSE_QUEUE_ACTIONS[action]
    return None


def report_period(current: datetime | None = None) -> ReportPeriod:
    value = current or now_ict()
    local = value.replace(tzinfo=ICT) if value.tzinfo is None else value.astimezone(ICT)
    end = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    monday = end - timedelta(days=end.weekday())
    return ReportPeriod(start=start, end=end, report_week=monday.date().isoformat())


def _percentage(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((numerator / denominator) * 100)


def format_weekly_report(
    metrics: WeeklyMetrics,
    profile: str,
    compact: bool = False,
    period: ReportPeriod | None = None,
) -> str:
    title = "📊 Weekly outcome"
    if period is not None:
        title += f" · {period.start:%d/%m}–{period.end - timedelta(days=1):%d/%m}"

    response_rate = _percentage(metrics.responded, metrics.delivered)
    delivery_line = (
        f"{metrics.delivered} delivered · {metrics.responded} responded "
        f"({response_rate}%)"
    )

    if profile == "fde-jobs":
        outcome_line = f"{metrics.apply} apply · {metrics.verify} verify"
    elif profile == "fde-interview":
        outcome_line = f"{metrics.completed} practiced · {metrics.repeat} repeat"
    else:
        sentiment_total = metrics.useful + metrics.noise
        precision = _percentage(metrics.useful, sentiment_total)
        outcome_line = (
            f"{metrics.useful} useful · {metrics.noise} noise · {precision}% useful"
        )

    queue_line = (
        f"{metrics.queued} queued · {metrics.completed} completed · "
        f"{metrics.open_items} open"
    )
    lines = [title, delivery_line, outcome_line, queue_line]
    if compact:
        return "\n".join(lines)
    return "\n".join(lines)
