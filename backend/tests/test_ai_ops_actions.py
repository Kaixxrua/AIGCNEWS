import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.app.services import ai_ops_actions
from backend.app.services.ai_ops_actions import (
    ORPHAN_MESSAGE,
    AiOpsActions,
    Candidate,
    select_actions,
)

NOON_CST = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)


def actions(now=NOON_CST, operations=True, stale=(), briefed=("all", "arxiv", "news", "x", "dailyhot",
                                                             "producthunt", "hackernews"),
            usage=None, summary=None, retry_jobs=()):
    repo = MagicMock()
    repo.config.return_value = {"recovery_enabled": True}
    repo.stale_running_tasks.return_value = list(stale)
    repo.action_usage.side_effect = lambda action, spacing: (usage or {}).get(action, {})
    repo.reserve_action.side_effect = lambda run, action, target, **_: {
        "id": "r1", "action": action, "target": target}
    repositories = MagicMock()
    repositories.x_translation_tasks.get_status_summary.return_value = summary or {
        "retryable": 0, "latest_success_at": now}
    repositories.x_translation_tasks.batch_running.return_value = 0
    repositories.briefings.get_briefing_by_date.side_effect = lambda key: (
        {"id": 1} if any(key == ai_ops_actions.get_briefing_cache_key("2026-09-28", s) for s in briefed)
        else None)
    scheduler = MagicMock()
    pending = {"daily_briefing"} | {f"daily_briefing_retry_{s}" for s in retry_jobs}
    scheduler.get_job.side_effect = lambda job_id: SimpleNamespace(id=job_id) if job_id in pending else None
    ops = MagicMock() if operations else None
    if ops:
        ops.submit.return_value = True
    return AiOpsActions(repo, repositories, scheduler, ops, "redis", now=lambda: now), repo, repositories


def ids(svc):
    return [c.id for c in svc.candidates()]


def test_only_missing_briefings_after_scheduler_retries_are_offered():
    svc, _, _ = actions()
    assert ids(svc) == ["briefing_regenerate:2026-09-28:github"]
    early, _, _ = actions(now=NOON_CST.replace(hour=2))  # 10:00 CST, scheduler retries may still run
    assert ids(early) == []
    pending_retry, _, _ = actions(retry_jobs=("github",))
    assert ids(pending_retry) == []
    offline, _, _ = actions(operations=False)
    assert ids(offline) == []
    disabled, _, _ = actions()
    disabled.scheduler.get_job.side_effect = lambda job_id: None
    assert ids(disabled) == []


def test_briefing_regenerate_submits_the_existing_dispatch_for_one_source():
    svc, repo, repositories = actions()
    candidate = svc.candidates()[0]
    result = asyncio.run(svc.execute("run", candidate))
    assert result["status"] == "submitted"
    svc.operations.submit.assert_called_once_with(
        ai_ops_actions.run_daily_briefing_dispatch, repositories, redis_client="redis",
        sources=["github"], target_date="2026-09-28")
    assert repo.reserve_action.call_args.kwargs == {
        "per_target": 2, "per_action": 10, "spacing_seconds": 3600, "title": "简报补生成"}
    repo.finish_action.assert_called_once()
    assert repo.finish_action.call_args.args[2] == "submitted"


def test_budget_and_permission_filter_candidates():
    exhausted, _, _ = actions(usage={"briefing_regenerate": {"2026-09-28:github": {"used": 2, "recent": 0}}})
    assert ids(exhausted) == []
    recent, _, _ = actions(usage={"briefing_regenerate": {"2026-09-28:github": {"used": 1, "recent": 1}}})
    assert ids(recent) == []
    daily_cap, _, _ = actions(usage={"briefing_regenerate": {f"d:{i}": {"used": 1, "recent": 0}
                                                             for i in range(10)}})
    assert ids(daily_cap) == []
    off, repo, _ = actions()
    repo.config.return_value = {"recovery_enabled": False}
    assert ids(off) == []
    repo.stale_running_tasks.assert_not_called()


