from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "dev_session.py"
_SPEC = importlib.util.spec_from_file_location("dev_session", _SCRIPT)
assert _SPEC and _SPEC.loader
_session = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _session
_SPEC.loader.exec_module(_session)


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch):
    # Git hooks export GIT_INDEX_FILE/GIT_DIR/etc.; these tests spawn git in
    # temporary repositories and must never operate on the enclosing repo.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)


def test_start_rejects_unsafe_slug(tmp_path):
    with pytest.raises(_session.SessionError, match="lowercase kebab-case"):
        _session.start("Feature_X", tmp_path)


def test_worktrees_parses_porcelain(monkeypatch, tmp_path):
    monkeypatch.setattr(
        _session,
        "git",
        lambda *args, cwd: """worktree /tmp/root
HEAD abc123
branch refs/heads/main

worktree /tmp/session
HEAD def456
branch refs/heads/session/demo-1

""",
    )
    result = _session.worktrees(tmp_path)
    assert result == [
        _session.Worktree(Path("/tmp/root"), "abc123", "main"),
        _session.Worktree(Path("/tmp/session"), "def456", "session/demo-1"),
    ]


def test_status_marks_main_and_dirty(monkeypatch, tmp_path):
    monkeypatch.setattr(_session, "current_worktree", lambda root: _session.Worktree(root, "abc", "main"))
    monkeypatch.setattr(_session, "worktrees", lambda root: [_session.Worktree(root, "abc", "main")])
    monkeypatch.setattr(_session, "primary_worktree", lambda root: root)
    monkeypatch.setattr(_session, "base_exists", lambda root: True)

    def fake_git(*args, cwd):
        if args[:3] == ("rev-list", "--left-right", "--count"):
            return "0 0"
        if args[0] == "merge-base":
            return "base"
        if args[:2] == ("rev-parse", "origin/main"):
            return "base"
        if args[:2] == ("status", "--porcelain=v1"):
            return " M file.py\n?? scratch.txt"
        raise AssertionError(args)

    monkeypatch.setattr(_session, "git", fake_git)
    result = _session.status(tmp_path)
    assert result["ok"] is False
    assert {"main", "primary_worktree", "dirty"} <= set(result["risk"])
    assert result["untracked"] is True
    assert result["staged"] is False


def test_status_marks_detached_and_ghost_parent(monkeypatch, tmp_path):
    monkeypatch.setattr(_session, "current_worktree", lambda root: _session.Worktree(root, "abc", None))
    monkeypatch.setattr(_session, "worktrees", lambda root: [_session.Worktree(root, "abc", None)])
    monkeypatch.setattr(_session, "primary_worktree", lambda root: root)
    monkeypatch.setattr(_session, "base_exists", lambda root: False)
    monkeypatch.setattr(_session, "git", lambda *args, cwd: "")
    result = _session.status(tmp_path)
    assert result["ok"] is False
    assert {"detached", "primary_worktree", "ghost_parent"} <= set(result["risk"])
    assert result["divergence"] == {"ahead": None, "behind": None}


def _receipt(level: _session.RiskLevel, *, passed: bool = True) -> _session.ValidationReceipt:
    paths = {
        _session.RiskLevel.GREEN: ["README.md"],
        _session.RiskLevel.YELLOW: ["backend/app/auth/service.py"],
        _session.RiskLevel.RED: ["backend/app/postgres_migrations/001.sql"],
    }[level]
    return _session.ValidationReceipt(
        commit="a" * 40,
        risk=_session.classify_paths(paths),
        checks=("pytest",),
        passed=passed,
        expected_head="b" * 40,
    )


def _patch_land_common(monkeypatch, tmp_path, receipt):
    monkeypatch.setattr(_session, "current_worktree", lambda root: _session.Worktree(root, "a" * 40, "session/demo-1"))
    monkeypatch.setattr(_session, "status", lambda root: {"dirty": False})
    monkeypatch.setattr(_session, "_receipt_from_file", lambda path: receipt)
    monkeypatch.setattr(_session, "landing_lock", lambda root: __import__("contextlib").nullcontext())


