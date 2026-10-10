from concurrent.futures import ThreadPoolExecutor
from functools import partial
from uuid import uuid4

from backend.app.core.postgres_migrations import PostgresMigrationRunner, discover_migrations
from backend.app.repositories.postgres_ai_ops_followup_repository import (
    PostgresAiOpsFollowupRepository,
    record_followup,
)
from backend.app.repositories.postgres_ai_ops_repository import PostgresAiOpsRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def due(database, expired=False):
    with database.transaction() as conn:
        conn.execute("UPDATE ai_ops_followups SET next_check_at=now()-interval '1 second'")
        if expired:
            conn.execute("UPDATE ai_ops_followups SET deadline_at=now()-interval '1 second'")


def record(database, run, action, target, baseline):
    action_id = str(uuid4())
    with database.transaction() as conn:
        record_followup(conn, run, action_id, action, target, baseline)
    return action_id


def translation(database, tag):
    with database.transaction() as conn:
        conn.execute("INSERT INTO documents (id,source,url,title) VALUES (%s,'x','https://x.com/test','private')", (tag,))
        return conn.execute("INSERT INTO x_translation_tasks (document_id,target_kind,source_tweet_id,source_text, "
                            "source_fingerprint,status,prompt_version) VALUES (%s,'outer',%s,'private',repeat('a',64), "
                            "'pending','v1') RETURNING id", (tag, tag)).fetchone()["id"]


def test_followup_migration_preserves_existing_monitoring_data_and_migration_history(tmp_path, monkeypatch):
    migrations = discover_migrations()
    followup = next(item for item in migrations if item.filename.endswith("_ai_ops_followups.sql"))
    for item in migrations:
        if item.version < followup.version:
            (tmp_path / item.filename).write_bytes(item.sql.encode("utf-8"))
    # Bootstrap the guarded scratch database at the preceding schema version.
    monkeypatch.setattr("backend.app.core.postgres_migrations.PostgresMigrationRunner",
                        partial(PostgresMigrationRunner, migrations_dir=tmp_path))
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        runs = PostgresAiOpsRepository(db)
        run = runs.create("manual")
        with db.transaction() as conn:
            history = conn.execute("SELECT * FROM app_schema_migrations ORDER BY version").fetchall()
            event = conn.execute("INSERT INTO email_send_events (kind,outcome) VALUES ('otp','accepted') "
                                 "RETURNING *").fetchone()
        (tmp_path / followup.filename).write_bytes(followup.sql.encode("utf-8"))
        runner = PostgresMigrationRunner(db, migrations_dir=tmp_path)
        assert [item.filename for item in runner.apply()] == [followup.filename]
        assert runner.apply() == []
        with db.transaction() as conn:
            assert conn.execute("SELECT * FROM app_schema_migrations WHERE version < %s ORDER BY version",
                                (followup.version,)).fetchall() == history
            assert conn.execute("SELECT * FROM email_send_events WHERE id=%s", (event["id"],)).fetchone() == event
        assert runs.get(run)["status"] == "running"
        record(db, run, "x_translation_retry", "queue", {})
        assert PostgresAiOpsFollowupRepository(db).recent()[0]["status"] == "pending"


def test_submitted_is_pending_then_verified_once_across_workers_after_cancellation():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        runs = PostgresAiOpsRepository(db)
        followups = PostgresAiOpsFollowupRepository(db)
        run = runs.create("manual")
        runs.event(run, "tool_result", "delivery", {"result": {"status": "ok", "active_sha": "a" * 40}})
        task = translation(db, "first")
        reservation = runs.reserve_action(run, "x_translation_retry", "queue", per_target=2, per_action=2,
                                          spacing_seconds=0, title="译文重试")
        runs.finish(run, "cancelled")
        runs.finish_action(run, reservation, "submitted", "译文重试", {"task_ids": [task]})
        assert followups.recent()[0]["status"] == "pending"
        assert followups.cases() == []
        due(db)
        followups.review()
        assert followups.recent()[0]["status"] == "pending"
        with db.transaction() as conn:
            conn.execute("UPDATE x_translation_tasks SET status='succeeded',translation_zh='已翻译' WHERE id=%s", (task,))
        due(db)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: PostgresAiOpsFollowupRepository(db).review(), range(3)))
        assert followups.recent()[0]["status"] == "verified"
        assert followups.recent()[0]["runtime_sha"] == "a" * 40
        assert "task_ids" not in followups.cases()[0]["baseline"]
        assert runs.get(run)["status"] == "cancelled"
        results = [e for e in runs.get(run)["events"] if e["kind"] == "followup_result"]
        assert len(results) == 1 and results[0]["data"]["recovered"] == 1
        with db.transaction() as conn:
            conn.execute("DELETE FROM ai_ops_runs WHERE id=%s", (run,))
        assert PostgresAiOpsFollowupRepository(db).cases()[0]["status"] == "verified"


