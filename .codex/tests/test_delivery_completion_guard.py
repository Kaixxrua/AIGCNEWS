from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "delivery-completion-guard.py"
SPEC = importlib.util.spec_from_file_location("delivery_completion_guard", HOOK)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def delivery_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    bare = tmp_path / "remote.git"
    root = tmp_path / "repo"
    production = tmp_path / "production"
    git(tmp_path, "init", "--bare", str(bare))
    git(tmp_path, "init", str(root))
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "base")
    git(root, "branch", "-M", "main")
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-u", "origin", "main")
    git(root, "switch", "-c", "session/test-123")
    (root / "TASK.md").write_text("task\n", encoding="utf-8")
    git(root, "add", "TASK.md")
    git(root, "commit", "-m", "test(workflow): task")
    task = git(root, "rev-parse", "HEAD")
    git(root, "config", "aigcnews.productionRoot", str(production))
    return root, production, task


def payload(root: Path, **values: object) -> dict[str, object]:
    return {
        "hook_event_name": "Stop",
        "cwd": str(root),
        "last_assistant_message": "done",
        "stop_hook_active": False,
        **values,
    }


def assert_blocked(result: dict[str, object], text: str) -> None:
    assert result["decision"] == "block"
    assert text in str(result["reason"])


def test_project_registers_stop_hook():
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    command = config["hooks"]["Stop"][0]["hooks"][0]
    assert command["type"] == "command"
    assert "delivery-completion-guard.py" in command["command"]


def test_allows_session_without_development_commits(tmp_path: Path):
    root = tmp_path / "repo"
    git(tmp_path, "init", str(root))
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "base")
    git(root, "branch", "-M", "main")
    git(tmp_path, "init", "--bare", str(tmp_path / "remote.git"))
    git(root, "remote", "add", "origin", str(tmp_path / "remote.git"))
    git(root, "push", "-u", "origin", "main")
    git(root, "switch", "-c", "session/analysis-123")
    assert GUARD.evaluate(payload(root)) == {}


def test_blocks_unpushed_and_unmerged_session(delivery_repo):
    root, _, _ = delivery_repo
    assert_blocked(GUARD.evaluate(payload(root)), "not been pushed")
    git(root, "push", "-u", "origin", "HEAD")
    assert_blocked(GUARD.evaluate(payload(root)), "not yet patch-equivalent")


def test_blocks_dirty_session(delivery_repo):
    root, _, _ = delivery_repo
    (root / "DIRTY.md").write_text("dirty\n", encoding="utf-8")
    assert_blocked(GUARD.evaluate(payload(root)), "still has")


def test_blocks_merged_change_until_production_contains_it(delivery_repo):
    root, production, task = delivery_repo
    git(root, "push", "-u", "origin", "HEAD")
    git(root, "switch", "main")
    git(root, "cherry-pick", task)
    merged = git(root, "rev-parse", "HEAD")
    git(root, "push", "origin", "main")
    git(root, "switch", "session/test-123")
    git(root, "fetch", "origin", "main")

    assert_blocked(GUARD.evaluate(payload(root)), "production state is missing")
    state_dir = production / ".aigcnews-deploy"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(
        json.dumps({"schema": GUARD.PRODUCTION_SCHEMA, "active_release": merged, "in_progress": None}),
        encoding="utf-8",
    )
    assert GUARD.evaluate(payload(root)) == {}


def test_allows_explicit_evidenced_external_blocker(delivery_repo):
    root, _, _ = delivery_repo
    result = GUARD.evaluate(
        payload(
            root,
            stop_hook_active=True,
            last_assistant_message="DELIVERY_BLOCKED: GitHub rejected the workflow run; run URL recorded.",
        )
    )
    assert result == {}


def test_subprocess_emits_single_json_object(delivery_repo):
    root, _, _ = delivery_repo
    completed = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload(root)),
        text=True,
        capture_output=True,
        env=os.environ.copy(),
        check=False,
    )
    assert completed.returncode == 0
    assert len(completed.stdout.strip().splitlines()) == 1
    assert json.loads(completed.stdout)["decision"] == "block"
