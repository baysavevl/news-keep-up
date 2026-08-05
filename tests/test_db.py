import tempfile
import unittest
from pathlib import Path

from news_keep_up.db import (
    claim_scheduler_run,
    connect_database,
    count_llm_calls_today,
    finish_scheduler_run,
    get_enrichment,
    get_job_opportunity_source_fingerprint,
    get_profile_setting,
    job_alert_was_delivered,
    list_pending_job_alerts,
    list_source_candidates,
    init_db,
    mark_job_alert_delivered,
    mark_delivered,
    record_source_evaluation,
    record_source_fetch_log,
    record_source_fetch_logs,
    record_llm_usage,
    list_source_fetch_health,
    upsert_enrichment,
    upsert_item,
    upsert_job_opportunity,
    upsert_profile_setting,
    upsert_source_candidate,
    upsert_source,
)
from news_keep_up.models import (
    CandidateItem,
    Enrichment,
    JobOpportunity,
    SourceCandidate,
    SourceEvaluation,
    SourceFetchLog,
    Settings,
    Source,
)


def make_item(title: str = "AI agents for engineers") -> CandidateItem:
    return CandidateItem(
        source_name="Latent Space",
        source_kind="rss",
        source_category="ai-engineering",
        title=title,
        url="https://example.com/post?utm_source=x",
        canonical_url="https://example.com/post",
        summary="A useful article about AI agents.",
        content="",
        author="",
        published_at="2026-07-06T03:00:00+00:00",
        fetched_at="2026-07-06T03:01:00+00:00",
        fingerprint="abc",
        raw={"id": "1"},
    )


def make_enrichment(score: int = 88) -> Enrichment:
    return Enrichment(
        model="gemini-2.5-flash-lite",
        relevance_score=score,
        category="ai-engineering",
        topic="coding-agents",
        icon="AI",
        title_vi="Tác nhân AI cho kỹ sư",
        summary="This explains how coding agents change engineering workflows.",
        why_it_matters="Useful for designing agent-assisted delivery workflows.",
        takeaway_vi="Nên thử nghiệm agent trong quy trình giao việc nhỏ.",
        should_send=True,
    )


def make_job_opportunity(
    opportunity_id: str = "wonderful-forward-deployed-engineer-vietnam",
    priority: str = "High",
    source_fingerprint: str = "job-fp-1",
) -> JobOpportunity:
    return JobOpportunity(
        id=opportunity_id,
        source_item_id=1,
        source_fingerprint=source_fingerprint,
        crawled_at="2026-07-27",
        priority=priority,
        company="Wonderful",
        role_title="Forward Deployed Engineer",
        category="Exact FDE Role",
        location="Vietnam",
        remote_policy="Remote Vietnam possible",
        vietnam_eligibility="explicit_yes",
        evidence_type="Hard",
        status="open",
        posted_date="",
        source_type="ATS",
        source_url="https://example.com/jobs/fde",
        apply_url="https://example.com/jobs/fde/apply",
        contact_person="",
        contact_url="",
        why_it_fits="Exact FDE role with Vietnam eligibility.",
        what_to_verify=["Compensation range"],
        required_seniority="Senior",
        required_skills=["LLM", "customer deployment"],
        domain=["enterprise AI"],
        company_expansion_signal="",
        linkedin_post_signal="",
        recommended_action="apply_now",
        outreach_angle="Emphasize AI deployment work in Vietnam.",
        confidence_score=94,
        should_alert=True,
    )


