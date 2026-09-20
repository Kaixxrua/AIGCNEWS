from concurrent.futures import ThreadPoolExecutor

from backend.app.repositories.postgres_ai_ops_repository import PostgresAiOpsRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_admission_persistence_cancel_lease_and_schedule():
    with postgres_test_sandbox() as sandbox:
        repo = PostgresAiOpsRepository(sandbox.database)
        assert repo.config() == {"enabled": False, "interval_minutes": 15}
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
