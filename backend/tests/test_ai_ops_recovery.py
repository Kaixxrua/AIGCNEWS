from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.services.ai_ops_recovery import AiOpsRecovery, eligible


def failed_task(**changes):
    return {"status": "failed", "item_count": 0, "error_msg": "ReadTimeout",
            "finished_at": (datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(), **changes}


@pytest.mark.parametrize("changes", [
    {"status": "running"}, {"status": "success"}, {"item_count": 1},
    {"error_msg": "401 ConnectError"}, {"error_msg": "429 ReadTimeout"},
    {"error_msg": "TypeError: connection timed out"}, {"error_msg": "unknown failure"},
    {"finished_at": "invalid"}, {"finished_at": "2026-01-01T00:00:00"},
    {"finished_at": datetime.now(timezone.utc).isoformat()},
    {"finished_at": (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()},
])
def test_only_recent_unambiguous_network_failures_qualify(changes):
    assert not eligible(failed_task(**changes), datetime.now(timezone.utc))


def test_transient_failure_qualifies():
    assert eligible(failed_task(), datetime.now(timezone.utc))


def recovery():
    repo, scheduler = MagicMock(), MagicMock()
    scheduler.state = 1
    job = scheduler.get_job.return_value
    job.max_instances = 1
    job.next_run_time = datetime.now(timezone.utc)+timedelta(minutes=30)
    repo.reserve_recovery.return_value = {"id": "action", "job_id": "news_techmeme", "task_id": 1}
    return AiOpsRecovery(repo, scheduler), repo, scheduler, job


@pytest.mark.parametrize("delivery", [{}, {"status": "stale", "release_status": "delivered"},
                                     {"status": "ok", "release_status": "deploying"}])
def test_unverified_delivery_never_changes_scheduler(delivery):
    svc, repo, scheduler, job = recovery()
    assert svc.run("run", delivery)["status"] == "skipped"
    repo.reserve_recovery.assert_not_called()
    job.modify.assert_not_called()


@pytest.mark.parametrize("mode", ["paused_scheduler", "paused_job", "near_due", "parallel_job", "denied"])
def test_scheduler_and_permission_guards(mode):
    svc, repo, scheduler, job = recovery()
    if mode == "paused_scheduler":
        scheduler.state = 2
    elif mode == "paused_job":
        job.next_run_time = None
    elif mode == "near_due":
        job.next_run_time = datetime.now(timezone.utc)
    elif mode == "parallel_job":
        job.max_instances = 2
    else:
        repo.reserve_recovery.return_value = None
    assert svc.run("run", {"status": "ok", "release_status": "delivered"})["status"] == "skipped"
    job.modify.assert_not_called()


def test_single_admitted_action_is_scheduled_not_reported_as_recovered():
    svc, repo, scheduler, job = recovery()
    result = svc.run("run", {"status": "ok", "release_status": "delivered"})
    assert result["status"] == "scheduled"
    repo.reserve_recovery.assert_called_once()
    job.modify.assert_called_once()
    scheduler.wakeup.assert_called_once()
    repo.finish_recovery.assert_called_once_with("run", repo.reserve_recovery.return_value, "scheduled")


def test_uncertain_submission_is_not_replayed_or_exposed():
    svc, repo, scheduler, job = recovery()
    job.modify.side_effect = RuntimeError("private token")
    result = svc.run("run", {"status": "ok", "release_status": "delivered"})
    assert result["status"] == "uncertain" and "private" not in str(result)
    repo.reserve_recovery.assert_called_once()
    repo.finish_recovery.assert_called_once_with("run", repo.reserve_recovery.return_value, "uncertain")


def test_real_scheduler_runs_registered_job_once_and_retains_normal_interval():
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    async def scenario():
        repo = MagicMock()
        repo.reserve_recovery.return_value = {"id": "action", "task_id": 1, "job_id": "news_techmeme"}
        scheduler = AsyncIOScheduler()
        calls = []
        completed = asyncio.Event()
        async def collect():
            calls.append("collected")
            completed.set()
        scheduler.add_job(collect, "interval", hours=1, id="news_techmeme", max_instances=1)
        scheduler.start()
        try:
            result = await asyncio.to_thread(AiOpsRecovery(repo, scheduler).run, "run",
                                             {"status": "ok", "release_status": "delivered"})
            assert result["status"] == "scheduled"
            await asyncio.wait_for(completed.wait(), 3)
            assert calls == ["collected"]
            job = scheduler.get_job("news_techmeme")
            assert job.max_instances == 1
            assert job.next_run_time > datetime.now(timezone.utc)+timedelta(minutes=59)
        finally:
            scheduler.shutdown()
            await asyncio.sleep(0)
    asyncio.run(scenario())
