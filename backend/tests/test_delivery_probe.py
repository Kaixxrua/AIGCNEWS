import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "delivery_probe", Path(__file__).parents[2] / "scripts/release/delivery_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_active_task_is_complete_even_during_later_deployment(monkeypatch):
    monkeypatch.setattr(probe, "contains", lambda *args: True)
    state = {"schema": "aigcnews.production-state.v1", "active_release": "a" * 40, "in_progress": "b" * 40}
    assert probe.evaluate(Path("."), "a" * 40, state)["status"] == "active"


def test_unrelated_replacement_is_rejected(monkeypatch):
    monkeypatch.setattr(probe, "contains", lambda *args: False)
    with pytest.raises(ValueError, match="does not contain"):
        probe.evaluate(
            Path("."),
            "a" * 40,
            {"schema": "aigcnews.production-state.v1"},
            {"source_sha": "b" * 40, "status": "queued"},
        )


def test_superseded_is_not_reported_as_deployed(monkeypatch):
    monkeypatch.setattr(probe, "contains", lambda *args: True)
    replacement = {
        "source_sha": "b" * 40,
        "status": "queued",
        "pr": 6,
        "session": "session/task-six",
        "title": "task six",
    }
    result = probe.evaluate(Path("."), "a" * 40, {"schema": "aigcnews.production-state.v1"}, replacement)
    assert result["status"] == "superseded_waiting"
    assert result["replacement"] == replacement


def test_real_git_ancestry_distinguishes_unrelated_commits(tmp_path):
    import subprocess

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()

    git("init")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "task")
    task = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "replacement")
    replacement = git("rev-parse", "HEAD")
    assert probe.contains(tmp_path, task, replacement)
    assert not probe.contains(tmp_path, task, base)
    with pytest.raises(ValueError, match="cannot be verified"):
        probe.contains(tmp_path, task, "f" * 40)


def test_pending_replacement_uses_explicit_source_not_workflow_head(monkeypatch):
    monkeypatch.setattr(probe, "contains", lambda root, a, b: b == "b" * 40)
    runs = [
        {
            "id": 1,
            "event": "workflow_run",
            "status": "pending",
            "display_title": "production-source:" + "b" * 40,
            "head_sha": "c" * 40,
        },
        {"id": 2, "event": "workflow_run", "status": "completed", "display_title": "production-source:" + "b" * 40},
        {"id": 3, "event": "workflow_run", "status": "queued", "display_title": "old format", "head_sha": "b" * 40},
    ]
    replacement = probe.queued_replacement(Path("."), "a" * 40, runs)
    assert replacement["run_id"] == 1
    assert replacement["source_sha"] == "b" * 40
    assert replacement["status"] == "queued"


def test_failed_replacement_remains_visible_until_newer_attempt(monkeypatch):
    monkeypatch.setattr(probe, "contains", lambda *args: True)
    failed = {
        "id": 2,
        "event": "workflow_run",
        "status": "completed",
        "conclusion": "failure",
        "display_title": "production-source:" + "b" * 40,
    }
    replacement = probe.queued_replacement(Path("."), "a" * 40, [failed])
    assert replacement["status"] == "failed"
    result = probe.evaluate(
        Path("."), "a" * 40, {"schema": "aigcnews.production-state.v1"}, replacement
    )
    assert result["status"] == "replacement_failed"
    retry = {**failed, "id": 3, "status": "queued", "conclusion": None}
    assert probe.queued_replacement(Path("."), "a" * 40, [failed, retry])["run_id"] == 3
