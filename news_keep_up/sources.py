from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin

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


def parse_json_feed(json_text: str, source: Source) -> list[CandidateItem]:
    data = json.loads(json_text)
    candidates: list[CandidateItem] = []
    for row in _json_job_rows(data):
        candidate = _candidate_from_json_job(row, source)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def fetch_source(source: Source, user_agent: str, timeout_seconds: int = 15) -> list[CandidateItem]:
    if source.kind == "hackernews":
        return fetch_hackernews(source, user_agent, timeout_seconds)

    request = urllib.request.Request(source.url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        text = response.read().decode("utf-8", errors="replace")
    if source.kind == "json":
        return parse_json_feed(text, source)
    if source.kind == "html":
        return parse_html_page(text, source)
    return parse_rss_or_atom(text, source)


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
            raw={**hit, **source.metadata},
        ))
    return candidates


def parse_html_page(html_text: str, source: Source) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    candidates.extend(_fwddeploy_candidates(html_text, source))
    candidates.extend(_json_ld_job_candidates(html_text, source))

    parser = _HTMLCandidateParser()
    parser.feed(html_text)
    page_title = clean_text(parser.title)
    seen: set[str] = {candidate.canonical_url for candidate in candidates}
    seen_titles: set[str] = {candidate.title.lower() for candidate in candidates}

    for title, href in parser.anchors:
        candidate = _html_candidate(source, title, href, page_title, "anchor")
        if candidate is None or candidate.canonical_url in seen:
            continue
        candidates.append(candidate)
        seen.add(candidate.canonical_url)
        seen_titles.add(candidate.title.lower())

    for title in parser.headings:
        if title.lower() in seen_titles:
            continue
        candidate = _html_candidate(source, title, source.url, page_title, "heading")
        if candidate is None:
            continue
        key = f"{candidate.canonical_url}#{candidate.title.lower()}"
        if key in seen:
            continue
        candidates.append(candidate)
        seen.add(key)
        seen_titles.add(candidate.title.lower())

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
        raw={"title": title, "url": link, "summary": summary, **source.metadata},
    )


