from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "worktree_gc.py"


def load_module():
    spec = importlib.util.spec_from_file_location("worktree_gc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gc = load_module()


def command(cwd: Path, *args: str) -> str:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("GIT_"):
            environment.pop(key)
    result = subprocess.run(list(args), cwd=cwd, env=environment, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    command(tmp_path, "git", "init", "--bare", "--initial-branch=main", str(bare))
    command(tmp_path, "git", "init", "--initial-branch=main", str(repo))
    command(repo, "git", "config", "user.name", "Worktree GC Test")
    command(repo, "git", "config", "user.email", "worktree-gc@example.invalid")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    command(repo, "git", "add", "tracked.txt")
    command(repo, "git", "commit", "-m", "test(base): initialize")
    command(repo, "git", "remote", "add", "origin", str(bare))
    command(repo, "git", "push", "-u", "origin", "main")
    return repo, bare


def session(repo: Path, managed: Path, name: str = "finished-100-200-3000") -> Path:
    managed.mkdir(parents=True, exist_ok=True)
    path = managed / name
    command(repo, "git", "worktree", "add", "-b", f"session/{name}", str(path), "main")
    return path


def commit_session(path: Path) -> str:
    (path / "feature.txt").write_text("complete\n", encoding="utf-8")
    command(path, "git", "add", "feature.txt")
    command(path, "git", "commit", "-m", "test(feature): complete")
    return command(path, "git", "rev-parse", "HEAD")


def merge_session(repo: Path, path: Path) -> None:
    branch = command(path, "git", "branch", "--show-current")
    command(repo, "git", "merge", "--ff-only", branch)
    command(repo, "git", "push", "origin", "main")


def age(path: Path) -> None:
    old = 1_600_000_000
    os.utime(path, (old, old))
    os.utime(path / ".git", (old, old))
    git_dir = Path(command(path, "git", "rev-parse", "--absolute-git-dir"))
    os.utime(git_dir / "HEAD", (old, old))


def test_collects_only_clean_completed_public_session(tmp_path: Path):
    repo, _ = repository(tmp_path)
    managed = repo / ".claude/worktrees"
    complete = session(repo, managed)
    commit_session(complete)
    merge_session(repo, complete)
    age(complete)

    decisions = gc.collect(repo, managed, private_authorizations=None, grace_hours=1, apply=True)

    assert any(item.path == str(complete) and item.action == "removed" for item in decisions)
    assert not complete.exists()


def test_skips_dirty_unmerged_and_recent_public_sessions(tmp_path: Path):
    repo, _ = repository(tmp_path)
    managed = repo / ".claude/worktrees"
    unmerged = session(repo, managed, "unmerged-100-200-3000")
    commit_session(unmerged)
    dirty = session(repo, managed, "dirty-100-200-3000")
    (dirty / "local.txt").write_text("keep\n", encoding="utf-8")
    recent = session(repo, managed, "recent-100-200-3000")

    decisions = gc.collect(repo, managed, private_authorizations=None, grace_hours=24, apply=True)
    reasons = {Path(item.path).name: item.reason for item in decisions}

    assert "not proven present" in reasons[unmerged.name]
    assert "changes remain" in reasons[dirty.name]
    assert "grace period" in reasons[recent.name]
    assert unmerged.exists() and dirty.exists() and recent.exists()


def test_skips_completed_worktree_used_by_process(tmp_path: Path):
    repo, _ = repository(tmp_path)
    managed = repo / ".claude/worktrees"
    complete = session(repo, managed)
    commit_session(complete)
    merge_session(repo, complete)
    age(complete)
    process = subprocess.Popen(["sleep", "30"], cwd=complete)
    try:
        decisions = gc.collect(repo, managed, private_authorizations=None, grace_hours=1, apply=True)
    finally:
        process.terminate()
        process.wait(timeout=5)

    decision = next(item for item in decisions if item.path == str(complete))
    assert decision.action == "skip"
    assert "used by process" in decision.reason
    assert complete.exists()


def test_private_cleanup_requires_clean_preserved_snapshot_and_authorization(tmp_path: Path):
    repo, _ = repository(tmp_path)
    managed = tmp_path / ".private-worktrees"
    private = managed / "godot-private"
    command(repo, "git", "worktree", "add", "-b", "codex/godot-private", str(private), "main")
    descriptor = private / "aigcnews-private-release.json"
    descriptor.write_text('{"release_id":"private"}\n', encoding="utf-8")
    command(private, "git", "add", descriptor.name)
    command(private, "git", "commit", "-m", "build(contact): pin release")
    command(private, "git", "push", "-u", "origin", "HEAD")
    snapshot = tmp_path / ".private-releases/release-private"
    command(
        tmp_path,
        "git",
        "clone",
        "--branch",
        "codex/godot-private",
        str(tmp_path / "origin.git"),
        str(snapshot),
    )
    ignored = private / "ignored-artifact.pck"
    (private / ".gitignore").write_text("ignored-artifact.pck\n", encoding="utf-8")
    command(private, "git", "add", ".gitignore")
    command(private, "git", "commit", "-m", "build(contact): ignore artifact")
    command(private, "git", "push", "origin", "HEAD")
    command(snapshot, "git", "pull", "--ff-only")
    ignored.write_bytes(b"private artifact")
    authorizations = tmp_path / "authorizations"

    target = gc.authorize_private(repo, private, snapshot, authorizations)
    document = json.loads(target.read_text(encoding="utf-8"))
    document["authorized_at"] = 1_600_000_000
    target.write_text(json.dumps(document), encoding="utf-8")
    decisions = gc.collect(
        repo,
        managed,
        private_authorizations=authorizations,
        grace_hours=1,
        apply=True,
    )

    assert any(item.path == str(private) and item.action == "removed" for item in decisions)
    assert not private.exists()
    assert snapshot.exists()
    assert not target.exists()


def test_private_authorization_rejects_dirty_worktree(tmp_path: Path):
    repo, _ = repository(tmp_path)
    managed = tmp_path / ".private-worktrees"
    private = session(repo, managed)
    (private / "uncommitted.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(gc.CleanupError, match="changes"):
        gc.authorize_private(repo, private, tmp_path / ".private-releases/missing", tmp_path / "auth")