def test_new_translation_success_does_not_mask_original_failure_or_missing_evidence():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        runs = PostgresAiOpsRepository(db)
        followups = PostgresAiOpsFollowupRepository(db)
        run = runs.create("manual")
        original, unrelated = translation(db, "original"), translation(db, "unrelated")
        with db.transaction() as conn:
            conn.execute("UPDATE x_translation_tasks SET status='failed' WHERE id=%s", (original,))
            conn.execute("UPDATE x_translation_tasks SET status='succeeded',translation_zh='success' WHERE id=%s", (unrelated,))
        record(db, run, "x_translation_retry", "queue", {"task_ids": [original]})
        record(db, run, "x_translation_retry", "queue", {"task_ids": [999999]})
        due(db, expired=True)
        followups.review()
        assert {r["status"] for r in followups.recent()} == {"not_recovered", "inconclusive"}
        assert [r["status"] for r in followups.cases()] == ["not_recovered"]


def test_empty_translation_is_not_recovery_and_cohort_is_bounded():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        task = translation(db, "empty")
        followups = PostgresAiOpsFollowupRepository(db)
        assert followups.translation_cohort(1) == [task]
        assert followups.translation_cohort(0) == []
        run = PostgresAiOpsRepository(db).create("manual")
        record(db, run, "x_translation_retry", "queue", {"task_ids": [task]})
        with db.transaction() as conn:
            conn.execute("UPDATE x_translation_tasks SET status='succeeded',translation_zh='  ' WHERE id=%s", (task,))
        due(db, expired=True)
        followups.review()
        assert followups.recent()[0]["status"] == "not_recovered"


def test_briefing_verification_is_scoped_to_exact_artifact_not_email_delivery():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        run = PostgresAiOpsRepository(db).create("manual")
        followups = PostgresAiOpsFollowupRepository(db)
        record(db, run, "briefing_regenerate", "2026-10-10:news", {"cache_key": "2026-10-10_news"})
        record(db, run, "briefing_regenerate", "2026-10-10:github", {"cache_key": "2026-10-10_github"})
        with db.transaction() as conn:
            conn.execute("INSERT INTO briefings (date,content) VALUES ('2026-10-10_news','briefing')")
        due(db, expired=True)
        followups.review()
        rows = {r["target"]: r for r in followups.recent()}
        assert rows["2026-10-10:news"]["status"] == "verified"
        assert "邮件投递未验证" in rows["2026-10-10:news"]["evidence"]["scope"]
        assert rows["2026-10-10:github"]["status"] == "not_recovered"


def test_feed_verification_ignores_historical_and_zero_output_success():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        run = PostgresAiOpsRepository(db).create("manual")
        followups = PostgresAiOpsFollowupRepository(db)
        record(db, run, "public_feed_retry", "single:news", {"task_id": 0})
        with db.transaction() as conn:
            conn.execute("INSERT INTO ingestion_tasks (task_name,status,item_count,started_at) "
                         "VALUES ('single:news','success',5,(now()-interval '1 day')::text)")
        due(db)
        followups.review()
        assert followups.recent()[0]["status"] == "pending"
        with db.transaction() as conn:
            conn.execute("INSERT INTO ingestion_tasks (task_name,status,item_count,started_at) "
                         "VALUES ('single:news','success',0,now()::text)")
        due(db, expired=True)
        followups.review()
        assert followups.recent()[0]["status"] == "not_recovered"
        record(db, run, "public_feed_retry", "single:news", {"task_id": 0})
        with db.transaction() as conn:
            conn.execute("INSERT INTO ingestion_tasks (task_name,status,item_count,started_at) "
                         "VALUES ('single:news','success',3,now()::text)")
        due(db)
        followups.review()
        assert followups.recent()[0]["status"] == "verified"


def test_orphan_verification_does_not_claim_ingestion_recovery_and_record_is_idempotent():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        run = PostgresAiOpsRepository(db).create("manual")
        followups = PostgresAiOpsFollowupRepository(db)
        with db.transaction() as conn:
            task = conn.execute("INSERT INTO ingestion_tasks (task_name,status,error_msg) "
                                "VALUES ('single:x','failed','orphaned: interrupted') RETURNING id").fetchone()["id"]
        action_id = record(db, run, "ingestion_orphan_close", "all", {"task_ids": [task]})
        with db.transaction() as conn:
            record_followup(conn, run, action_id, "ingestion_orphan_close", "all", {"task_ids": []})
        due(db)
        followups.review()
        assert len(followups.recent()) == 1
        assert followups.recent()[0]["status"] == "verified"
        assert "采集恢复未验证" in followups.recent()[0]["evidence"]["scope"]


def test_missed_observation_window_does_not_learn_a_later_success():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        run = PostgresAiOpsRepository(db).create("manual")
        followups = PostgresAiOpsFollowupRepository(db)
        task = translation(db, "late")
        record(db, run, "x_translation_retry", "queue", {"task_ids": [task]})
        with db.transaction() as conn:
            conn.execute("UPDATE x_translation_tasks SET status='succeeded',translation_zh='late result'")
            conn.execute("UPDATE ai_ops_followups SET deadline_at=now()-interval '3 hours'")
        due(db)
        followups.review()
        assert followups.recent()[0]["status"] == "inconclusive"
        assert followups.cases() == []