def _json_job_rows(data) -> Iterable[dict]:
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = []
        for key in ("jobs", "items", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                rows = value
                break
    else:
        rows = []

    for row in rows:
        if isinstance(row, dict):
            yield row


def _candidate_from_json_job(row: dict, source: Source) -> CandidateItem | None:
    title = _first_json_value(row, ("title", "position", "name"))
    raw_url = _first_json_value(row, ("url", "apply_url", "job_url", "absolute_url"))
    if not title or not raw_url:
        return None

    url = urljoin(source.url, raw_url)
    canonical = canonicalize_url(url)
    company = _first_json_value(row, ("company", "company_name", "organization", "hiring_organization"))
    location = _first_json_value(row, ("location", "candidate_required_location", "candidate_location", "region", "country"))
    description = _first_json_value(row, ("description", "summary", "content"))
    published = _first_json_value(row, ("date", "publication_date", "published_at", "created_at"))
    compensation = _json_compensation(row)
    tags = _json_tags(row)

    summary_parts: list[str] = []
    if company:
        summary_parts.append(f"Company: {company}.")
    if location:
        summary_parts.append(f"Location: {location}.")
    if compensation:
        summary_parts.append(f"Compensation: {compensation}.")
    if tags:
        summary_parts.append(f"Tags: {tags}.")
    if description:
        summary_parts.append(description)
    summary = clean_text(" ".join(summary_parts))

    raw = {
        **row,
        **source.metadata,
        "company": company,
        "location": location,
        "remote_policy": "Remote",
    }
    if compensation:
        raw["compensation"] = compensation

    return CandidateItem(
        source_name=source.name,
        source_kind=source.kind,
        source_category=source.category,
        title=title,
        url=url,
        canonical_url=canonical,
        summary=summary,
        content="",
        author=company,
        published_at=published,
        fetched_at=now_ict().isoformat(),
        fingerprint=fingerprint_text(title, summary, canonical),
        raw=raw,
    )


def _first_json_value(row: dict, keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            for nested_key in ("name", "title", "value"):
                nested_value = value.get(nested_key)
                if nested_value:
                    return clean_text(nested_value)
            continue
        if isinstance(value, list):
            text = ", ".join(clean_text(item) for item in value if clean_text(item))
        else:
            text = clean_text(value)
        if text:
            return text
    return ""


def _json_tags(row: dict) -> str:
    value = row.get("tags") or row.get("keywords")
    if isinstance(value, list):
        return ", ".join(clean_text(item) for item in value if clean_text(item))
    return clean_text(value or "")


def _json_compensation(row: dict) -> str:
    salary = clean_text(row.get("salary") or row.get("compensation") or "")
    if salary:
        return salary

    salary_min = row.get("salary_min")
    salary_max = row.get("salary_max")
    if _positive_number(salary_min) and _positive_number(salary_max):
        return f"{salary_min} - {salary_max}"
    if _positive_number(salary_min):
        return f"{salary_min}+"
    if _positive_number(salary_max):
        return f"up to {salary_max}"
    return ""


def _positive_number(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _fwddeploy_candidates(html_text: str, source: Source) -> list[CandidateItem]:
    source_url = source.url.lower()
    if "fwddeploy.com" not in source_url and "forward deployed engineer job board" not in html_text.lower():
        return []

    candidates: list[CandidateItem] = []
    for href, block in re.findall(
        r"<a\b(?=[^>]*href=[\"'][^\"']*/jobs/[^\"']+[\"'])[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        candidate = _fwddeploy_card_candidate(source, href, block)
        if candidate is not None:
            candidates.append(candidate)

    if candidates:
        return candidates

    detail_candidate = _fwddeploy_detail_candidate(html_text, source)
    return [detail_candidate] if detail_candidate is not None else []


def _fwddeploy_card_candidate(source: Source, href: str, block: str) -> CandidateItem | None:
    title = _first_html_text(block, "h3")
    if not title:
        return None
    paragraphs = [_strip_html(match) for match in re.findall(r"<p\b[^>]*>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL)]
    paragraphs = _unique_texts([value for value in paragraphs if value and value != title])
    company = _first_non_meta_paragraph(paragraphs) or _alt_text_company(block)
    metadata = _fwddeploy_metadata_from_values(paragraphs, company)
    return _job_board_candidate(source, href, title, company, metadata, "fwddeploy_card")


def _fwddeploy_detail_candidate(html_text: str, source: Source) -> CandidateItem | None:
    title = _first_html_text(html_text, "h1") or _meta_content(html_text, "og:title")
    if not title:
        return None
    after_title = html_text[html_text.find("<h1"):] if "<h1" in html_text else html_text
    company = _first_link_text(after_title) or _alt_text_company(html_text)
    detail_region = html_text[:html_text.find('class="mt-12 rich-text"')] if 'class="mt-12 rich-text"' in html_text else html_text
    values = [_strip_html(match) for match in re.findall(
        r"<(?:div|p)\b[^>]*(?:job-posted-at|flex items-center text-sm)[^>]*>(.*?)</(?:div|p)>",
        detail_region,
        flags=re.IGNORECASE | re.DOTALL,
    )]
    metadata = _fwddeploy_metadata_from_values(_unique_texts(values), company)
    description = _meta_content(html_text, "description")
    if description and not metadata.get("description"):
        metadata["description"] = description
    return _job_board_candidate(source, source.url, title, company, metadata, "fwddeploy_detail")


def _job_board_candidate(
    source: Source,
    href: str,
    title: str,
    company: str,
    metadata: dict[str, str],
    candidate_type: str,
) -> CandidateItem | None:
    clean_title = clean_text(title)
    if not _is_useful_html_candidate_title(clean_title):
        return None
    absolute_url = urljoin(source.url, href)
    canonical = canonicalize_url(absolute_url)
    summary = _job_board_summary(company, metadata)
    raw = {
        "title": clean_title,
        "url": absolute_url,
        "summary": summary,
        "html_candidate_type": candidate_type,
        **source.metadata,
    }
    if company:
        raw["company"] = company
    raw.update({key: value for key, value in metadata.items() if value})
    return CandidateItem(
        source_name=source.name,
        source_kind=source.kind,
        source_category=source.category,
        title=clean_title,
        url=absolute_url,
        canonical_url=canonical,
        summary=summary,
        content=metadata.get("description", ""),
        published_at=metadata.get("posted_age", ""),
        fetched_at=now_ict().isoformat(),
        fingerprint=fingerprint_text(clean_title, summary, canonical),
        raw=raw,
    )


def _fwddeploy_metadata_from_values(values: list[str], company: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    location_values: list[str] = []
    employment_values = {
        "full-time",
        "part-time",
        "contract",
        "internship",
        "temporary",
        "freelance",
    }
    for value in values:
        lowered = value.lower()
        if not value or value == company:
            continue
        if lowered in employment_values:
            metadata.setdefault("employment_type", value)
        elif re.search(r"\b\d+\s+(minute|hour|day|week|month|year)s?\b", lowered):
            metadata.setdefault("posted_age", value)
        elif "$" in value or " usd " in f" {lowered} " or "€" in value or "£" in value:
            metadata.setdefault("compensation", value)
        else:
            location_values.append(value)
    if location_values:
        metadata["location"] = " ".join(location_values[:2])
        country = _country_from_location(metadata["location"])
        if country:
            metadata["country"] = country
    if "remote" in metadata.get("location", "").lower():
        metadata["remote_policy"] = "Remote"
    return metadata


def _country_from_location(location: str) -> str:
    lowered = location.lower()
    country_terms = [
        ("Vietnam", ("vietnam", "viet nam", "ho chi minh", "hcmc", "hanoi", "saigon")),
        ("United States", ("united states", "usa", "u.s.")),
        ("Singapore", ("singapore",)),
        ("India", ("india", "bengaluru", "bangalore")),
        ("Malaysia", ("malaysia",)),
        ("Thailand", ("thailand",)),
        ("Indonesia", ("indonesia",)),
        ("Philippines", ("philippines",)),
        ("Hong Kong", ("hong kong",)),
        ("Taiwan", ("taiwan",)),
        ("Japan", ("japan",)),
        ("Korea", ("korea",)),
        ("Australia", ("australia",)),
    ]
    for country, terms in country_terms:
        if any(term in lowered for term in terms):
            return country
    return ""


def _job_board_summary(company: str, metadata: dict[str, str]) -> str:
    parts = []
    if company:
        parts.append(f"Company: {company}")
    if metadata.get("location"):
        parts.append(f"Location: {metadata['location']}")
    if metadata.get("remote_policy"):
        parts.append(f"Remote policy: {metadata['remote_policy']}")
    if metadata.get("employment_type"):
        parts.append(f"Employment: {metadata['employment_type']}")
    if metadata.get("compensation"):
        parts.append(f"Compensation: {metadata['compensation']}")
    if metadata.get("posted_age"):
        parts.append(f"Posted: {metadata['posted_age']}")
    if metadata.get("description"):
        parts.append(metadata["description"])
    return ". ".join(parts)


def _first_html_text(html_text: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html_text, flags=re.IGNORECASE | re.DOTALL)
    return _strip_html(match.group(1)) if match else ""


def _first_link_text(html_text: str) -> str:
    match = re.search(r"<a\b[^>]*>(.*?)</a>", html_text, flags=re.IGNORECASE | re.DOTALL)
    return _strip_html(match.group(1)) if match else ""


def _first_non_meta_paragraph(values: list[str]) -> str:
    employment_values = {"full-time", "part-time", "contract", "internship", "temporary", "freelance"}
    for value in values:
        lowered = value.lower()
        if lowered in employment_values:
            continue
        if re.search(r"\b\d+\s+(minute|hour|day|week|month|year)s?\b", lowered):
            continue
        if "$" in value or " usd " in f" {lowered} " or "€" in value or "£" in value:
            continue
        if "remote" in lowered or "," in value:
            continue
        return value
    return ""


def _alt_text_company(html_text: str) -> str:
    match = re.search(r"alt=[\"']([^\"']+?) logo[\"']", html_text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def _meta_content(html_text: str, name: str) -> str:
    pattern = (
        rf"<meta\b(?=[^>]*(?:name|property)=[\"']{re.escape(name)}[\"'])"
        r"(?=[^>]*content=[\"']([^\"']*)[\"'])[^>]*>"
    )
    match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    return clean_text(unescape(match.group(1))) if match else ""


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return clean_text(unescape(without_tags))


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if not value or key in seen:
            continue
        unique.append(value)
        seen.add(key)
    return unique


class _HTMLCandidateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self.headings: list[str] = []
        self.title = ""
        self._active_anchor: dict[str, object] | None = None
        self._active_heading: list[str] | None = None
        self._title_parts: list[str] | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attributes = dict(attrs)
        if tag == "a":
            self._active_anchor = {"href": attributes.get("href", ""), "parts": []}
        elif tag in {"h1", "h2", "h3", "h4"}:
            self._active_heading = []
        elif tag == "title":
            self._title_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag in {"script", "style", "svg", "noscript"}:
                self._skip_depth -= 1
            return
        if tag == "a" and self._active_anchor is not None:
            parts = self._active_anchor.get("parts", [])
            href = str(self._active_anchor.get("href", ""))
            title = clean_text(" ".join(str(part) for part in parts))
            if title and href:
                self.anchors.append((title, href))
            self._active_anchor = None
        elif tag in {"h1", "h2", "h3", "h4"} and self._active_heading is not None:
            title = clean_text(" ".join(self._active_heading))
            if title:
                self.headings.append(title)
            self._active_heading = None
        elif tag == "title" and self._title_parts is not None:
            self.title = clean_text(" ".join(self._title_parts))
            self._title_parts = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._active_anchor is not None:
            parts = self._active_anchor.setdefault("parts", [])
            if isinstance(parts, list):
                parts.append(data)
        if self._active_heading is not None:
            self._active_heading.append(data)
        if self._title_parts is not None:
            self._title_parts.append(data)


def _html_candidate(
    source: Source,
    title: str,
    url: str,
    page_title: str,
    candidate_type: str,
) -> CandidateItem | None:
    clean_title = clean_text(title)
    if not _is_useful_html_candidate_title(clean_title):
        return None
    absolute_url = urljoin(source.url, url)
    if absolute_url.startswith(("mailto:", "tel:", "javascript:")):
        return None
    canonical = canonicalize_url(absolute_url)
    summary = clean_text(page_title if candidate_type != "anchor" else "")
    return CandidateItem(
        source_name=source.name,
        source_kind=source.kind,
        source_category=source.category,
        title=clean_title,
        url=absolute_url,
        canonical_url=canonical,
        summary=summary,
        content="",
        fetched_at=now_ict().isoformat(),
        fingerprint=fingerprint_text(clean_title, summary, canonical),
        raw={"title": clean_title, "url": absolute_url, "summary": summary, "html_candidate_type": candidate_type, **source.metadata},
    )


def _json_ld_job_candidates(html_text: str, source: Source) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    for script_text in re.findall(
        r"<script\b(?=[^>]*type=[\"'][^\"']*application/ld\+json[^\"']*[\"'])[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            data = json.loads(unescape(script_text).strip())
        except (json.JSONDecodeError, TypeError):
            continue
        for posting in _iter_json_ld_job_postings(data):
            candidate = _candidate_from_json_ld(posting, source)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _iter_json_ld_job_postings(value):
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_job_postings(item)
        return
    if not isinstance(value, dict):
        return
    graph = value.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _iter_json_ld_job_postings(item)
    raw_type = value.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    if any(str(job_type).lower() == "jobposting" for job_type in types):
        yield value


def _candidate_from_json_ld(posting: dict, source: Source) -> CandidateItem | None:
    title = clean_text(posting.get("title", ""))
    if not title:
        return None
    org = _json_ld_name(posting.get("hiringOrganization"))
    location = _json_ld_location(posting.get("jobLocation") or posting.get("applicantLocationRequirements"))
    description = clean_text(re.sub(r"<[^>]+>", " ", str(posting.get("description", ""))))
    url = clean_text(posting.get("url", "")) or source.url
    canonical = canonicalize_url(urljoin(source.url, url))
    summary = clean_text(" ".join(part for part in (org, location, description) if part))
    return CandidateItem(
        source_name=source.name,
        source_kind=source.kind,
        source_category=source.category,
        title=title,
        url=urljoin(source.url, url),
        canonical_url=canonical,
        summary=summary,
        content="",
        published_at=clean_text(posting.get("datePosted", "")),
        fetched_at=now_ict().isoformat(),
        fingerprint=fingerprint_text(title, summary, canonical),
        raw={
            "title": title,
            "url": url,
            "summary": summary,
            "company": org,
            "location": location,
            "html_candidate_type": "json_ld_job",
            **source.metadata,
        },
    )


def _json_ld_name(value) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name", ""))
    return clean_text(value)


def _json_ld_location(value) -> str:
    if isinstance(value, list):
        return clean_text("; ".join(_json_ld_location(item) for item in value))
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, dict):
            return clean_text(" ".join(str(address.get(key, "")) for key in (
                "addressLocality",
                "addressRegion",
                "addressCountry",
            )))
        return clean_text(value.get("name", ""))
    return clean_text(value)


def _is_useful_html_candidate_title(title: str) -> bool:
    if len(title) < 5:
        return False
    lowered = title.lower()
    blocked = {
        "apply",
        "apply now",
        "sign in",
        "sign up",
        "log in",
        "privacy policy",
        "terms of service",
        "cookie settings",
        "see more",
        "next",
        "previous",
        "all jobs",
        "remote jobs",
        "careers",
        "home",
        "contact",
    }
    if lowered in blocked:
        return False
    if lowered.startswith(("image", "button:", "input")):
        return False
    return True


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
