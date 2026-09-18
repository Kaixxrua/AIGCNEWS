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
    monkeypatch.setattr(guard, "_run", lambda *a, **kw: SimpleNamespace(stdout=head, returncode=0))
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
