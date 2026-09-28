from concurrent.futures import ThreadPoolExecutor

from backend.app.repositories.postgres_ai_ops_repository import PostgresAiOpsRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_admission_persistence_cancel_lease_and_schedule():
    with postgres_test_sandbox() as sandbox:
        repo = PostgresAiOpsRepository(sandbox.database)
        assert repo.config() == {"enabled": False, "interval_minutes": 15, "recovery_enabled": True}
        assert repo.create("scheduled", scheduled=True) is None
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: repo.create("manual"), range(4)))
        assert len([i for i in ids if i]) == 1
        run_id = next(i for i in ids if i)
        assert repo.event(run_id, "tool_result", "health", {"status": "ok"})
        restored = PostgresAiOpsRepository(sandbox.database)
        assert restored.get(run_id)["events"][0]["data"]["status"] == "ok"
        repo.finish(run_id, "cancelled")
        assert not repo.event(run_id, "model", "late event")
        repo.finish(run_id, "completed", "must not overwrite cancellation")
        assert repo.get(run_id)["status"] == "cancelled"
        repo.configure(True, 15)
        assert repo.create("scheduled", scheduled=True) is None
        with sandbox.database.transaction() as conn:
            conn.execute("UPDATE ai_ops_runs SET started_at=now()-interval '20 minutes'")
        second = repo.create("scheduled", scheduled=True)
        assert second
        with sandbox.database.transaction() as conn:
            conn.execute("UPDATE ai_ops_runs SET started_at=now()-interval '7 minutes' WHERE id=%s", (second,))
        third = repo.create("manual")
        assert third and repo.get(second)["status"] == "interrupted"
        assert len(repo.list()) == 3


def test_recovery_permissions_deduplication_budgets_and_audit():
    from datetime import datetime, timedelta, timezone

    from backend.app.services.ai_ops_recovery import eligible
    with postgres_test_sandbox() as sandbox:
        repo = PostgresAiOpsRepository(sandbox.database)
        run = repo.create("manual")
        def task(status="failed", name="single:news"):
            with sandbox.database.transaction() as conn:
                return conn.execute("INSERT INTO ingestion_tasks "
                    "(task_name,status,item_count,finished_at,error_msg) VALUES (%s,%s,0,%s,'ReadTimeout') RETURNING id",
                    (name, status, (datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat())).fetchone()["id"]
        first = task()
        def claim():
            return repo.reserve_recovery(run, "single:news", "news_techmeme", eligible)
        repo.configure(True, 15, False)
        assert claim() is None
        repo.configure(True, 15)  # Old clients cannot silently re-enable permission.
        assert not repo.config()["recovery_enabled"]
        repo.configure(True, 15, True)
        assert repo.reserve_recovery(run, "single:x", "x_watchlist", eligible) is None
        active = task("running", "single:news:2026-09-20")
        assert claim() is None
        with sandbox.database.transaction() as conn:
            conn.execute("UPDATE ingestion_tasks SET status='success' WHERE id=%s", (active,))
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: claim(), range(4)))
        assert len([c for c in claims if c]) == 1
        action = next(c for c in claims if c)
        assert action["task_id"] == first
        repo.finish(run, "cancelled")
        repo.finish_recovery(run, action, "scheduled")
        assert repo.get(run)["events"][-1]["data"]["status"] == "scheduled"
        assert claim() is None
        run = repo.create("manual")
        with sandbox.database.transaction() as conn:
            conn.execute("UPDATE ai_ops_recovery_actions SET created_at=now()-interval '2 hours'")
        assert claim() is None  # Same task cannot be replayed after cooldown.
        for _ in range(2):
            task()
            assert claim()
            with sandbox.database.transaction() as conn:
                conn.execute("UPDATE ai_ops_recovery_actions SET created_at=now()-interval '2 hours'")
        task()
        assert claim() is None  # Three in 24 hours, including uncertain/reserved actions.