def test_land_refuses_red_and_requires_yellow_confirmation(monkeypatch, tmp_path):
    red = _receipt(_session.RiskLevel.RED)
    _patch_land_common(monkeypatch, tmp_path, red)
    with pytest.raises(_session.SessionError, match="Red"):
        _session.land(tmp_path / "receipt.json", tmp_path)

    yellow = _receipt(_session.RiskLevel.YELLOW)
    _patch_land_common(monkeypatch, tmp_path, yellow)
    with pytest.raises(_session.SessionError, match="confirm-yellow"):
        _session.land(tmp_path / "receipt.json", tmp_path)


def test_land_refuses_unpassed_receipt_before_lock(monkeypatch, tmp_path):
    _patch_land_common(monkeypatch, tmp_path, _receipt(_session.RiskLevel.GREEN))
    monkeypatch.setattr(
        _session,
        "_receipt_from_file",
        lambda path: (_ for _ in ()).throw(_session.SessionError("validation receipt is not a passed v1 receipt")),
    )
    with pytest.raises(_session.SessionError, match="passed"):
        _session.land(tmp_path / "receipt.json", tmp_path)


def test_land_requires_remote_base_to_match_receipt(monkeypatch, tmp_path):
    receipt = _receipt(_session.RiskLevel.GREEN)
    _patch_land_common(monkeypatch, tmp_path, receipt)
    monkeypatch.setattr(_session, "git", lambda *args, cwd: "/".join(args) if args[:2] == ("rev-parse", "--git-common-dir") else "c" * 40)
    with pytest.raises(_session.SessionError, match="moved"):
        _session.land(tmp_path / "receipt.json", tmp_path)


def _run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


def _temporary_remote(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    root = tmp_path / "checkout"
    _run_git(tmp_path, "init", "--bare", str(bare))
    _run_git(tmp_path, "init", str(seed))
    _run_git(seed, "config", "user.name", "test")
    _run_git(seed, "config", "user.email", "test@example.invalid")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(seed, "add", "README.md")
    _run_git(seed, "commit", "-m", "initial")
    _run_git(seed, "branch", "-M", "main")
    hooks = Path(__file__).parents[2] / ".githooks"
    shutil.copytree(hooks, seed / ".githooks")
    _run_git(seed, "add", ".githooks")
    _run_git(seed, "commit", "-m", "tracked hooks")
    _run_git(seed, "remote", "add", "origin", str(bare))
    _run_git(seed, "push", "origin", "main")
    # A bare repo initialized with the platform default branch points HEAD at a
    # nonexistent ref; without this the clone has no checked-out working tree.
    _run_git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    _run_git(tmp_path, "clone", str(bare), str(root))
    _run_git(root, "config", "user.name", "test")
    _run_git(root, "config", "user.email", "test@example.invalid")
    _run_git(root, "config", "extensions.worktreeConfig", "true")
    _run_git(root, "fetch", "origin", "main")
    return bare, root


def _session_checkout(tmp_path: Path) -> tuple[Path, Path, str]:
    _, root = _temporary_remote(tmp_path)
    session = Path(_session.start("landing-test", root)["worktree"])
    _run_git(session, "config", "user.name", "test")
    _run_git(session, "config", "user.email", "test@example.invalid")
    (session / "README.md").write_text("landed\n", encoding="utf-8")
    _run_git(session, "add", "README.md")
    # Fixture commit only: the project pre-commit suite is not under test here.
    _run_git(session, "commit", "--no-verify", "-m", "change")
    commit = _run_git(session, "rev-parse", "HEAD").stdout.strip()
    return root, session, commit


def test_git_helper_ignores_leaked_hook_environment(monkeypatch, tmp_path):
    repo = tmp_path / "poisoned-target"
    other = tmp_path / "other"
    _run_git(tmp_path, "init", str(repo))
    _run_git(repo, "config", "user.name", "test")
    _run_git(repo, "config", "user.email", "test@example.invalid")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "init")
    _run_git(tmp_path, "init", str(other))
    # Simulate the variables Git exports into hook-spawned processes; every
    # repo-directing variable must be stripped before spawning git.
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.bare'=true")
    assert _session.git("rev-parse", "--show-toplevel", cwd=repo) == str(repo.resolve())
    assert _session.git("rev-parse", "--is-bare-repository", cwd=repo) == "false"
    # Transport helpers survive the scrub.
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    assert "GIT_SSH_COMMAND" in _session._git_env()


