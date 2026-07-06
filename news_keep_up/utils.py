from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ICT = ZoneInfo("Asia/Ho_Chi_Minh")

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
}


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS or key_lower.startswith(TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key_lower, value))
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def clean_text(text: str) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fingerprint_text(*parts: str) -> str:
    normalized = clean_text(" ".join(parts)).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def now_ict() -> datetime:
    return datetime.now(ICT)
