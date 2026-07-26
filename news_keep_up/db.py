from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import CandidateItem, Enrichment, JobOpportunity, Settings, Source, SourceCandidate, SourceEvaluation


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
        """CREATE TABLE IF NOT EXISTS scheduler_runs (
            id INTEGER PRIMARY KEY,
            slot TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            triggered_at TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT DEFAULT '',
            message_length INTEGER DEFAULT 0
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduler_runs_slot_scheduled
           ON scheduler_runs(slot, scheduled_for)""",
        """CREATE INDEX IF NOT EXISTS idx_scheduler_runs_status
           ON scheduler_runs(status, scheduled_for)""",
        """CREATE TABLE IF NOT EXISTS job_opportunities (
            id TEXT PRIMARY KEY,
            source_item_id INTEGER REFERENCES items(id),
            source_fingerprint TEXT NOT NULL,
            crawled_at TEXT NOT NULL,
            priority TEXT NOT NULL,
            company TEXT NOT NULL,
            role_title TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            remote_policy TEXT NOT NULL,
            vietnam_eligibility TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            status TEXT NOT NULL,
            posted_date TEXT,
            source_type TEXT NOT NULL,
            source_url TEXT NOT NULL,
            apply_url TEXT,
            contact_person TEXT,
            contact_url TEXT,
            why_it_fits TEXT NOT NULL,
            what_to_verify TEXT NOT NULL,
            required_seniority TEXT,
            required_skills TEXT NOT NULL,
            domain TEXT NOT NULL,
            company_expansion_signal TEXT,
            linkedin_post_signal TEXT,
            recommended_action TEXT NOT NULL,
            outreach_angle TEXT,
            confidence_score INTEGER NOT NULL,
            should_alert INTEGER NOT NULL,
            alert_fingerprint TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE INDEX IF NOT EXISTS idx_job_opportunities_priority_status
           ON job_opportunities(priority, status, updated_at)""",
        """CREATE INDEX IF NOT EXISTS idx_job_opportunities_source_item
           ON job_opportunities(source_item_id)""",
        """CREATE TABLE IF NOT EXISTS job_alert_deliveries (
            id INTEGER PRIMARY KEY,
            opportunity_id TEXT NOT NULL REFERENCES job_opportunities(id),
            alert_fingerprint TEXT NOT NULL,
            delivered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_job_alert_deliveries_opportunity_fingerprint
           ON job_alert_deliveries(opportunity_id, alert_fingerprint)""",
        """CREATE TABLE IF NOT EXISTS source_candidates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            source_type TEXT NOT NULL,
            status TEXT NOT NULL,
            score INTEGER NOT NULL,
            discovered_from TEXT NOT NULL,
            reason TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE INDEX IF NOT EXISTS idx_source_candidates_status_score
           ON source_candidates(status, score, updated_at)""",
        """CREATE TABLE IF NOT EXISTS source_evaluations (
            id INTEGER PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            evaluation_date TEXT NOT NULL,
            fetched_items_7d INTEGER NOT NULL,
            opportunities_7d INTEGER NOT NULL,
            alerts_7d INTEGER NOT NULL,
            score INTEGER NOT NULL,
            verdict TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_source_evaluations_source_date
           ON source_evaluations(source_url, evaluation_date)""",
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


def get_job_opportunity_source_fingerprint(conn, source_item_id: int) -> str | None:
    row = conn.execute(
        """SELECT source_fingerprint
           FROM job_opportunities
           WHERE source_item_id=?
           ORDER BY updated_at DESC
           LIMIT 1""",
        (source_item_id,),
    ).fetchone()
    if not row:
        return None
    return str(row_value(row, "source_fingerprint", 0))


