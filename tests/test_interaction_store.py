import sqlite3
import unittest

from news_keep_up.db import init_db
from news_keep_up.interaction_store import (
    complete_weekly_report,
    list_open_queue,
    load_engagement_delivery,
    load_stored_subject,
    mark_engagement_delivered,
    mark_engagement_failed,
    mark_queue_unavailable,
    plan_engagement_deliveries,
    record_interaction,
    release_weekly_report,
    reserve_weekly_report,
    weekly_metrics,
)
from news_keep_up.interactions import InteractionSubject


CREATED = "2026-08-21T10:00:00+07:00"


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def plan_and_deliver(
    conn,
    subjects,
    *,
    profile="engineer",
    chat_id="-1001",
    kind="content",
    message_id="700",
    created_at=CREATED,
):
    rows = plan_engagement_deliveries(
        conn,
        profile,
        chat_id,
        subjects,
        kind,
        created_at,
    )
    mark_engagement_delivered(conn, [row.id for row in rows], message_id, created_at)
    return rows


class InteractionStoreTest(unittest.TestCase):
    def test_init_db_creates_interaction_schema_idempotently(self):
        conn = connection()

        init_db(conn)
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        self.assertTrue(
            {
                "engagement_deliveries",
                "interaction_events",
                "action_queue",
                "weekly_report_deliveries",
            }.issubset(names)
        )
        conn.close()

    def test_delivery_lifecycle_assigns_ids_and_shared_message_id(self):
        conn = connection()

        rows = plan_engagement_deliveries(
            conn,
            "engineer",
            "-1001",
            [InteractionSubject("news", 1), InteractionSubject("news", 2)],
            "content",
            CREATED,
        )
        mark_engagement_delivered(conn, [row.id for row in rows], "700", CREATED)
        stored = [load_engagement_delivery(conn, row.id) for row in rows]

        self.assertEqual(len({row.id for row in rows}), 2)
        self.assertTrue(all(row.id > 0 for row in rows))
        self.assertEqual([row.delivery_state for row in stored], ["delivered", "delivered"])
        self.assertEqual([row.telegram_message_id for row in stored], ["700", "700"])
        conn.close()

    def test_failed_delivery_only_changes_planned_rows(self):
        conn = connection()
        rows = plan_engagement_deliveries(
            conn,
            "engineer",
            "-1001",
            [InteractionSubject("news", 1), InteractionSubject("news", 2)],
            "content",
            CREATED,
        )
        mark_engagement_delivered(conn, [rows[0].id], "700", CREATED)

        mark_engagement_failed(conn, [row.id for row in rows])

        self.assertEqual(load_engagement_delivery(conn, rows[0].id).delivery_state, "delivered")
        self.assertEqual(load_engagement_delivery(conn, rows[1].id).delivery_state, "failed")
        conn.close()

    def test_duplicate_callback_id_is_idempotent(self):
        conn = connection()
        delivery = plan_and_deliver(conn, [InteractionSubject("news", 1)])[0]

        first = record_interaction(conn, delivery.id, "useful", "42", "cb-1", CREATED)
        duplicate = record_interaction(conn, delivery.id, "useful", "42", "cb-1", CREATED)
        count = conn.execute("SELECT COUNT(*) FROM interaction_events").fetchone()[0]

        self.assertTrue(first.changed)
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(duplicate.changed)
        self.assertEqual(count, 1)
        conn.close()

    def test_repeating_current_action_is_a_successful_no_op(self):
        conn = connection()
        delivery = plan_and_deliver(conn, [InteractionSubject("news", 1)])[0]

        record_interaction(conn, delivery.id, "save", "42", "cb-1", CREATED)
        repeated = record_interaction(
            conn,
            delivery.id,
            "save",
            "42",
            "cb-2",
            "2026-08-21T10:01:00+07:00",
        )
        queue_count = conn.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0]

        self.assertFalse(repeated.duplicate)
        self.assertFalse(repeated.changed)
        self.assertEqual(queue_count, 1)
        conn.close()

    def test_record_interaction_rejects_an_action_for_the_wrong_subject(self):
        conn = connection()
        delivery = plan_and_deliver(conn, [InteractionSubject("job", "job-1")])[0]

        with self.assertRaises(ValueError):
            record_interaction(conn, delivery.id, "useful", "42", "cb-1", CREATED)

        self.assertEqual(conn.execute("SELECT COUNT(*) FROM interaction_events").fetchone()[0], 0)
        conn.close()

    def test_queue_is_scoped_to_actor_and_clamped_to_eight_rows(self):
        conn = connection()
        subjects = [InteractionSubject("news", index) for index in range(1, 11)]
        rows = plan_and_deliver(conn, subjects)
        for index, row in enumerate(rows, start=1):
            record_interaction(
                conn,
                row.id,
                "save",
                "42",
                f"cb-{index}",
                f"2026-08-21T10:{index:02d}:00+07:00",
            )
        other = plan_and_deliver(conn, [InteractionSubject("news", 99)], message_id="701")[0]
        record_interaction(conn, other.id, "save", "84", "cb-other", CREATED)

        mine = list_open_queue(conn, "engineer", "-1001", "42", limit=99)

        self.assertEqual(len(mine), 8)
        self.assertEqual(mine[0].subject_id, "10")
        self.assertNotIn("99", {entry.subject_id for entry in mine})
        conn.close()

    def test_mark_queue_unavailable_closes_only_the_target_row(self):
        conn = connection()
        rows = plan_and_deliver(
            conn,
            [InteractionSubject("news", 1), InteractionSubject("news", 2)],
        )
        record_interaction(conn, rows[0].id, "save", "42", "cb-1", CREATED)
        record_interaction(conn, rows[1].id, "save", "42", "cb-2", CREATED)

        mark_queue_unavailable(
            conn,
            "engineer",
            "-1001",
            "42",
            "news",
            "1",
            "2026-08-21T11:00:00+07:00",
        )

        self.assertEqual(
            [entry.subject_id for entry in list_open_queue(conn, "engineer", "-1001", "42")],
            ["2"],
        )
        conn.close()

    def test_load_stored_subject_resolves_news_and_job_links(self):
        conn = connection()
        conn.execute(
            """INSERT INTO items (
                   id, source_name, source_kind, source_category, title, url, canonical_url
               ) VALUES (1, 'Source', 'rss', 'ai', 'Agent article',
                         'https://example.com/article', 'https://example.com/article')"""
        )
        conn.execute(
            """INSERT INTO job_opportunities (
                   id, source_fingerprint, crawled_at, priority, company, role_title,
                   category, location, remote_policy, vietnam_eligibility,
                   evidence_type, status, source_type, source_url, apply_url,
                   why_it_fits, what_to_verify, required_skills, domain,
                   recommended_action, confidence_score, should_alert,
                   alert_fingerprint, raw_json
               ) VALUES (
                   'job-1', 'fp', '2026-08-21', 'High', 'Acme', 'FDE', 'Exact',
                   'Vietnam', 'Remote', 'yes', 'Hard', 'open', 'ATS',
                   'https://example.com/job', 'https://example.com/apply', 'fit',
                   '[]', '[]', '[]', 'apply_now', 90, 1, 'alert-fp', '{}'
               )"""
        )
        conn.commit()

        self.assertEqual(
            load_stored_subject(conn, "news", "1"),
            ("Agent article", "https://example.com/article"),
        )
        self.assertEqual(
            load_stored_subject(conn, "job", "job-1"),
            ("FDE · Acme", "https://example.com/apply"),
        )
        self.assertIsNone(load_stored_subject(conn, "news", "not-a-number"))
        conn.close()

    def test_weekly_metrics_excludes_queue_deliveries_from_denominator(self):
        conn = connection()
        content = plan_and_deliver(
            conn,
            [InteractionSubject("news", 1), InteractionSubject("news", 2)],
            created_at="2026-08-20T10:00:00+07:00",
        )
        queue = plan_and_deliver(
            conn,
            [InteractionSubject("news", 1)],
            kind="queue",
            message_id="701",
            created_at="2026-08-20T11:00:00+07:00",
        )[0]
        record_interaction(conn, content[0].id, "useful", "42", "cb-useful", "2026-08-20T12:00:00+07:00")
        record_interaction(conn, content[0].id, "save", "42", "cb-save", "2026-08-20T12:01:00+07:00")
        record_interaction(conn, content[1].id, "noise", "84", "cb-noise", "2026-08-20T12:02:00+07:00")
        record_interaction(conn, content[1].id, "save", "84", "cb-save-2", "2026-08-20T12:03:00+07:00")
        record_interaction(conn, queue.id, "done", "42", "cb-done", "2026-08-20T12:04:00+07:00")

        metrics = weekly_metrics(
            conn,
            "engineer",
            "-1001",
            "2026-08-17T00:00:00+07:00",
            "2026-08-24T00:00:00+07:00",
        )
        mine = weekly_metrics(
            conn,
            "engineer",
            "-1001",
            "2026-08-17T00:00:00+07:00",
            "2026-08-24T00:00:00+07:00",
            actor_user_id="42",
        )

        self.assertEqual(metrics.delivered, 2)
        self.assertEqual(metrics.responded, 2)
        self.assertEqual((metrics.useful, metrics.noise), (1, 1))
        self.assertEqual((metrics.queued, metrics.completed, metrics.open_items), (2, 1, 1))
        self.assertEqual(metrics.apply, 0)
        self.assertEqual((mine.responded, mine.useful, mine.noise), (1, 1, 0))
        self.assertEqual((mine.queued, mine.completed, mine.open_items), (1, 1, 0))
        conn.close()

    def test_weekly_reservation_is_unique_releasable_and_completable(self):
        conn = connection()

        self.assertTrue(reserve_weekly_report(conn, "engineer", "-1001", "2026-08-17", CREATED))
        self.assertFalse(reserve_weekly_report(conn, "engineer", "-1001", "2026-08-17", CREATED))
        release_weekly_report(conn, "engineer", "-1001", "2026-08-17")
        self.assertTrue(reserve_weekly_report(conn, "engineer", "-1001", "2026-08-17", CREATED))
        complete_weekly_report(
            conn,
            "engineer",
            "-1001",
            "2026-08-17",
            "2026-08-21T10:01:00+07:00",
        )

        self.assertFalse(
            reserve_weekly_report(
                conn,
                "engineer",
                "-1001",
                "2026-08-17",
                "2026-08-21T11:00:00+07:00",
            )
        )
        conn.close()

    def test_stale_weekly_reservation_can_be_reclaimed_after_fifteen_minutes(self):
        conn = connection()
        self.assertTrue(
            reserve_weekly_report(
                conn,
                "engineer",
                "-1001",
                "2026-08-17",
                "2026-08-21T09:00:00+07:00",
            )
        )

        self.assertFalse(
            reserve_weekly_report(
                conn,
                "engineer",
                "-1001",
                "2026-08-17",
                "2026-08-21T09:15:00+07:00",
            )
        )
        self.assertTrue(
            reserve_weekly_report(
                conn,
                "engineer",
                "-1001",
                "2026-08-17",
                "2026-08-21T09:15:01+07:00",
            )
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