def _write_receipt(path: Path, commit: str, expected_head: str, *, paths: list[str] | None = None) -> None:
    # Receipts are validated against the real classifier, so build the risk
    # block from classify_paths instead of hardcoding a level.
    assessment = _session.classify_paths(paths or ["README.md"])
    payload = {
        "schema": "aigcnews.validation-receipt.v1",
        "commit": commit,
        "expected_head": expected_head,
        "risk": assessment.to_dict(),
        "checks": ["pytest"],
        "passed": True,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _advance_remote(tmp_path: Path, bare: Path, label: str = "upstream") -> str:
    other = tmp_path / f"other-{label}"
    _run_git(tmp_path, "clone", str(bare), str(other))
    _run_git(other, "config", "user.name", "test")
    _run_git(other, "config", "user.email", "test@example.invalid")
    (other / "UPSTREAM.md").write_text(label + "\n", encoding="utf-8")
    _run_git(other, "add", "UPSTREAM.md")
    _run_git(other, "commit", "--no-verify", "-m", label)
    _run_git(other, "push", "origin", "main")
    return _run_git(other, "rev-parse", "HEAD").stdout.strip()


def test_start_creates_real_linked_worktree_with_local_hooks(tmp_path):
    root = _temporary_remote(tmp_path)[1]
    result = _session.start("real-session", root)
    session = Path(result["worktree"])
    assert session.is_dir()
    assert _run_git(session, "branch", "--show-current").stdout.strip().startswith("session/")
    assert _run_git(session, "config", "--worktree", "--get", "core.hooksPath").stdout.strip() == ".githooks"
    assert (session / ".githooks" / "pre-push").is_file()
    for hook in ("pre-commit", "commit-msg", "pre-push", "post-commit"):
        assert os.access(session / ".githooks" / hook, os.X_OK)


def test_start_records_owner_without_allowing_rebind(tmp_path, monkeypatch):
    from scripts.ci.delivery_ownership import record_owner, resolve_owner

    root = _temporary_remote(tmp_path)[1]
    owner = "01a0a9b2-7db0-78a2-a960-cfc652157d21"
    monkeypatch.setenv("CODEX_THREAD_ID", owner)
    result = _session.start("owner-test", root)
    assert resolve_owner(result["branch"], root) == owner
    with pytest.raises(FileExistsError):
        record_owner(result["worktree"], result["branch"], owner)
    _run_git(Path(result["worktree"]), "checkout", "--detach")
    assert resolve_owner(result["branch"], root) is None


def test_legacy_session_without_owner_is_not_inferred(tmp_path, monkeypatch):
    from scripts.ci.delivery_ownership import resolve_owner

    root = _temporary_remote(tmp_path)[1]
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    result = _session.start("no-owner", root)
    assert resolve_owner(result["branch"], root) is None


def test_bad_owner_rejected_before_worktree_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "not-a-task-id")
    with pytest.raises(_session.SessionError, match="CODEX_THREAD_ID"):
        _session.start("bad-owner", tmp_path)


def test_start_from_linked_worktree_does_not_nest_sessions(tmp_path):
    root = _temporary_remote(tmp_path)[1]
    first = Path(_session.start("first-session", root)["worktree"])
    second = Path(_session.start("second-session", first)["worktree"])
    assert second.parent == root / ".claude" / "worktrees"
    assert not str(second).startswith(str(first) + os.sep)


def test_status_distinguishes_unstaged_from_staged_changes(tmp_path):
    root = _temporary_remote(tmp_path)[1]
    session = Path(_session.start("status-session", root)["worktree"])
    (session / "README.md").write_text("unstaged\n", encoding="utf-8")

    unstaged = _session.status(session)

    assert unstaged["dirty"] is True
    assert unstaged["staged"] is False
    _run_git(session, "add", "README.md")
    staged = _session.status(session)
    assert staged["staged"] is True


