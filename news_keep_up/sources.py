from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

from .models import CandidateItem, Source
from .utils import canonicalize_url, clean_text, fingerprint_text, now_ict


def parse_rss_or_atom(xml_text: str, source: Source) -> list[CandidateItem]:
    root = ET.fromstring(xml_text)
    if _local_name(root.tag) == "feed":
        entries = [node for node in root.iter() if _local_name(node.tag) == "entry"]
    else:
        entries = [node for node in root.iter() if _local_name(node.tag) == "item"]
    candidates: list[CandidateItem] = []
    for node in entries:
        candidate = _candidate_from_xml(node, source)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def fetch_source(source: Source, user_agent: str, timeout_seconds: int = 15) -> list[CandidateItem]:
    if source.kind == "hackernews":
        return fetch_hackernews(source, user_agent, timeout_seconds)

    request = urllib.request.Request(source.url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        xml_text = response.read().decode("utf-8", errors="replace")
    return parse_rss_or_atom(xml_text, source)


def fetch_hackernews(source: Source, user_agent: str, timeout_seconds: int = 15) -> list[CandidateItem]:
    request = urllib.request.Request(source.url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))

    candidates: list[CandidateItem] = []
    for hit in data.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        title = clean_text(hit.get("title") or hit.get("story_title") or "")
        if not title or not url:
            continue
        summary = clean_text(hit.get("story_text") or "")
        canonical = canonicalize_url(url)
        candidates.append(CandidateItem(
            source_name=source.name,
            source_kind=source.kind,
            source_category=source.category,
            title=title,
            url=url,
            canonical_url=canonical,
            summary=summary,
            author=clean_text(hit.get("author") or ""),
            published_at=clean_text(hit.get("created_at") or ""),
            fetched_at=now_ict().isoformat(),
            fingerprint=fingerprint_text(title, summary, canonical),
            raw=hit,
        ))
    return candidates


def _candidate_from_xml(node: ET.Element, source: Source) -> CandidateItem | None:
    title = clean_text(_first_text(node, ("title",)))
    link = clean_text(_first_text(node, ("link",)))
    if not link:
        link = _first_link_href(node)
    summary = clean_text(_first_text(node, ("description", "summary", "content", "encoded")))
    author = clean_text(_first_text(node, ("author", "creator", "name")))
    published = clean_text(_first_text(node, ("pubDate", "published", "updated", "date")))
    if published:
        published = _normalize_date(published)
    if not title or not link:
        return None

    canonical = canonicalize_url(link)
    return CandidateItem(
        source_name=source.name,
        source_kind=source.kind,
        source_category=source.category,
        title=title,
        url=link,
        canonical_url=canonical,
        summary=summary,
        content="",
        author=author,
        published_at=published,
        fetched_at=now_ict().isoformat(),
        fingerprint=fingerprint_text(title, summary, canonical),
        raw={"title": title, "url": link, "summary": summary},
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ET.Element, names: Iterable[str]) -> Iterable[ET.Element]:
    wanted = set(names)
    for child in node.iter():
        if child is node:
            continue
        if _local_name(child.tag) in wanted:
            yield child


def _first_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in _children(node, names):
        if child.text:
            return child.text
    return ""


def _first_link_href(node: ET.Element) -> str:
    for child in _children(node, ("link",)):
        href = child.attrib.get("href")
        if href:
            return href
    return ""


def _normalize_date(value: str) -> str:
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
