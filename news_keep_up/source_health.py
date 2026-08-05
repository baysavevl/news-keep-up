from __future__ import annotations

import html
import re

from .models import Source, SourceFetchLog
from .utils import now_ict


def successful_source_fetch_log(slot: str, source: Source, item_count: int) -> SourceFetchLog:
    return SourceFetchLog(
        slot=slot,
        source_name=source.name,
        source_url=source.url,
        source_kind=source.kind,
        status="ok",
        item_count=max(0, int(item_count)),
        fetched_at=now_ict().isoformat(),
    )


def failed_source_fetch_log(slot: str, source: Source, error: Exception) -> SourceFetchLog:
    return SourceFetchLog(
        slot=slot,
        source_name=source.name,
        source_url=source.url,
        source_kind=source.kind,
        status="failed",
        item_count=0,
        error_type=error.__class__.__name__,
        error_message=_clean_error_message(str(error)),
        fetched_at=now_ict().isoformat(),
    )


def _clean_error_message(message: str) -> str:
    value = html.unescape(str(message or ""))
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()
