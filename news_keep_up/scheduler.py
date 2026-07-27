from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .utils import ICT, now_ict

FDE_NEWS_TIMES = ((8, 0), (14, 0))
ENGINEER_NEWS_TIMES = ((9, 15), (16, 0))
FDE_INTERVIEW_TIMES = ((8, 35), (11, 35), (14, 35))
FDE_JOB_ALERT_MINUTES = (0, 30)
FDE_JOB_ALERT_START_HOUR = 7
FDE_JOB_ALERT_END_HOUR = 21
FDE_JOB_SOURCE_TIMES = ((7, 10),)


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


def is_fde_job_alert_send_window(current: datetime | None = None) -> bool:
    now = current or now_ict()
    if now.tzinfo is None:
        now = now.replace(tzinfo=ICT)
    else:
        now = now.astimezone(ICT)
    start = now.replace(hour=FDE_JOB_ALERT_START_HOUR, minute=0, second=0, microsecond=0)
    end = now.replace(hour=FDE_JOB_ALERT_END_HOUR, minute=0, second=0, microsecond=0)
    return start <= now <= end


def _jobs_for_day(day, start: datetime, end: datetime) -> list[ScheduledDigestJob]:
    jobs: list[ScheduledDigestJob] = []
    for hour, minute in FDE_NEWS_TIMES:
        jobs.append(_job_for(day, hour, minute, "fde"))
    for hour, minute in ENGINEER_NEWS_TIMES:
        jobs.append(_job_for(day, hour, minute, "engineer"))
    for hour, minute in FDE_INTERVIEW_TIMES:
        jobs.append(_job_for(day, hour, minute, "fde-interview"))
    for hour, minute in FDE_JOB_SOURCE_TIMES:
        jobs.append(_job_for(day, hour, minute, "fde-job-sources"))
    for hour in range(FDE_JOB_ALERT_START_HOUR, FDE_JOB_ALERT_END_HOUR + 1):
        for minute in FDE_JOB_ALERT_MINUTES:
            if hour == FDE_JOB_ALERT_END_HOUR and minute > 0:
                continue
            jobs.append(_job_for(day, hour, minute, "fde-jobs"))
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