def test_recovery_ignores_historical_failure_after_success():
    from backend.app.services.ai_ops_recovery import eligible
    with postgres_test_sandbox() as sandbox:
        repo = PostgresAiOpsRepository(sandbox.database)
        run = repo.create("manual")
        with sandbox.database.transaction() as conn:
            for status in ("failed", "success"):
                conn.execute("INSERT INTO ingestion_tasks (task_name,status,finished_at,error_msg) "
                    "VALUES ('single:news',%s,(now()-interval '10 minutes')::text,'ReadTimeout')", (status,))
        assert repo.reserve_recovery(run, "single:news", "news_techmeme", eligible) is None


def test_action_budgets_come_from_the_audit_trail():
    from datetime import timedelta
    with postgres_test_sandbox() as sandbox:
        repo = PostgresAiOpsRepository(sandbox.database)
        run = repo.create("manual")
        limits = {"per_target": 2, "per_action": 3, "spacing_seconds": 3600, "title": "简报补生成"}
        def reserve(target, run_id=run):
            return repo.reserve_action(run_id, "briefing_regenerate", target, **limits)
        def age_events():
            with sandbox.database.transaction() as conn:
                conn.execute("UPDATE ai_ops_runs SET events=(SELECT jsonb_agg(jsonb_set(e, '{at}', "
                             "to_jsonb((now()-interval '2 hours')::text))) FROM jsonb_array_elements(events) e)")
        repo.configure(True, 15, False)
        assert reserve("d:github") is None
        repo.configure(True, 15, True)
        first = reserve("d:github")
        assert first["action"] == "briefing_regenerate" and first["target"] == "d:github"
        assert reserve("d:github") is None  # spacing
        assert repo.action_usage("briefing_regenerate", 3600) == {"d:github": {"used": 1, "recent": 1}}
        age_events()
        assert reserve("d:github")
        age_events()
        assert reserve("d:github") is None  # per-target daily budget
        assert reserve("d:news")
        assert reserve("d:all") is None  # per-action daily budget
        assert repo.reserve_action(run, "x_translation_retry", "queue", **limits)
        repo.finish(run, "cancelled")
        assert repo.reserve_action(run, "ingestion_orphan_close", "all", **limits) is None
        repo.finish_action(run, first, "submitted", "简报补生成", {"status": "forged", "date": "d"})
        last = repo.get(run)["events"][-1]
        assert last["kind"] == "action_result" and last["data"]["status"] == "submitted"
        assert last["data"]["id"] == first["id"] and last["data"]["date"] == "d"
        try:
            repo.finish_action(run, first, "deployed", "x")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown status accepted")
        # Legacy recovery events without an action key never count against action budgets.
        second = repo.create("manual")
        repo.event(second, "action_start", "公共资讯补跑", {"id": "x", "task_id": 1, "job_id": "hackernews"})
        assert repo.action_usage("briefing_regenerate", 3600).keys() == {"d:github", "d:news"}
        assert repo.stale_running_tasks(timedelta(hours=6), 10) == []


def test_stale_running_tasks_threshold_and_malformed_timestamps():
    from datetime import datetime, timedelta, timezone
    with postgres_test_sandbox() as sandbox:
        repo = PostgresAiOpsRepository(sandbox.database)
        def task(status, started_at):
            with sandbox.database.transaction() as conn:
                return conn.execute("INSERT INTO ingestion_tasks (task_name,status,started_at) "
                                    "VALUES ('single:x',%s,%s) RETURNING id", (status, started_at)).fetchone()["id"]
        now = datetime.now(timezone.utc)
        old = task("running", (now - timedelta(hours=7)).isoformat())
        task("running", (now - timedelta(hours=5)).isoformat())
        task("failed", (now - timedelta(days=9)).isoformat())
        task("running", "not-a-timestamp")
        task("running", None)
        older = task("running", "2026-03-14T10:03:29.673831+00:00")
        rows = repo.stale_running_tasks(timedelta(hours=6), 10)
        assert [row["id"] for row in rows] == sorted([old, older])
        assert rows[0]["task_name"] == "single:x"
        assert len(repo.stale_running_tasks(timedelta(hours=6), 1)) == 1
