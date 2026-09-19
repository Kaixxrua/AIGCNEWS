import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "completion_guard", Path(__file__).parents[2] / ".codex/hooks/delivery-completion-guard.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize("status", ["active", "superseded_waiting", "replacement_failed"])
def test_lineage_guard_preserves_terminal_and_carrier_states(monkeypatch, tmp_path, status):
    head = "a" * 40

    def git(_, *args):
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        if args[0] == "symbolic-ref":
            return "session/task"
        if args == ("rev-parse", "HEAD"):
            return head
        return ""

    monkeypatch.setattr(guard, "_git", git)
    monkeypatch.setattr(guard, "_run", lambda *a, **kw: SimpleNamespace(stdout="" if "config" in a[0] else head, returncode=0))
    monkeypatch.setattr(guard, "_branch_has_commits", lambda *a: True)
    monkeypatch.setattr(guard, "_session_changes", lambda *a: ([head], []))
    monkeypatch.setattr(guard, "_production_root", lambda *a: tmp_path)
    monkeypatch.setattr(guard, "_read_production_state", lambda *a: {})
    delivery = {"status": status, "landing_sha": head, "replacement": {"source_sha": "b" * 40}}
    probe = SimpleNamespace(inspect_session=lambda *a: delivery)
    monkeypatch.setattr(guard, "importlib", SimpleNamespace(util=SimpleNamespace(
        spec_from_file_location=lambda *a: SimpleNamespace(loader=SimpleNamespace(exec_module=lambda *a: None)),
        module_from_spec=lambda *a: probe,
    )))
    result = guard.evaluate({"hook_event_name": "Stop", "cwd": str(tmp_path)})
    if status == "active":
        assert result == {}
    else:
        assert result["decision"] == "block"
        assert status in result["reason"]
        assert "do not edit, commit, push, retry deployment or deploy" in result["reason"]
        assert "Continue the existing unattended pipeline" not in result["reason"]
        if status == "replacement_failed":
            assert "Carrier deployment failed" in result["reason"]
            assert "await coordinator instructions" in result["reason"]


@pytest.mark.parametrize('release_status,allowed', [('delivered',True),('deploying',False),('failed',False)])
def test_local_mode_does_not_request_github(monkeypatch,tmp_path,release_status,allowed):
    import json
    head='a'*40
    state=tmp_path/'local.json'
    state.write_text(json.dumps({'schema':'aigcnews.local-delivery.v1','mode':'local',
        'tasks':[{'branch':'session/task','sha':head,'landing_sha':head}],
        'release':{'sha':head,'status':release_status}}))
    def git(_, *args):
        if args==('rev-parse','--show-toplevel'):return str(tmp_path)
        if args[0]=='symbolic-ref':return 'session/task'
        if args==('rev-parse','HEAD'):return head
        return ''
    def run(args,**kwargs):
        assert 'fetch' not in args
        return SimpleNamespace(stdout=str(state) if 'config' in args else '',returncode=0)
    monkeypatch.setattr(guard,'_git',git);monkeypatch.setattr(guard,'_run',run)
    monkeypatch.setattr(guard,'_branch_has_commits',lambda *a:True)
    monkeypatch.setattr(guard,'_read_production_state',lambda *a:{'active_release':head})
    monkeypatch.setattr(guard,'_production_root',lambda *a:tmp_path)
    assert (guard.evaluate({'hook_event_name':'Stop','cwd':str(tmp_path)})=={}) is allowed
