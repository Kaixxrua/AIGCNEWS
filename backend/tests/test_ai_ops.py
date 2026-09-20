import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services.ai_ops import (
    AiOpsService,
    create_ai_ops_service,
    delivery_snapshot,
    parse_decision,
)
from scripts.ai_ops_delivery_bridge import publish


def service(decisions):
    repo = MagicMock()
    repo.event.return_value = True
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        SimpleNamespace(content=d if isinstance(d, str) else json.dumps(d)) for d in decisions]))
    tools = {"health": MagicMock(return_value={"status": "ok"}),
             "tasks": MagicMock(return_value=[{"started_at": datetime.now(timezone.utc)}])}
    return AiOpsService(repo, tools, lambda: model), repo, model


def test_real_tool_decisions_and_evidence():
    svc, repo, model = service([{"tool": "tasks", "reason": "check tasks"}, "有限结论"])
    asyncio.run(svc.run("id"))
    svc.tools["tasks"].assert_called_once()
    assert model.ainvoke.call_count == 2
    repo.finish.assert_called_once_with("id", "completed", "有限结论")
    events = [c.args for c in repo.event.call_args_list]
    json.dumps(events)  # Evidence including timestamps is JSON-safe for PostgreSQL.


@pytest.mark.parametrize("tool", ["shell", "health", "deploy"])
def test_unknown_and_repeated_tools_never_execute(tool):
    svc, repo, model = service([{"tool": tool}])
    asyncio.run(svc.run("id"))
    repo.finish.assert_called_once_with("id", "failed")
    assert model.ainvoke.call_count == 1


def test_cancelled_run_stops_before_model_call():
    svc, repo, model = service([])
    repo.event.return_value = False
    asyncio.run(svc.run("id"))
    model.ainvoke.assert_not_called()
    svc.tools["health"].assert_not_called()


def test_provider_failure_keeps_evidence_and_hides_credentials():
    svc, repo, model = service([])
    model.ainvoke.side_effect = RuntimeError("secret-key")
    asyncio.run(svc.run("id"))
    assert "tool_result" in str(repo.event.call_args_list)
    assert "secret-key" not in str(repo.mock_calls)
    repo.finish.assert_called_once_with("id", "failed")


def test_delivery_bridge_allowlist_and_freshness(tmp_path):
    source, target = tmp_path / "source.json", tmp_path / "target.json"
    source.write_text(json.dumps({"schema": "aigcnews.local-delivery.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(), "main_sha": "a" * 40,
        "active_release": {"sha": "b" * 40, "token": "secret"},
        "tasks": [{"sha": "a" * 40, "status": "queued", "owner": "private", "error": "secret"}]}))
    publish(source, target)
    assert "secret" not in target.read_text()
    assert "private" not in target.read_text()
    assert delivery_snapshot(target)["status"] == "ok"
    data = json.loads(target.read_text())
    data["generated_at"] = "2000-01-01T00:00:00+00:00"
    target.write_text(json.dumps(data))
    assert delivery_snapshot(target)["status"] == "stale"
    assert delivery_snapshot(tmp_path / "missing")["status"] == "unavailable"


def test_relay_duplicate_objects_are_deduplicated_but_conflicts_rejected():
    value = '{"tool":"tasks","reason":"check"}'
    assert parse_decision(value + value) == {"tool": "tasks", "reason": "check"}
    assert parse_decision('```json\n' + value + '\n```')["tool"] == "tasks"
    with pytest.raises(ValueError):
        parse_decision(value + '{"tool":"shell"}')
    with pytest.raises(ValueError):
        parse_decision('[]')


def test_conflicting_gateway_reply_uses_explicit_read_only_checklist():
    svc, repo, _ = service(['{"tool":"tasks"}{"report":"premature"}', "最终结论"])
    asyncio.run(svc.run("id"))
    svc.tools["tasks"].assert_called_once()
    assert any(call.args[1] == "warning" for call in repo.event.call_args_list)
    repo.finish.assert_called_once_with("id", "completed", "最终结论")


def test_recovery_uses_fresh_delivery_and_report_receives_real_outcome():
    svc, repo, model = service([{"tool": "tasks"}, "最终结论"])
    svc.tools["delivery"] = MagicMock(return_value={"status": "ok", "release_status": "delivered"})
    svc.recovery = MagicMock()
    svc.recovery.run.return_value = {"status": "scheduled", "task_id": 7}
    asyncio.run(svc.run("id"))
    assert svc.tools["delivery"].call_count == 2
    svc.recovery.run.assert_called_once_with("id", {"status": "ok", "release_status": "delivered"})
    report_input = model.ainvoke.call_args.args[0][-1].content
    assert json.loads(report_input)["recovery"] == {"status": "scheduled", "task_id": 7}


def test_cancel_before_policy_never_admits_action():
    svc, repo, _ = service([{"tool": "tasks"}, "unused"])
    svc.recovery = MagicMock()
    repo.event.side_effect = lambda run, kind, *args: kind != "policy"
    asyncio.run(svc.run("id"))
    svc.recovery.run.assert_not_called()


def test_composition_uses_injected_dependencies_and_limits_evidence():
    database, repositories, health, scheduler, provider = (MagicMock() for _ in range(5))
    health.run.return_value = {"status": "ok"}
    repositories.ingestion_tasks.list_tasks.return_value = {"items": [
        {"id": 7, "status": "failed", "error_msg": "private task detail"}]}
    repositories.error_events.list_events.return_value = {"items": [
        {"id": 8, "exception_type": "TimeoutError", "message": "private error"}]}
    scheduler.running = True
    scheduler.get_jobs.return_value = []
    svc = create_ai_ops_service(database=database, repositories=repositories,
                                health_checks=health, scheduler=scheduler, model_provider=provider)
    assert svc.repository.database is database
    assert svc.tools["health"]() == {"status": "ok"}
    assert svc.tools["tasks"]()[0]["id"] == 7
    assert "error_msg" not in svc.tools["tasks"]()[0]
    assert svc.tools["errors"]()[0]["exception_type"] == "TimeoutError"
    assert "message" not in svc.tools["errors"]()[0]
    assert svc.tools["scheduler"]() == {"running": True, "jobs": [], "job_count": 0}
    assert svc.model() is provider.get_chat_model.return_value.model_copy.return_value
    provider.get_chat_model.assert_called_once_with(reasoning_effort="low")