def upsert_job_opportunity(conn, opportunity: JobOpportunity) -> tuple[bool, bool]:
    existing = conn.execute(
        "SELECT alert_fingerprint FROM job_opportunities WHERE id=?",
        (opportunity.id,),
    ).fetchone()
    values = _job_opportunity_values(opportunity)
    if existing:
        previous_fingerprint = str(row_value(existing, "alert_fingerprint", 0))
        conn.execute(
            """UPDATE job_opportunities
               SET source_item_id=?, source_fingerprint=?, crawled_at=?, priority=?,
                   company=?, role_title=?, category=?, location=?, remote_policy=?,
                   vietnam_eligibility=?, evidence_type=?, status=?, posted_date=?,
                   source_type=?, source_url=?, apply_url=?, contact_person=?,
                   contact_url=?, why_it_fits=?, what_to_verify=?, required_seniority=?,
                   required_skills=?, domain=?, company_expansion_signal=?,
                   linkedin_post_signal=?, recommended_action=?, outreach_angle=?,
                   confidence_score=?, should_alert=?, alert_fingerprint=?, raw_json=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (*values, opportunity.id),
        )
        conn.commit()
        return False, previous_fingerprint != opportunity.alert_fingerprint

    conn.execute(
        """INSERT INTO job_opportunities (
               id, source_item_id, source_fingerprint, crawled_at, priority, company,
               role_title, category, location, remote_policy, vietnam_eligibility,
               evidence_type, status, posted_date, source_type, source_url, apply_url,
               contact_person, contact_url, why_it_fits, what_to_verify,
               required_seniority, required_skills, domain, company_expansion_signal,
               linkedin_post_signal, recommended_action, outreach_angle,
               confidence_score, should_alert, alert_fingerprint, raw_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (opportunity.id, *values),
    )
    conn.commit()
    return True, True


def _job_opportunity_values(opportunity: JobOpportunity) -> tuple[Any, ...]:
    raw = {
        "id": opportunity.id,
        "source_item_id": opportunity.source_item_id,
        "source_fingerprint": opportunity.source_fingerprint,
        "crawled_at": opportunity.crawled_at,
        "priority": opportunity.priority,
        "company": opportunity.company,
        "role_title": opportunity.role_title,
        "category": opportunity.category,
        "location": opportunity.location,
        "remote_policy": opportunity.remote_policy,
        "vietnam_eligibility": opportunity.vietnam_eligibility,
        "evidence_type": opportunity.evidence_type,
        "status": opportunity.status,
        "posted_date": opportunity.posted_date,
        "source_type": opportunity.source_type,
        "source_url": opportunity.source_url,
        "apply_url": opportunity.apply_url,
        "contact_person": opportunity.contact_person,
        "contact_url": opportunity.contact_url,
        "why_it_fits": opportunity.why_it_fits,
        "what_to_verify": opportunity.what_to_verify,
        "required_seniority": opportunity.required_seniority,
        "required_skills": opportunity.required_skills,
        "domain": opportunity.domain,
        "company_expansion_signal": opportunity.company_expansion_signal,
        "linkedin_post_signal": opportunity.linkedin_post_signal,
        "recommended_action": opportunity.recommended_action,
        "outreach_angle": opportunity.outreach_angle,
        "confidence_score": opportunity.confidence_score,
        "should_alert": opportunity.should_alert,
    }
    return (
        opportunity.source_item_id,
        opportunity.source_fingerprint,
        opportunity.crawled_at,
        opportunity.priority,
        opportunity.company,
        opportunity.role_title,
        opportunity.category,
        opportunity.location,
        opportunity.remote_policy,
        opportunity.vietnam_eligibility,
        opportunity.evidence_type,
        opportunity.status,
        opportunity.posted_date,
        opportunity.source_type,
        opportunity.source_url,
        opportunity.apply_url,
        opportunity.contact_person,
        opportunity.contact_url,
        opportunity.why_it_fits,
        json.dumps(opportunity.what_to_verify, ensure_ascii=True),
        opportunity.required_seniority,
        json.dumps(opportunity.required_skills, ensure_ascii=True),
        json.dumps(opportunity.domain, ensure_ascii=True),
        opportunity.company_expansion_signal,
        opportunity.linkedin_post_signal,
        opportunity.recommended_action,
        opportunity.outreach_angle,
        opportunity.confidence_score,
        int(opportunity.should_alert),
        opportunity.alert_fingerprint,
        json.dumps(raw, ensure_ascii=True),
    )


def job_alert_was_delivered(conn, opportunity_id: str, alert_fingerprint: str) -> bool:
    row = conn.execute(
        """SELECT 1
           FROM job_alert_deliveries
           WHERE opportunity_id=? AND alert_fingerprint=?
           LIMIT 1""",
        (opportunity_id, alert_fingerprint),
    ).fetchone()
    return row is not None


def mark_job_alert_delivered(conn, opportunity_id: str, alert_fingerprint: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO job_alert_deliveries (opportunity_id, alert_fingerprint)
           VALUES (?, ?)""",
        (opportunity_id, alert_fingerprint),
    )
    conn.commit()


def list_pending_job_alerts(conn, limit: int = 20) -> list[JobOpportunity]:
    rows = conn.execute(
        """SELECT id, source_item_id, source_fingerprint, crawled_at, priority, company,
                  role_title, category, location, remote_policy, vietnam_eligibility,
                  evidence_type, status, posted_date, source_type, source_url, apply_url,
                  contact_person, contact_url, why_it_fits, what_to_verify,
                  required_seniority, required_skills, domain, company_expansion_signal,
                  linkedin_post_signal, recommended_action, outreach_angle,
                  confidence_score, should_alert
           FROM job_opportunities jo
           WHERE should_alert=1
             AND priority IN ('High', 'Medium')
             AND status <> 'closed'
             AND NOT EXISTS (
                 SELECT 1
                 FROM job_alert_deliveries jad
                 WHERE jad.opportunity_id = jo.id
                   AND jad.alert_fingerprint = jo.alert_fingerprint
             )
           ORDER BY updated_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [_job_opportunity_from_row(row) for row in rows]


def _job_opportunity_from_row(row) -> JobOpportunity:
    return JobOpportunity(
        id=str(row_value(row, "id", 0)),
        source_item_id=int(row_value(row, "source_item_id", 1)),
        source_fingerprint=str(row_value(row, "source_fingerprint", 2)),
        crawled_at=str(row_value(row, "crawled_at", 3)),
        priority=str(row_value(row, "priority", 4)),
        company=str(row_value(row, "company", 5)),
        role_title=str(row_value(row, "role_title", 6)),
        category=str(row_value(row, "category", 7)),
        location=str(row_value(row, "location", 8)),
        remote_policy=str(row_value(row, "remote_policy", 9)),
        vietnam_eligibility=str(row_value(row, "vietnam_eligibility", 10)),
        evidence_type=str(row_value(row, "evidence_type", 11)),
        status=str(row_value(row, "status", 12)),
        posted_date=str(row_value(row, "posted_date", 13) or ""),
        source_type=str(row_value(row, "source_type", 14)),
        source_url=str(row_value(row, "source_url", 15)),
        apply_url=str(row_value(row, "apply_url", 16) or ""),
        contact_person=str(row_value(row, "contact_person", 17) or ""),
        contact_url=str(row_value(row, "contact_url", 18) or ""),
        why_it_fits=str(row_value(row, "why_it_fits", 19)),
        what_to_verify=_json_list(row_value(row, "what_to_verify", 20)),
        required_seniority=str(row_value(row, "required_seniority", 21) or ""),
        required_skills=_json_list(row_value(row, "required_skills", 22)),
        domain=_json_list(row_value(row, "domain", 23)),
        company_expansion_signal=str(row_value(row, "company_expansion_signal", 24) or ""),
        linkedin_post_signal=str(row_value(row, "linkedin_post_signal", 25) or ""),
        recommended_action=str(row_value(row, "recommended_action", 26)),
        outreach_angle=str(row_value(row, "outreach_angle", 27) or ""),
        confidence_score=int(row_value(row, "confidence_score", 28)),
        should_alert=bool(row_value(row, "should_alert", 29)),
    )


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def upsert_source_candidate(conn, candidate: SourceCandidate) -> tuple[bool, bool]:
    existing = conn.execute(
        "SELECT id, fingerprint FROM source_candidates WHERE url=?",
        (candidate.url,),
    ).fetchone()
    values = (
        candidate.id,
        candidate.name,
        candidate.kind,
        candidate.url,
        candidate.category,
        candidate.source_type,
        candidate.status,
        candidate.score,
        candidate.discovered_from,
        candidate.reason,
        candidate.fingerprint,
    )
    if existing:
        previous_fingerprint = str(row_value(existing, "fingerprint", 1))
        conn.execute(
            """UPDATE source_candidates
               SET id=?, name=?, kind=?, category=?, source_type=?, status=?, score=?,
                   discovered_from=?, reason=?, fingerprint=?, updated_at=CURRENT_TIMESTAMP
               WHERE url=?""",
            (
                candidate.id,
                candidate.name,
                candidate.kind,
                candidate.category,
                candidate.source_type,
                candidate.status,
                candidate.score,
                candidate.discovered_from,
                candidate.reason,
                candidate.fingerprint,
                candidate.url,
            ),
        )
        conn.commit()
        return False, previous_fingerprint != candidate.fingerprint

    conn.execute(
        """INSERT INTO source_candidates (
               id, name, kind, url, category, source_type, status, score,
               discovered_from, reason, fingerprint
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        values,
    )
    conn.commit()
    return True, True


def list_source_candidates(conn, status: str | None = None, limit: int = 50) -> list[SourceCandidate]:
    conditions: list[str] = []
    params: list[object] = []
    if status is not None:
        conditions.append("status=?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""SELECT id, name, kind, url, category, source_type, status, score,
                   discovered_from, reason
            FROM source_candidates
            {where}
            ORDER BY score DESC, updated_at DESC
            LIMIT ?""",
        (*params, limit),
    ).fetchall()
    return [
        SourceCandidate(
            id=str(row_value(row, "id", 0)),
            name=str(row_value(row, "name", 1)),
            kind=str(row_value(row, "kind", 2)),
            url=str(row_value(row, "url", 3)),
            category=str(row_value(row, "category", 4)),
            source_type=str(row_value(row, "source_type", 5)),
            status=str(row_value(row, "status", 6)),
            score=int(row_value(row, "score", 7)),
            discovered_from=str(row_value(row, "discovered_from", 8)),
            reason=str(row_value(row, "reason", 9)),
        )
        for row in rows
    ]


def record_source_evaluation(conn, evaluation: SourceEvaluation) -> None:
    conn.execute(
        """INSERT INTO source_evaluations (
               source_name, source_url, evaluation_date, fetched_items_7d,
               opportunities_7d, alerts_7d, score, verdict, reason
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_url, evaluation_date) DO UPDATE SET
               source_name=excluded.source_name,
               fetched_items_7d=excluded.fetched_items_7d,
               opportunities_7d=excluded.opportunities_7d,
               alerts_7d=excluded.alerts_7d,
               score=excluded.score,
               verdict=excluded.verdict,
               reason=excluded.reason""",
        (
            evaluation.source_name,
            evaluation.source_url,
            evaluation.evaluation_date,
            evaluation.fetched_items_7d,
            evaluation.opportunities_7d,
            evaluation.alerts_7d,
            evaluation.score,
            evaluation.verdict,
            evaluation.reason,
        ),
    )
    conn.commit()


def claim_scheduler_run(
    conn,
    slot: str,
    scheduled_for: str,
    triggered_at: str,
    stale_after_minutes: int = 30,
) -> bool:
    row = conn.execute(
        """SELECT status, triggered_at
           FROM scheduler_runs
           WHERE slot=? AND scheduled_for=?""",
        (slot, scheduled_for),
    ).fetchone()
    if row:
        status = str(row_value(row, "status", 0))
        previous_trigger = str(row_value(row, "triggered_at", 1))
        if status == "done":
            return False
        if status == "running" and _scheduler_trigger_is_fresh(
            previous_trigger,
            triggered_at,
            stale_after_minutes,
        ):
            return False
        conn.execute(
            """UPDATE scheduler_runs
               SET triggered_at=?, status='running', error='', message_length=0
               WHERE slot=? AND scheduled_for=?""",
            (triggered_at, slot, scheduled_for),
        )
        conn.commit()
        return True

    conn.execute(
        """INSERT INTO scheduler_runs (slot, scheduled_for, triggered_at, status)
           VALUES (?, ?, ?, 'running')""",
        (slot, scheduled_for, triggered_at),
    )
    conn.commit()
    return True


def finish_scheduler_run(
    conn,
    slot: str,
    scheduled_for: str,
    status: str,
    message_length: int = 0,
    error: str = "",
) -> None:
    conn.execute(
        """UPDATE scheduler_runs
           SET status=?, message_length=?, error=?
           WHERE slot=? AND scheduled_for=?""",
        (status, message_length, error[:500], slot, scheduled_for),
    )
    conn.commit()


def _scheduler_trigger_is_fresh(previous_trigger: str, current_trigger: str, stale_after_minutes: int) -> bool:
    try:
        previous = datetime.fromisoformat(previous_trigger)
        current = datetime.fromisoformat(current_trigger)
    except ValueError:
        return False
    return current - previous < timedelta(minutes=stale_after_minutes)
