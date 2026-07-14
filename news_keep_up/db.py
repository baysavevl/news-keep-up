from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import CandidateItem, Enrichment, Settings, Source


def row_value(row, key: str, index: int):
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def connect_database(settings: Settings):
    if settings.turso_database_url:
        try:
            import libsql_experimental as libsql  # type: ignore
        except ImportError as exc:
            raise RuntimeError("TURSO_DATABASE_URL is set but libsql_experimental is not installed") from exc
        return libsql.connect(settings.turso_database_url, auth_token=settings.turso_auth_token or "")

    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn) -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            source_id INTEGER REFERENCES sources(id),
            source_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_category TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            canonical_url TEXT NOT NULL UNIQUE,
            summary TEXT,
            content TEXT,
            author TEXT,
            published_at TEXT,
            fetched_at TEXT,
            fingerprint TEXT,
            raw_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS enrichments (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL UNIQUE REFERENCES items(id),
            model TEXT NOT NULL,
            relevance_score INTEGER NOT NULL,
            category TEXT NOT NULL,
            topic TEXT NOT NULL,
            icon TEXT NOT NULL,
            title_vi TEXT NOT NULL,
            summary TEXT NOT NULL,
            why_it_matters TEXT NOT NULL,
            takeaway_vi TEXT NOT NULL,
            should_send INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items(id),
            slot TEXT NOT NULL,
            delivered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_backfill INTEGER DEFAULT 0
        )""",
        """DELETE FROM deliveries
           WHERE id NOT IN (
               SELECT MIN(id)
               FROM deliveries
               GROUP BY item_id, slot
           )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_deliveries_item_slot
           ON deliveries(item_id, slot)""",
        """CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            call_date TEXT NOT NULL,
            slot TEXT NOT NULL,
            item_id INTEGER REFERENCES items(id),
            status TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    for statement in statements:
        conn.execute(statement)
    conn.commit()


def upsert_source(conn, source: Source) -> int:
    row = conn.execute("SELECT id FROM sources WHERE url=?", (source.url,)).fetchone()
    if row:
        source_id = int(row_value(row, "id", 0))
        conn.execute(
            """UPDATE sources
               SET name=?, type=?, category=?, enabled=?
               WHERE id=?""",
            (source.name, source.kind, source.category, int(source.enabled), source_id),
        )
        conn.commit()
        return source_id

    conn.execute(
        """INSERT INTO sources (name, type, url, category, enabled)
           VALUES (?, ?, ?, ?, ?)""",
        (source.name, source.kind, source.url, source.category, int(source.enabled)),
    )
    conn.commit()
    inserted = conn.execute("SELECT id FROM sources WHERE url=?", (source.url,)).fetchone()
    return int(row_value(inserted, "id", 0))


def upsert_item(conn, item: CandidateItem) -> tuple[int, bool]:
    row = conn.execute("SELECT id FROM items WHERE canonical_url=?", (item.canonical_url,)).fetchone()
    values = _item_values(item)
    if row:
        item_id = int(row_value(row, "id", 0))
        conn.execute(
            """UPDATE items
               SET source_name=?, source_kind=?, source_category=?, title=?, url=?,
                   summary=?, content=?, author=?, published_at=?, fetched_at=?,
                   fingerprint=?, raw_json=?
               WHERE id=?""",
            (*values, item_id),
        )
        conn.commit()
        return item_id, False

    conn.execute(
        """INSERT INTO items (
               source_name, source_kind, source_category, title, url, summary, content,
               author, published_at, fetched_at, fingerprint, raw_json, canonical_url
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (*values, item.canonical_url),
    )
    conn.commit()
    inserted = conn.execute("SELECT id FROM items WHERE canonical_url=?", (item.canonical_url,)).fetchone()
    return int(row_value(inserted, "id", 0)), True


def _item_values(item: CandidateItem) -> tuple[Any, ...]:
    return (
        item.source_name,
        item.source_kind,
        item.source_category,
        item.title,
        item.url,
        item.summary,
        item.content,
        item.author,
        item.published_at,
        item.fetched_at,
        item.fingerprint,
        json.dumps(item.raw, ensure_ascii=True),
    )


def get_enrichment(conn, item_id: int) -> Enrichment | None:
    row = conn.execute(
        """SELECT model, relevance_score, category, topic, icon, title_vi, summary,
                  why_it_matters, takeaway_vi, should_send
           FROM enrichments WHERE item_id=?""",
        (item_id,),
    ).fetchone()
    if not row:
        return None
    return Enrichment(
        model=row_value(row, "model", 0),
        relevance_score=int(row_value(row, "relevance_score", 1)),
        category=row_value(row, "category", 2),
        topic=row_value(row, "topic", 3),
        icon=row_value(row, "icon", 4),
        title_vi=row_value(row, "title_vi", 5),
        summary=row_value(row, "summary", 6),
        why_it_matters=row_value(row, "why_it_matters", 7),
        takeaway_vi=row_value(row, "takeaway_vi", 8),
        should_send=bool(row_value(row, "should_send", 9)),
    )


def upsert_enrichment(conn, item_id: int, enrichment: Enrichment) -> None:
    conn.execute(
        """INSERT INTO enrichments (
               item_id, model, relevance_score, category, topic, icon, title_vi,
               summary, why_it_matters, takeaway_vi, should_send
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(item_id) DO UPDATE SET
               model=excluded.model,
               relevance_score=excluded.relevance_score,
               category=excluded.category,
               topic=excluded.topic,
               icon=excluded.icon,
               title_vi=excluded.title_vi,
               summary=excluded.summary,
               why_it_matters=excluded.why_it_matters,
               takeaway_vi=excluded.takeaway_vi,
               should_send=excluded.should_send""",
        (
            item_id,
            enrichment.model,
            enrichment.relevance_score,
            enrichment.category,
            enrichment.topic,
            enrichment.icon,
            enrichment.title_vi,
            enrichment.summary,
            enrichment.why_it_matters,
            enrichment.takeaway_vi,
            int(enrichment.should_send),
        ),
    )
    conn.commit()


def mark_delivered(conn, item_ids: list[int], slot: str, backfill_ids: set[int]) -> None:
    for item_id in item_ids:
        conn.execute(
            """INSERT OR IGNORE INTO deliveries (item_id, slot, is_backfill)
               VALUES (?, ?, ?)""",
            (item_id, slot, int(item_id in backfill_ids)),
        )
    conn.commit()


def record_llm_usage(conn, model: str, call_date: str, slot: str, item_id: int | None, status: str) -> None:
    conn.execute(
        """INSERT INTO llm_usage (model, call_date, slot, item_id, status)
           VALUES (?, ?, ?, ?, ?)""",
        (model, call_date, slot, item_id, status),
    )
    conn.commit()


def count_llm_calls_today(conn, call_date: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM llm_usage WHERE call_date=?", (call_date,)).fetchone()
    return int(row_value(row, "count", 0) if row else 0)