def test_pre_commit_rejects_session_branch_in_primary_checkout(tmp_path):
    root = _temporary_remote(tmp_path)[1]
    _run_git(root, "switch", "-c", "session/primary-misuse-1")
    hook = root / ".githooks" / "pre-commit"

    rejected = subprocess.run([str(hook)], cwd=root, text=True, capture_output=True, check=False)

    assert rejected.returncode != 0
    assert "primary checkout" in rejected.stderr


def test_pre_commit_allows_clean_linked_session_without_staged_files(tmp_path):
    root = _temporary_remote(tmp_path)[1]
    session = Path(_session.start("hook-session", root)["worktree"])
    hook = session / ".githooks" / "pre-commit"

    accepted = subprocess.run([str(hook)], cwd=session, text=True, capture_output=True, check=False)

    assert accepted.returncode == 0


def test_post_commit_pushes_session_to_same_name_despite_main_upstream(tmp_path):
    bare, root = _temporary_remote(tmp_path)
    session = Path(_session.start("push-test", root)["worktree"])
    branch = _run_git(session, "branch", "--show-current").stdout.strip()
    assert _run_git(session, "rev-parse", "--abbrev-ref", "@{upstream}").stdout.strip() == "origin/main"
    _run_git(session, "config", "user.name", "test")
    _run_git(session, "config", "user.email", "test@example.invalid")
    (session / "PUSHED.md").write_text("published\n", encoding="utf-8")
    _run_git(session, "add", "PUSHED.md")

    committed = _run_git(session, "commit", "--no-verify", "-m", "test(workflow): publish session")

    assert "push failed" not in committed.stderr
    assert _run_git(bare, "rev-parse", f"refs/heads/{branch}").stdout.strip() == _run_git(
        session, "rev-parse", "HEAD"
    ).stdout.strip()
    assert _run_git(session, "rev-parse", "--abbrev-ref", "@{upstream}").stdout.strip() == f"origin/{branch}"


def test_land_success_uses_non_force_push_and_cleans_nonce(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    expected = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, expected)
    result = _session.land(receipt, session)
    assert result["old_head"] == expected
    assert result["new_head"] == commit
    assert _run_git(tmp_path / "remote.git", "rev-parse", "refs/heads/main").stdout.strip() == commit
    common = _session._git_common_dir(session)
    assert not (common / "aigcnews-landing.nonce").exists()


def test_pre_push_rejects_main_without_nonce_and_accepts_matching_nonce(tmp_path):
    _, root = _temporary_remote(tmp_path)
    hook = root / ".githooks" / "pre-push"
    env = os.environ.copy()
    env["AIGCNEWS_LANDING_COMMAND"] = "1"
    rejected = subprocess.run(
        [str(hook), "origin"], cwd=root, text=True,
        input=f"refs/heads/main {'0' * 40} refs/heads/main {'0' * 40}\n",
        capture_output=True, env=env, check=False,
    )
    assert rejected.returncode != 0
    nonce_file = _session._git_common_dir(root) / "aigcnews-landing.nonce"
    nonce_file.write_text("test-nonce\n", encoding="ascii")
    nonce_file.chmod(0o600)
    env["AIGCNEWS_LANDING_NONCE"] = "test-nonce"
    accepted = subprocess.run(
        [str(hook), "origin"], cwd=root, text=True,
        input=f"refs/heads/session/test-1 {'0' * 40} refs/heads/main {'0' * 40}\n",
        capture_output=True, env=env, check=False,
    )
    assert accepted.returncode == 0
    assert stat.S_IMODE(nonce_file.stat().st_mode) == 0o600
    nonce_file.unlink()


def test_land_refuses_after_remote_moves_and_preserves_branch(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    bare = tmp_path / "remote.git"
    expected = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, expected)
    upstream = _advance_remote(tmp_path, bare)
    with pytest.raises(_session.SessionError, match="moved since validation"):
        _session.land(receipt, session)
    # The failed landing leaves the remote, the task branch, and no nonce.
    assert _run_git(bare, "rev-parse", "refs/heads/main").stdout.strip() == upstream
    branch = _run_git(session, "branch", "--show-current").stdout.strip()
    assert _run_git(root, "rev-parse", f"refs/heads/{branch}").stdout.strip() == commit
    assert not (_session._git_common_dir(session) / "aigcnews-landing.nonce").exists()


