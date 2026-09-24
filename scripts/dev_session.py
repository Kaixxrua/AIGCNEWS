#!/usr/bin/env python3
"""Create and validate branch-backed development sessions.

The command deliberately fails closed: it never resets, stashes, rebases, or
removes worktrees.  A session is a unique ``session/<slug>-<id>`` branch with a
worktree registered by Git and based on ``origin/main``.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Direct invocation (``python scripts/dev_session.py``) puts only scripts/ on
# sys.path; anchor the worktree root so ``scripts.risk_controls`` imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ci import ao_delivery_adapter
from scripts.ci.delivery_ownership import CLAUDE_OWNER_PREFIX, owner_provider, record_owner
from scripts.risk_controls import RiskLevel, ValidationReceipt, classify_paths

SESSION_RE = re.compile(r"^session/(?P<name>[a-z0-9][a-z0-9-]{1,127})$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch: str | None


# Git hooks export these variables into every hook-spawned process.  If they
# leak into a child that runs git against a different repository (a temp repo
# in tests, or the landing push from a hook context), every command silently
# targets the enclosing repo instead of ``cwd``.  Strip the repo-directing
# variables while keeping transport helpers such as GIT_SSH_COMMAND and
# GIT_ASKPASS.
_GIT_REPO_ENV_VARS = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_QUARANTINE_PATH",
    "GIT_NAMESPACE", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
})


def _git_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in _GIT_REPO_ENV_VARS}


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False, env=_git_env(),
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SessionError(f"git {' '.join(args)} failed: {detail}")
    # Keep leading porcelain whitespace: in `git status --porcelain=v1` the
    # first column is the index state, so stripping it turns an unstaged-only
    # first entry into a false staged entry. Git command output only needs its
    # trailing record separator removed here.
    return result.stdout.rstrip()


def repo_root(cwd: Path | None = None) -> Path:
    return Path(git("rev-parse", "--show-toplevel", cwd=cwd or Path.cwd())).resolve()


def worktrees(root: Path) -> list[Worktree]:
    raw = git("worktree", "list", "--porcelain", cwd=root)
    entries: list[Worktree] = []
    current: dict[str, str] = {}
    for line in (*raw.splitlines(), ""):
        if line:
            key, _, value = line.partition(" ")
            current[key] = value
            continue
        if current:
            entries.append(Worktree(
                path=Path(current["worktree"]).resolve(),
                head=current.get("HEAD", ""),
                branch=current.get("branch", "").removeprefix("refs/heads/") or None,
            ))
            current = {}
    return entries


def current_worktree(root: Path) -> Worktree:
    path = root.resolve()
    matches = [item for item in worktrees(root) if item.path == path]
    if not matches:
        raise SessionError("current directory is not a registered Git worktree")
    return matches[0]


def _git_common_dir(root: Path) -> Path:
    raw = Path(git("rev-parse", "--git-common-dir", cwd=root))
    # A primary checkout prints a relative path (".git"); a linked worktree
    # prints an absolute one. Anchor relative output to root, never to the
    # caller's process cwd.
    return raw.resolve() if raw.is_absolute() else (root / raw).resolve()


def primary_worktree(root: Path) -> Path:
    """Return the primary checkout that owns the shared Git common dir."""
    return _git_common_dir(root).parent


def base_exists(root: Path) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/main"],
        cwd=root, check=False, env=_git_env(),
    )
    return result.returncode == 0


def status(root: Path) -> dict[str, Any]:
    item = current_worktree(root)
    risks: list[str] = []
    primary = primary_worktree(root)
    if item.path == primary:
        risks.append("primary_worktree")
    if item.branch is None:
        risks.append("detached")
    elif item.branch == "main":
        risks.append("main")
    elif SESSION_RE.fullmatch(item.branch) is None:
        risks.append("branch_not_session")

    registered = worktrees(root)
    same_branch = [x for x in registered if item.branch and x.branch == item.branch]
    same_path = [x for x in registered if x.path == item.path]
    if len(same_branch) != 1 or len(same_path) != 1:
        risks.append("reused_branch_or_worktree")
    if not base_exists(root):
        risks.append("ghost_parent")
    hooks_path = subprocess.run(
        ["git", "config", "--worktree", "--get", "core.hooksPath"],
        cwd=root, text=True, capture_output=True, check=False, env=_git_env(),
    ).stdout.strip()
    if hooks_path != ".githooks":
        risks.append("unsafe_hooks_path")

    current = item.head or ""
    base = "origin/main"
    ahead = behind = None
    if base_exists(root) and current:
        counts = git("rev-list", "--left-right", "--count", f"{base}...{current}", cwd=root).split()
        behind, ahead = (int(counts[0]), int(counts[1]))
        if git("merge-base", base, current, cwd=root) != git("rev-parse", base, cwd=root):
            risks.append("not_based_on_origin_main")

    porcelain = git("status", "--porcelain=v1", "--untracked-files=all", cwd=root)
    staged = any(line and line[0] not in " ?" for line in porcelain.splitlines())
    untracked = any(line.startswith("??") for line in porcelain.splitlines())
    dirty = bool(porcelain)
    if dirty:
        risks.append("dirty")

    return {
        "worktree": str(item.path),
        "primary_worktree": str(primary),
        "branch": item.branch,
        "base": base,
        "current": current,
        "clean": not dirty,
        "dirty": dirty,
        "staged": staged,
        "untracked": untracked,
        "divergence": {"ahead": ahead, "behind": behind},
        "risk": risks,
        "ok": not risks,
    }


def task_owner() -> str:
    """Return the exact identity of the agent task creating the session.

    Codex tasks own sessions by thread ID; Claude Code tasks by session ID,
    recorded as ``claude:<uuid>``. A process that inherited both identities
    cannot prove which task is acting, so it is refused rather than guessed.
    """
    codex = os.environ.get("CODEX_THREAD_ID")
    claude = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if codex and claude:
        raise SessionError(
            "both CODEX_THREAD_ID and CLAUDE_CODE_SESSION_ID are set; refusing ambiguous session ownership"
        )
    if codex:
        try:
            uuid.UUID(codex)
        except ValueError:
            raise SessionError("invalid CODEX_THREAD_ID; refusing ambiguous session ownership") from None
        return codex
    if claude:
        owner = CLAUDE_OWNER_PREFIX + claude
        try:
            owner_provider(owner)
        except ValueError:
            raise SessionError("invalid CLAUDE_CODE_SESSION_ID; refusing ambiguous session ownership") from None
        return owner
    raise SessionError(
        "CODEX_THREAD_ID or CLAUDE_CODE_SESSION_ID is required: "
        "create the session from its owning Codex or Claude Code task"
    )


def start(slug: str, root: Path) -> dict[str, Any]:
    if not SLUG_RE.fullmatch(slug):
        raise SessionError("slug must be lowercase kebab-case (2-40 characters)")
    owner = task_owner()
    ao_session = os.environ.get("AO_SESSION_ID")
    ao_evidence = None
    if ao_session is not None:
        # AO bindings are verified against a Codex provider thread.
        if owner_provider(owner) != "codex":
            raise SessionError("AO_SESSION_ID requires a Codex owner; no worktree created")
        try:
            ao_evidence = ao_delivery_adapter.provider_identity(ao_session, owner)
        except Exception as exc:
            raise SessionError(f"AO identity preflight failed; no worktree created: {exc}") from exc
    # Refresh the remote-tracking base on every start; stale bases undermine
    # the branch-backed session contract.
    git("fetch", "origin", "main", cwd=root)
    if not base_exists(root):
        raise SessionError("origin/main is unavailable; refusing to create a session")

    session_id = f"{int(time.time())}-{os.getpid()}-{random.SystemRandom().randint(1000, 9999)}"
    name = f"{slug}-{session_id}"
    branch = f"session/{name}"
    # Always place new sessions below the primary checkout. Calling `start`
    # from an existing linked worktree must not create nested worktrees.
    primary = primary_worktree(root)
    path = (primary / ".claude" / "worktrees" / name).resolve()
    existing = worktrees(root)
    if any(item.branch == branch for item in existing) or any(item.path == path for item in existing):
        raise SessionError("session branch or worktree already exists; refusing reuse")
    if path.exists():
        raise SessionError(f"session worktree path already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Enable per-worktree config before creating the linked checkout; otherwise
    # Git rejects --worktree and every linked checkout inherits one global path.
    git("config", "extensions.worktreeConfig", "true", cwd=root)
    git("worktree", "add", "-b", branch, str(path), "origin/main", cwd=root)
    record_owner(path, branch, owner)
    # A shared absolute hooksPath points at the primary checkout and is unsafe
    # for linked worktrees. Store the tracked relative path in worktree config.
    git("config", "extensions.worktreeConfig", "true", cwd=path)
    git("config", "--worktree", "core.hooksPath", ".githooks", cwd=path)
    result = {
        "worktree": str(path),
        "branch": branch,
        "base": "origin/main",
        "primary_worktree": str(primary),
    }
    if ao_evidence is not None:
        try:
            result["ao_binding"] = ao_delivery_adapter.auto_bind_new(
                branch, ao_session, path, primary, owner,
                git("rev-parse", "HEAD", cwd=path), evidence=ao_evidence,
            )
        except Exception as exc:
            raise SessionError(
                f"AO automatic binding failed; preserve worktree {path} branch {branch}; "
                f"do not start a second writer: {exc}"
            ) from exc
    return result


def _session_branch(item: Worktree) -> None:
    if not item.branch or item.branch == "main" or SESSION_RE.fullmatch(item.branch) is None:
        raise SessionError("landing requires a session/<slug>-<id> branch")


def _receipt_from_file(path: Path) -> ValidationReceipt:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        risk_data = data["risk"]
        assessment = classify_paths(risk_data["paths"])
        if assessment.level.value != risk_data["level"] or tuple(assessment.reasons) != tuple(risk_data["reasons"]):
            raise ValueError("receipt risk classification is stale")
        receipt = ValidationReceipt(
            commit=data["commit"], risk=assessment, checks=tuple(data["checks"]),
            passed=bool(data["passed"]), expected_head=data.get("expected_head"),
            landing_command=data.get("landing_command"), schema=data.get("schema", ""),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SessionError(f"invalid validation receipt: {exc}") from None
    if receipt.schema != "aigcnews.validation-receipt.v1" or not receipt.passed:
        raise SessionError("validation receipt is not a passed v1 receipt")
    return receipt


@contextmanager
def landing_lock(root: Path):
    common = _git_common_dir(root)
    lock_path = common / "aigcnews-landing.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SessionError("another landing is in progress; refusing to queue") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _landing_nonce_path(root: Path) -> Path:
    return _git_common_dir(root) / "aigcnews-landing.nonce"


def land(receipt_path: Path, root: Path, *, confirm_yellow: bool = False) -> dict[str, str]:
    item = current_worktree(root)
    _session_branch(item)
    if status(root)["dirty"]:
        raise SessionError("landing requires a clean worktree")
    receipt = _receipt_from_file(receipt_path)
    if receipt.commit != item.head:
        raise SessionError("validation receipt commit does not match current HEAD")
    if receipt.risk.level is RiskLevel.RED:
        raise SessionError("Red changes cannot be landed by this local command")
    if receipt.risk.level is RiskLevel.YELLOW and not confirm_yellow:
        raise SessionError("Yellow landing requires --confirm-yellow")
    if receipt.expected_head is None:
        raise SessionError("validation receipt has no expected base SHA")
    with landing_lock(root):
        git("fetch", "origin", "main", cwd=root)
        remote_head = git("rev-parse", "origin/main", cwd=root)
        if remote_head != receipt.expected_head:
            raise SessionError("origin/main moved since validation; refresh in the task worktree")
        if git("merge-base", remote_head, item.head, cwd=root) != remote_head:
            raise SessionError("task HEAD is stale relative to origin/main")
        nonce_path = _landing_nonce_path(root)
        nonce = secrets.token_urlsafe(32)
        try:
            nonce_path.write_text(nonce + "\n", encoding="ascii")
            os.chmod(nonce_path, 0o600)
            env = _git_env()
            env["AIGCNEWS_LANDING_COMMAND"] = "1"
            env["AIGCNEWS_LANDING_NONCE"] = nonce
            result = subprocess.run(
                ["git", "push", "origin", f"{item.head}:refs/heads/main"],
                cwd=root, text=True, capture_output=True, check=False, env=env,
            )
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip()
                raise SessionError(f"non-force landing push rejected: {detail}")
        finally:
            try:
                nonce_path.unlink()
            except FileNotFoundError:
                pass
    return {"old_head": receipt.expected_head, "new_head": item.head, "branch": item.branch or ""}


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start", help="create a unique branch-backed worktree")
    start_parser.add_argument("slug")
    sub.add_parser("status", help="report the current session")
    sub.add_parser("check", help="fail unless the current session is safe")
    land_parser = sub.add_parser("land", help="receipt-gated non-force landing to main")
    land_parser.add_argument("receipt", type=Path)
    land_parser.add_argument("--confirm-yellow", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = repo_root()
        if args.command == "start":
            emit(start(args.slug, root))
            return 0
        if args.command == "land":
            emit(land(args.receipt, root, confirm_yellow=args.confirm_yellow))
            return 0
        result = status(root)
        emit(result)
        return 0 if args.command == "status" or result["ok"] else 1
    except SessionError as exc:
        emit({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
