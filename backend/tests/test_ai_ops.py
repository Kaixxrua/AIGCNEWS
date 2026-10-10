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


def test_fixed_tools_collect_without_model_routing():
    svc, repo, model = service(["有限结论"])
    asyncio.run(svc.run("id"))
    svc.tools["tasks"].assert_called_once()
    assert model.ainvoke.call_count == 1
    repo.finish.assert_called_once_with("id", "completed", "有限结论")
    events = [c.args for c in repo.event.call_args_list]
    json.dumps(events)  # Evidence including timestamps is JSON-safe for PostgreSQL.


@pytest.mark.parametrize("tool", ["shell", "deploy"])
def test_unknown_tool_registry_is_rejected(tool):
    with pytest.raises(ValueError, match="invalid_tool_registry"):
        AiOpsService(MagicMock(), {tool: MagicMock()}, MagicMock())


def test_report_text_never_executes_model_instructions():
    svc, repo, model = service([{"tool": "deploy"}])
    asyncio.run(svc.run("id"))
    assert model.ainvoke.call_count == 1
    assert set(svc.tools) == {"health", "tasks"}
    for tool in svc.tools.values():
        tool.assert_called_once()


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
    assert repo.finish.call_args.args[:2] == ("id", "failed")
    assert "未生成 AI 分析结论" in repo.finish.call_args.args[2]


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


def test_failed_tool_does_not_prevent_other_evidence_or_report():
    svc, repo, model = service(["有限结论"])
    svc.tools["health"].side_effect = TimeoutError("secret")
    asyncio.run(svc.run("id"))
    svc.tools["tasks"].assert_called_once()
    evidence = json.loads(model.ainvoke.call_args.args[0][-1].content)
    assert evidence["health"]["result"] == {"status": "unavailable", "error_type": "TimeoutError"}
    assert "secret" not in str(repo.mock_calls)
    repo.finish.assert_called_once_with("id", "completed", "有限结论")


def test_recovery_uses_fresh_delivery_and_report_receives_real_outcome():
    svc, repo, model = service(["最终结论"])
    svc.tools["delivery"] = MagicMock(return_value={"status": "ok", "release_status": "delivered"})
    svc.recovery = MagicMock()
    svc.recovery.run.return_value = {"status": "scheduled", "task_id": 7}
    asyncio.run(svc.run("id"))
    assert svc.tools["delivery"].call_count == 2
    svc.recovery.run.assert_called_once_with("id", {"status": "ok", "release_status": "delivered"})
    report_input = model.ainvoke.call_args.args[0][-1].content
    assert json.loads(report_input)["recovery"] == {"status": "scheduled", "task_id": 7}


def test_cancel_before_policy_never_admits_action():
    svc, repo, _ = service(["unused"])
    svc.recovery = MagicMock()
    repo.event.side_effect = lambda run, kind, *args: kind != "policy"
    asyncio.run(svc.run("id"))
    svc.recovery.run.assert_not_called()


def test_composition_uses_injected_dependencies_and_limits_evidence(monkeypatch):
    diagnostics = MagicMock()
    diagnostics.errors.return_value = {"total": 1, "groups": []}
    monkeypatch.setattr("backend.app.services.ai_ops.PostgresAiOpsDiagnosticsRepository", lambda _: diagnostics)
    database, repositories, health, scheduler, provider = (MagicMock() for _ in range(5))
    health.run.return_value = {"status": "ok"}
    repositories.ingestion_tasks.list_tasks.return_value = {"items": [
        {"id": 7, "status": "failed", "error_msg": "private task detail"}]}
    repositories.error_events.list_events.return_value = {"items": [
        {"id": 8, "exception_type": "TimeoutError", "message": "private error"}]}
    repositories.x_translation_tasks.get_status_summary.return_value = {"pending": 22, "failed": 7}
    scheduler.running = True
    scheduler.get_jobs.return_value = []
    svc = create_ai_ops_service(database=database, repositories=repositories,
                                health_checks=health, scheduler=scheduler, model_provider=provider)
    assert svc.repository.database is database
    assert svc.tools["health"]() == {"status": "ok"}
    assert svc.tools["tasks"]()[0]["id"] == 7
    assert "error_msg" not in svc.tools["tasks"]()[0]
    assert svc.tools["errors"]() == {"total": 1, "groups": []}
    assert svc.tools["scheduler"]() == {"running": True, "jobs": [], "job_count": 0}
    assert svc.tools["x_translations"]()["pending"] == 22
    assert svc.model() is provider.get_chat_model.return_value.model_copy.return_value
    provider.get_chat_model.assert_called_once_with(reasoning_effort="high")


def acting_service(decisions, candidates):
    from backend.app.services.ai_ops_actions import Candidate
    svc, repo, model = service(decisions)
    built = [Candidate(*spec, {"n": 1}) for spec in candidates]
    svc.actions = MagicMock()
    svc.actions.candidates.return_value = built
    svc.actions.execute = AsyncMock(side_effect=lambda run, c: {"id": c.id, "status": "submitted"})
    order = []
    svc.recovery = MagicMock()
    svc.recovery.run.side_effect = lambda *_: order.append("recovery") or {"status": "skipped"}
    svc.actions.execute.side_effect = lambda run, c: order.append(c.id) or {"id": c.id, "status": "submitted"}
    svc.tools["delivery"] = MagicMock(return_value={"status": "ok"})
    return svc, repo, model, order