def test_land_refuses_stale_head_even_with_current_receipt(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    bare = tmp_path / "remote.git"
    # The receipt names the moved remote head, but the task HEAD never
    # contained it: the ancestry check, not the receipt check, must fire.
    upstream = _advance_remote(tmp_path, bare)
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, upstream)
    with pytest.raises(_session.SessionError, match="stale"):
        _session.land(receipt, session)
    assert _run_git(bare, "rev-parse", "refs/heads/main").stdout.strip() == upstream


def test_land_refuses_while_another_landing_holds_lock(tmp_path):
    import fcntl

    root, session, commit = _session_checkout(tmp_path)
    expected = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, expected)
    lock_path = _session._git_common_dir(session) / "aigcnews-landing.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(_session.SessionError, match="another landing is in progress"):
            _session.land(receipt, session)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    # Releasing the contender's lock lets the same receipt land cleanly.
    result = _session.land(receipt, session)
    assert result["new_head"] == commit


def test_land_cleans_nonce_when_remote_rejects_push(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    bare = tmp_path / "remote.git"
    expected = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, expected)
    pre_receive = bare / "hooks" / "pre-receive"
    pre_receive.write_text("#!/bin/sh\nexit 1\n", encoding="ascii")
    pre_receive.chmod(0o755)
    with pytest.raises(_session.SessionError, match="non-force landing push rejected"):
        _session.land(receipt, session)
    assert _run_git(bare, "rev-parse", "refs/heads/main").stdout.strip() == expected
    assert not (_session._git_common_dir(session) / "aigcnews-landing.nonce").exists()


def test_land_yellow_receipt_requires_and_honors_confirmation(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    expected = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, expected, paths=["backend/app/auth/service.py"])
    with pytest.raises(_session.SessionError, match="confirm-yellow"):
        _session.land(receipt, session)
    result = _session.land(receipt, session, confirm_yellow=True)
    assert result["new_head"] == commit
    assert _run_git(tmp_path / "remote.git", "rev-parse", "refs/heads/main").stdout.strip() == commit


def test_land_rejects_receipt_with_stale_risk_classification(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    expected = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, expected, paths=["backend/app/postgres_migrations/001.sql"])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    # A receipt that downgrades a Red path to green is stale/tampered and must
    # be refused before any lock or push happens.
    payload["risk"]["level"] = "green"
    payload["risk"]["reasons"] = []
    receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(_session.SessionError, match="stale"):
        _session.land(receipt, session)


def test_land_preserves_foreign_refs_worktrees_and_dirty_files(tmp_path):
    root, session, commit = _session_checkout(tmp_path)
    bare = tmp_path / "remote.git"
    foreign_wt = tmp_path / "foreign-wt"
    _run_git(root, "worktree", "add", "--detach", str(foreign_wt), "origin/main")
    base = _run_git(root, "rev-parse", "origin/main").stdout.strip()
    _run_git(root, "branch", "foreign-work", base)
    (root / "README.md").write_text("foreign dirty\n", encoding="utf-8")
    (root / "scratch.txt").write_text("keep me\n", encoding="utf-8")
    refs_before = _run_git(root, "for-each-ref", "refs/heads").stdout
    worktrees_before = _run_git(root, "worktree", "list", "--porcelain").stdout
    receipt = tmp_path / "receipt.json"
    _write_receipt(receipt, commit, base)
    _session.land(receipt, session)
    assert _run_git(root, "for-each-ref", "refs/heads").stdout == refs_before
    assert _run_git(root, "worktree", "list", "--porcelain").stdout == worktrees_before
    assert (root / "README.md").read_text(encoding="utf-8") == "foreign dirty\n"
    assert (root / "scratch.txt").read_text(encoding="utf-8") == "keep me\n"
    assert _run_git(bare, "rev-parse", "refs/heads/main").stdout.strip() == commit
