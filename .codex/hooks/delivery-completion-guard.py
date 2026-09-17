#!/usr/bin/env python3
"""Prevent a development turn from ending before its delivery is complete."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

BLOCKER_MARKER = "DELIVERY_BLOCKED:"
PRODUCTION_SCHEMA = "aigcnews.production-state.v1"


class GuardError(RuntimeError):
    pass


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GIT_") and key not in {"GIT_SSH", "GIT_SSH_COMMAND"}:
            env.pop(key, None)
    return env


def _run(command: Sequence[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_git_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise GuardError(f"{command[0]} failed: {detail}")
    return completed


def _git(cwd: Path, *args: str) -> str:
    return _run(["git", *args], cwd=cwd).stdout.strip()


def _block(reason: str) -> dict[str, object]:
    instruction = (
        f"Delivery is incomplete: {reason} Continue the existing unattended pipeline without asking "
        "the user: ensure the session branch is pushed, follow Session PR, Contract Baseline, exact-SHA "
        "auto-merge, the main baseline, and Deploy Production until the task is active in production. "
        "Do not manually bypass gates or interfere with another task's run. Diagnose and fix an in-scope "
        f"failure. Only for a genuine external/manual blocker, report evidence with `{BLOCKER_MARKER} ...`."
    )
    return {"decision": "block", "reason": instruction, "systemMessage": instruction}


def _session_changes(cwd: Path, base: str) -> tuple[list[str], list[str]]:
    lines = [line for line in _git(cwd, "cherry", base, "HEAD").splitlines() if line]
    positive = [line[2:] for line in lines if line.startswith("+ ")]
    equivalent = [line[2:] for line in lines if line.startswith("- ")]
    return positive, equivalent


def _branch_has_commits(cwd: Path, branch: str, head: str) -> bool:
    reflog = _run(
        ["git", "reflog", "show", "--format=%H", f"refs/heads/{branch}"],
        cwd=cwd,
        check=False,
    ).stdout.splitlines()
    # dev_session.py creates a fresh, unique local branch, so its oldest
    # reflog entry is the immutable session baseline. Fail closed if that
    # evidence is unavailable: an empty development session should be rare,
    # while silently skipping a delivered commit would violate the contract.
    return not reflog or reflog[-1].strip() != head


def _production_root(cwd: Path) -> Path:
    override = os.environ.get("AIGCNEWS_PRODUCTION_ROOT", "").strip()
    if override:
        return Path(override).expanduser()
    configured = _run(
        ["git", "config", "--get", "aigcnews.productionRoot"], cwd=cwd, check=False
    ).stdout.strip()
    if configured:
        return Path(configured).expanduser()
    common = Path(_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common.parent.with_name(f"{common.parent.name}-production")


def _read_production_state(root: Path) -> dict[str, object]:
    path = root / ".aigcnews-deploy" / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GuardError(f"production state is missing at {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"production state is unreadable at {path}: {exc}") from None
    if not isinstance(state, dict) or state.get("schema") != PRODUCTION_SCHEMA:
        raise GuardError(f"production state at {path} has an unsupported schema")
    return state


def evaluate(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("hook_event_name") != "Stop":
        return {}

    last_message = str(payload.get("last_assistant_message") or "")
    if payload.get("stop_hook_active") is True and BLOCKER_MARKER in last_message:
        return {}

    cwd = Path(str(payload.get("cwd") or ".")).resolve()
    try:
        root = Path(_git(cwd, "rev-parse", "--show-toplevel"))
        branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except GuardError:
        return {}
    if not branch.startswith("session/"):
        return {}

    if _git(root, "status", "--porcelain=v1"):
        return _block("the session worktree still has staged, unstaged, or untracked changes.")

    head = _git(root, "rev-parse", "HEAD")
    has_commits = _branch_has_commits(root, branch, head)

    try:
        _git(
            root,
            "fetch",
            "--quiet",
            "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
        _run(
            [
                "git",
                "fetch",
                "--quiet",
                "origin",
                f"refs/heads/{branch}:refs/remotes/origin/{branch}",
            ],
            cwd=root,
            check=False,
        )
        positive, equivalent = _session_changes(root, "origin/main")
    except GuardError as exc:
        return _block(f"remote delivery state could not be verified ({exc}).")

    if not positive and not equivalent and not has_commits:
        return {}

    remote = _run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"], cwd=root, check=False
    ).stdout.strip()
    if positive and remote != head:
        return _block("the current session commit has not been pushed to the same-name remote branch.")
    if positive:
        return _block("the pushed session changes are not yet patch-equivalent to origin/main.")

    try:
        state = _read_production_state(_production_root(root))
    except GuardError as exc:
        return _block(str(exc) + ".")
    in_progress = state.get("in_progress")
    active = state.get("active_release")
    if in_progress is not None:
        return _block(f"production release {in_progress} is still in progress.")
    if not isinstance(active, str) or len(active) != 40:
        return _block("production has no valid active release.")
    if _run(["git", "cat-file", "-e", f"{active}^{{commit}}"], cwd=root, check=False).returncode:
        try:
            _git(root, "fetch", "--quiet", "origin", active)
        except GuardError as exc:
            return _block(f"active production commit {active} could not be inspected ({exc}).")
    deployed_positive, _ = _session_changes(root, active)
    if deployed_positive:
        failed = state.get("last_failed_release")
        suffix = f"; last failed release is {failed}" if failed else ""
        return _block(f"active production release {active} does not contain this task{suffix}.")
    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")
        result = evaluate(payload)
    except Exception as exc:  # noqa: BLE001 - a Stop guard must fail closed
        result = _block(f"the delivery guard failed closed ({type(exc).__name__}: {exc}).")
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