def test_model_selected_actions_run_before_fixed_recovery_and_reach_report():
    svc, repo, model, order = acting_service([
        {"actions": [{"id": "briefing_regenerate:2026-09-28:github", "reason": "missing"},
                     {"id": "briefing_regenerate:2026-09-28:news"},
                     {"id": "deploy:main"}]},
        "最终结论"], [("briefing_regenerate", "2026-09-28:github"),
                      ("briefing_regenerate", "2026-09-28:news")])
    asyncio.run(svc.run("id"))
    assert order == ["briefing_regenerate:2026-09-28:github", "recovery"]
    report = json.loads(model.ainvoke.call_args.args[0][-1].content)["actions"]
    assert [r["status"] for r in report["results"]] == ["submitted", "skipped"]
    assert len(report["candidates"]) == 2
    warnings = [c.args[3] for c in repo.event.call_args_list if c.args[1] == "warning"]
    assert warnings == [{"ids": ["deploy:main"]}]
    repo.finish.assert_called_once_with("id", "completed", "最终结论")


def test_deferred_candidates_are_audited_and_reported_but_never_run():
    github = "briefing_regenerate:2026-09-28:github"
    svc, repo, model, order = acting_service([
        {"actions": [], "skipped": [{"id": github, "reason": "上游仍在报错"}, {"id": "deploy:main"}]},
        "最终结论"], [("briefing_regenerate", "2026-09-28:github")])
    asyncio.run(svc.run("id"))
    assert order == ["recovery"]
    audited = [c.args[3] for c in repo.event.call_args_list if c.args[2] == "暂缓候选"]
    assert audited == [{"skipped": [{"id": github, "reason": "上游仍在报错"}]}]
    report = json.loads(model.ainvoke.call_args.args[0][-1].content)["actions"]
    assert report["deferred"] == audited[0]["skipped"] and report["results"] == []


@pytest.mark.parametrize("reply", ['{"tool":"tasks"}', "not json", '{"actions":"all"}'])
def test_unusable_action_reply_executes_nothing_but_run_completes(reply):
    svc, repo, _, order = acting_service([reply, "最终结论"],
                                         [("x_translation_retry", "queue")])
    asyncio.run(svc.run("id"))
    assert order == ["recovery"]
    repo.finish.assert_called_once_with("id", "completed", "最终结论")


def test_no_candidates_skips_the_action_model_call():
    svc, repo, model, order = acting_service(["最终结论"], [])
    asyncio.run(svc.run("id"))
    assert model.ainvoke.call_count == 1 and order == ["recovery"]


def test_cancel_during_action_phase_never_executes():
    svc, repo, _, order = acting_service([{"actions": [{"id": "x_translation_retry:queue"}]}],
                                         [("x_translation_retry", "queue")])
    repo.event.side_effect = lambda run, kind, title, *args: title != "核对动作前置条件"
    asyncio.run(svc.run("id"))
    assert order == []
    svc.actions.execute.assert_not_called()


def test_composition_wires_action_dependencies():
    database, repositories, health, scheduler, provider, operations = (MagicMock() for _ in range(6))
    svc = create_ai_ops_service(database=database, repositories=repositories, health_checks=health,
                                scheduler=scheduler, model_provider=provider,
                                operations=operations, redis_client="redis")
    assert svc.actions.repository is svc.repository
    assert svc.actions.operations is operations and svc.actions.redis_client == "redis"
    assert svc.actions.repositories is repositories and svc.actions.scheduler is scheduler


def test_model_timeout_keeps_all_evidence_with_an_explicit_non_ai_summary():
    svc, repo, model = service([])
    model.ainvoke.side_effect = TimeoutError("private relay body")
    asyncio.run(svc.run("id"))
    assert all(tool.call_count == 1 for tool in svc.tools.values())
    assert model.ainvoke.call_count == 1
    assert repo.finish.call_args.args[:2] == ("id", "failed")
    summary = repo.finish.call_args.args[2]
    assert "程序采集摘要" in summary and "health" in summary and "tasks" in summary
    assert "private relay" not in str(repo.mock_calls)


def test_knowledge_and_observed_cases_are_supplied_to_the_model():
    svc, repo, model = service(["报告"])
    svc.followups = MagicMock()
    svc.followups.cases.return_value = []
    svc.tools["x_translations"] = lambda: {"retryable": 1, "running": 1, "stale_running": 1}
    asyncio.run(svc.run("id"))
    evidence = json.loads(model.ainvoke.call_args.args[0][-1].content)
    books = evidence["knowledge"]["result"]["runbooks"]
    assert "x-translation" in [book["id"] for book in books]
    assert any(c.args[2] == "knowledge" for c in repo.event.call_args_list)


def test_followups_continue_when_automatic_investigations_are_off(monkeypatch):
    svc, repo, model = service([])
    svc.followups = MagicMock()
    repo.create.return_value = None
    monkeypatch.setattr("backend.app.services.ai_ops.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(svc.watch())
    svc.followups.review.assert_called_once()
    model.ainvoke.assert_not_called()