def test_orphan_close_uses_existing_task_lifecycle_and_rechecks_status():
    stale = [{"id": 1, "task_name": "single:news:2026-03-16", "started_at": "2026-03-16T06:03:00+00:00"},
             {"id": 2, "task_name": "single:x", "started_at": "2026-09-01T00:00:00+00:00"}]
    svc, repo, repositories = actions(stale=stale)
    repositories.ingestion_tasks.get_task.side_effect = lambda task_id: (
        {"status": "running", "item_count": 3} if task_id == 1 else {"status": "success"})
    candidate = next(c for c in svc.candidates() if c.action == "ingestion_orphan_close")
    assert candidate.facts["by_task"] == {"single:news": 1, "single:x": 1}
    result = asyncio.run(svc.execute("run", candidate))
    assert result["status"] == "completed" and result["closed"] == 1
    repositories.ingestion_tasks.finish_task.assert_called_once_with(
        1, status="failed", error_msg=ORPHAN_MESSAGE, item_count=3)
    assert repo.stale_running_tasks.call_args.args == (timedelta(hours=6), 200)


def test_x_translation_retry_only_when_backlog_is_stalled():
    fresh, _, _ = actions(summary={"retryable": 5, "latest_success_at": NOON_CST - timedelta(minutes=10)})
    assert ids(fresh) == ["briefing_regenerate:2026-09-28:github"]
    stalled, _, repositories = actions(summary={"retryable": 5, "latest_failure_error": "boom",
                                                "latest_success_at": NOON_CST - timedelta(hours=2)})
    candidate = next(c for c in stalled.candidates() if c.action == "x_translation_retry")
    repositories.x_translation_tasks.count_retryable.return_value = 5
    result = asyncio.run(stalled.execute("run", candidate))
    assert result["status"] == "submitted"
    repositories.x_translation_tasks.recover_stale_running.assert_called_once_with()
    operation, limit = stalled.operations.submit.call_args.args
    assert operation.__self__.repository is repositories.x_translation_tasks and limit == 200
    repositories.x_translation_tasks.batch_running.return_value = 1
    assert "x_translation_retry:queue" not in ids(stalled)


def test_execute_rechecks_state_budget_and_records_failures():
    svc, repo, repositories = actions()
    candidate = svc.candidates()[0]
    repositories.briefings.get_briefing_by_date.side_effect = lambda key: {"id": 9}
    assert asyncio.run(svc.execute("run", candidate))["status"] == "skipped"
    repo.reserve_action.assert_not_called()
    svc, repo, _ = actions()
    repo.reserve_action.side_effect = None
    repo.reserve_action.return_value = None
    assert asyncio.run(svc.execute("run", svc.candidates()[0]))["status"] == "skipped"
    repo.finish_action.assert_not_called()
    svc, repo, _ = actions()
    svc.operations.submit.side_effect = RuntimeError("secret")
    result = asyncio.run(svc.execute("run", svc.candidates()[0]))
    assert result["status"] == "uncertain" and "secret" not in str(result)
    assert repo.finish_action.call_args.args[2] == "uncertain"


def test_model_can_only_pick_code_built_candidates():
    built = [Candidate("briefing_regenerate", "2026-09-28:github", {}),
             Candidate("x_translation_retry", "queue", {})]
    picked, ignored = select_actions({"actions": [
        {"id": "x_translation_retry:queue", "reason": "stalled"},
        {"id": "x_translation_retry:queue"},
        {"id": "shell:rm -rf /"}, "briefing_regenerate:2026-09-28:github"]}, built)
    assert [(c.id, r) for c, r in picked] == [("x_translation_retry:queue", "stalled")]
    assert len(ignored) == 3
    with pytest.raises(ValueError):
        select_actions({"tool": "tasks"}, built)
