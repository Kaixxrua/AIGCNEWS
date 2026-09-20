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
