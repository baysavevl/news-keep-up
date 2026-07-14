from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .utils import ICT, now_ict


@dataclass(frozen=True)
class ScheduledDigestJob:
    slot: str
    scheduled_for: datetime

    @property
    def scheduled_for_key(self) -> str:
        return self.scheduled_for.isoformat()


def due_digest_jobs(
    current: datetime | None = None,
    lookback_minutes: int = 55,
) -> list[ScheduledDigestJob]:
    now = current or now_ict()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ICT)
    else:
        now = now.astimezone(ICT)

    start = now - timedelta(minutes=lookback_minutes)
    jobs: list[ScheduledDigestJob] = []
    day_count = (now.date() - start.date()).days + 1
    for day_offset in range(day_count):
        day = start.date() + timedelta(days=day_offset)
        jobs.extend(_jobs_for_day(day, start, now))
    return sorted(jobs, key=lambda job: job.scheduled_for)


def _jobs_for_day(day, start: datetime, end: datetime) -> list[ScheduledDigestJob]:
    jobs: list[ScheduledDigestJob] = []
    for hour in range(7, 23):
        jobs.append(_job_for(day, hour, 20, "fde"))
        jobs.append(_job_for(day, hour, 40, "engineer"))
    for hour in range(7, 22, 2):
        jobs.append(_job_for(day, hour, 35, "fde-interview"))
    return [job for job in jobs if start <= job.scheduled_for <= end]


def _job_for(day, hour: int, minute: int, slot: str) -> ScheduledDigestJob:
    scheduled_for = datetime(
        day.year,
        day.month,
        day.day,
        hour,
        minute,
        tzinfo=ICT,
    )
    return ScheduledDigestJob(slot=slot, scheduled_for=scheduled_for)