class DatabaseTest(unittest.TestCase):
    def test_upsert_source_and_item_dedupes_by_canonical_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            source = Source("Latent Space", "rss", "https://www.latent.space/feed", "ai-engineering")
            first_source_id = upsert_source(conn, source)
            second_source_id = upsert_source(conn, source)
            self.assertEqual(first_source_id, second_source_id)

            first_item_id, first_is_new = upsert_item(conn, make_item())
            second_item_id, second_is_new = upsert_item(conn, make_item("Updated title"))

            self.assertEqual(first_item_id, second_item_id)
            self.assertTrue(first_is_new)
            self.assertFalse(second_is_new)

    def test_enrichment_is_cached_by_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            self.assertIsNone(get_enrichment(conn, item_id))
            upsert_enrichment(conn, item_id, make_enrichment())
            cached = get_enrichment(conn, item_id)

            self.assertIsNotNone(cached)
            self.assertEqual(cached.title_vi, "Tác nhân AI cho kỹ sư")
            self.assertEqual(cached.relevance_score, 88)

    def test_delivery_and_llm_usage_are_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            record_llm_usage(conn, "gemini-2.5-flash-lite", "2026-07-06", "morning", item_id, "ok")
            record_llm_usage(conn, "gemini-2.5-flash-lite", "2026-07-06", "morning", item_id, "fallback")
            mark_delivered(conn, [item_id], "morning", {item_id})
            mark_delivered(conn, [item_id], "morning", {item_id})

            self.assertEqual(count_llm_calls_today(conn, "2026-07-06"), 2)
            row = conn.execute("SELECT is_backfill FROM deliveries WHERE item_id=?", (item_id,)).fetchone()
            self.assertEqual(row["is_backfill"], 1)
            count = conn.execute("SELECT COUNT(*) AS count FROM deliveries WHERE item_id=?", (item_id,)).fetchone()
            self.assertEqual(count["count"], 1)

    def test_scheduler_run_claims_once_and_marks_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            scheduled_for = "2026-07-14T10:20:00+07:00"
            self.assertTrue(claim_scheduler_run(conn, "fde", scheduled_for, "2026-07-14T10:21:00+07:00"))
            self.assertFalse(claim_scheduler_run(conn, "fde", scheduled_for, "2026-07-14T10:22:00+07:00"))

            finish_scheduler_run(conn, "fde", scheduled_for, "done", message_length=123)
            self.assertFalse(claim_scheduler_run(conn, "fde", scheduled_for, "2026-07-14T10:55:00+07:00"))

            row = conn.execute(
                "SELECT status, message_length FROM scheduler_runs WHERE slot=? AND scheduled_for=?",
                ("fde", scheduled_for),
            ).fetchone()
            self.assertEqual(row["status"], "done")
            self.assertEqual(row["message_length"], 123)

    def test_job_opportunity_upsert_tracks_material_changes_and_alert_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            opportunity = make_job_opportunity()
            opportunity = JobOpportunity(**{**opportunity.__dict__, "source_item_id": item_id})
            inserted, changed = upsert_job_opportunity(conn, opportunity)

            self.assertTrue(inserted)
            self.assertTrue(changed)
            self.assertEqual(get_job_opportunity_source_fingerprint(conn, 1), "job-fp-1")
            self.assertFalse(job_alert_was_delivered(conn, opportunity.id, opportunity.alert_fingerprint))

            mark_job_alert_delivered(conn, opportunity.id, opportunity.alert_fingerprint)
            self.assertTrue(job_alert_was_delivered(conn, opportunity.id, opportunity.alert_fingerprint))

            inserted, changed = upsert_job_opportunity(conn, opportunity)
            self.assertFalse(inserted)
            self.assertFalse(changed)

            updated = make_job_opportunity(priority="Medium", source_fingerprint="job-fp-2")
            updated = JobOpportunity(**{**updated.__dict__, "source_item_id": item_id})
            inserted, changed = upsert_job_opportunity(conn, updated)

            self.assertFalse(inserted)
            self.assertTrue(changed)
            self.assertEqual(get_job_opportunity_source_fingerprint(conn, 1), "job-fp-2")

    def test_pending_job_alerts_include_low_and_watch_states_until_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            low = make_job_opportunity(priority="Low")
            low = JobOpportunity(**{
                **low.__dict__,
                "source_item_id": item_id,
                "status": "watch",
                "category": "Watchlist Company",
                "should_alert": False,
                "confidence_score": 25,
            })
            upsert_job_opportunity(conn, low)

            pending = list_pending_job_alerts(conn)
            self.assertEqual([opportunity.id for opportunity in pending], [low.id])

            mark_job_alert_delivered(conn, low.id, low.alert_fingerprint)
            self.assertEqual(list_pending_job_alerts(conn), [])

    def test_pending_job_alerts_exclude_closed_and_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            closed = make_job_opportunity("closed-fde-role")
            closed = JobOpportunity(**{**closed.__dict__, "source_item_id": item_id, "status": "closed"})
            rejected = make_job_opportunity("rejected-fde-role")
            rejected = JobOpportunity(**{**rejected.__dict__, "source_item_id": item_id, "category": "Reject"})
            upsert_job_opportunity(conn, closed)
            upsert_job_opportunity(conn, rejected)

            self.assertEqual(list_pending_job_alerts(conn), [])

    def test_pending_job_alerts_dedupe_by_delivered_apply_or_source_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)
            item_id, _ = upsert_item(conn, make_item())

            original = make_job_opportunity("fwddeploy-remote-jobs-clera")
            original = JobOpportunity(**{
                **original.__dict__,
                "source_item_id": item_id,
                "company": "FWDDeploy Remote Jobs",
                "source_url": "https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
                "apply_url": "https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
            })
            corrected = make_job_opportunity("clera-founding-forward-deployed-engineer")
            corrected = JobOpportunity(**{
                **corrected.__dict__,
                "source_item_id": item_id,
                "company": "Clera",
                "source_url": "https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
                "apply_url": "https://www.fwddeploy.com/jobs/founding-forward-deployed-engineer-53cfcb31",
            })

            upsert_job_opportunity(conn, original)
            mark_job_alert_delivered(conn, original.id, original.alert_fingerprint)
            upsert_job_opportunity(conn, corrected)

            self.assertEqual(list_pending_job_alerts(conn), [])

    def test_profile_settings_are_upserted(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            upsert_profile_setting(conn, "fde-jobs", "telegram_chat_id", "-100999")
            upsert_profile_setting(conn, "fde-jobs", "telegram_chat_id", "-100888")

            self.assertEqual(get_profile_setting(conn, "fde-jobs", "telegram_chat_id"), "-100888")
            self.assertEqual(get_profile_setting(conn, "fde", "telegram_chat_id"), "")

    def test_source_candidates_and_evaluations_are_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            candidate = SourceCandidate(
                id="ashby-fde-apac",
                name="Ashby FDE APAC",
                kind="rss",
                url="https://www.bing.com/search?q=site%3Ajobs.ashbyhq.com+FDE+APAC&format=rss",
                category="ats-index-search",
                source_type="ATS",
                status="candidate",
                score=84,
                discovered_from="Bing source discovery",
                reason="Finds indexed Ashby FDE roles in APAC.",
            )
            inserted, changed = upsert_source_candidate(conn, candidate)
            inserted_again, changed_again = upsert_source_candidate(conn, candidate)

            self.assertTrue(inserted)
            self.assertTrue(changed)
            self.assertFalse(inserted_again)
            self.assertFalse(changed_again)
            self.assertEqual(list_source_candidates(conn, status="candidate")[0].url, candidate.url)

            evaluation = SourceEvaluation(
                source_name="Bing FDE Vietnam",
                source_url="https://www.bing.com/search?q=fde&format=rss",
                evaluation_date="2026-07-27",
                fetched_items_7d=12,
                opportunities_7d=3,
                alerts_7d=1,
                score=88,
                verdict="keep",
                reason="Produced one alert and several relevant opportunities.",
            )
            record_source_evaluation(conn, evaluation)

            row = conn.execute(
                "SELECT score, verdict FROM source_evaluations WHERE source_name=?",
                ("Bing FDE Vietnam",),
            ).fetchone()
            self.assertEqual(row["score"], 88)
            self.assertEqual(row["verdict"], "keep")

    def test_source_fetch_health_ranks_failed_and_empty_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            record_source_fetch_log(conn, SourceFetchLog(
                slot="fde-jobs",
                source_name="Upwork Direct Search",
                source_url="https://www.upwork.com/nx/search/jobs/?q=fde",
                source_kind="html",
                status="failed",
                item_count=0,
                error_type="HTTPError",
                error_message="HTTP Error 403: Forbidden",
                fetched_at="2026-08-04T08:00:00+07:00",
            ))
            record_source_fetch_log(conn, SourceFetchLog(
                slot="fde-jobs",
                source_name="Upwork Direct Search",
                source_url="https://www.upwork.com/nx/search/jobs/?q=fde",
                source_kind="html",
                status="failed",
                item_count=0,
                error_type="HTTPError",
                error_message="HTTP Error 403: Forbidden",
                fetched_at="2026-08-04T08:30:00+07:00",
            ))
            record_source_fetch_log(conn, SourceFetchLog(
                slot="fde-jobs",
                source_name="Bing FDE Vietnam",
                source_url="https://www.bing.com/search?q=fde&format=rss",
                source_kind="rss",
                status="ok",
                item_count=0,
                fetched_at="2026-08-04T08:30:00+07:00",
            ))
            record_source_fetch_log(conn, SourceFetchLog(
                slot="fde-jobs",
                source_name="FWDDeploy Remote Jobs",
                source_url="https://www.fwddeploy.com/jobs",
                source_kind="html",
                status="ok",
                item_count=7,
                fetched_at="2026-08-04T08:30:00+07:00",
            ))

            health = list_source_fetch_health(
                conn,
                slot="fde-jobs",
                since="2026-08-03T00:00:00+07:00",
                limit=3,
            )

        self.assertEqual(health[0].source_name, "Upwork Direct Search")
        self.assertEqual(health[0].failed_runs, 2)
        self.assertEqual(health[0].last_status, "failed")
        self.assertIn("403", health[0].last_error)
        self.assertEqual(health[1].source_name, "Bing FDE Vietnam")
        self.assertEqual(health[1].empty_runs, 1)

    def test_source_fetch_logs_can_be_recorded_in_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_database(Settings(db_path=Path(tmp) / "test.db"))
            init_db(conn)

            record_source_fetch_logs(conn, [
                SourceFetchLog(
                    slot="fde-jobs",
                    source_name="RemoteOK AI API Jobs",
                    source_url="https://remoteok.com/api?tags=ai",
                    source_kind="json",
                    status="ok",
                    item_count=12,
                    fetched_at="2026-08-04T08:00:00+07:00",
                ),
                SourceFetchLog(
                    slot="fde-jobs",
                    source_name="AIJobs.net Remote AI Jobs",
                    source_url="https://aijobs.net/?prefill_remote=1",
                    source_kind="html",
                    status="ok",
                    item_count=0,
                    fetched_at="2026-08-04T08:00:00+07:00",
                ),
            ])

            health = list_source_fetch_health(conn, slot="fde-jobs", limit=2)

        self.assertEqual(len(health), 2)
        self.assertEqual(sum(row.total_runs for row in health), 2)


if __name__ == "__main__":
    unittest.main()
