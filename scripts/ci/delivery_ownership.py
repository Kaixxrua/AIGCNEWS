"""Creation-time ownership receipts; dashboard labels never authorize wakeups."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

SCHEMA_CODEX = "aigcnews.delivery-owner.v1"
# Non-Codex owners use a newer schema. Controllers that predate it still read
# thread_id to enqueue the push, but their v1-only wakeup and success paths
# treat the task as unowned instead of addressing it as a Codex thread.
SCHEMA_PROVIDER = "aigcnews.delivery-owner.v2"
CLAUDE_OWNER_PREFIX = "claude:"


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.check_output(["git", "-C", str(root), *args], env=env,
                                   text=True, stderr=subprocess.DEVNULL, timeout=10).strip()


def receipt_path(root, branch):
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common / "delivery-owners" / (hashlib.sha256(branch.encode()).hexdigest() + ".json")


def owner_provider(owner):
    """Return the provider of an exact owner identity; raise ValueError otherwise.

    Codex owners are bare thread UUIDs. Claude Code owners are
    ``claude:<canonical session UUID>``, which no Codex transport accepts.
    """
    if not isinstance(owner, str):
        raise ValueError("owner identity must be a string")
    if owner.startswith(CLAUDE_OWNER_PREFIX):
        session = owner.removeprefix(CLAUDE_OWNER_PREFIX)
        if str(uuid.UUID(session)) != session:
            raise ValueError("Claude Code session ID must be a canonical UUID")
        return "claude"
    uuid.UUID(owner)
    return "codex"


def record_owner(root, branch, owner):
    """Called only by dev_session start, never inferred from a later observer."""
    provider = owner_provider(owner)
    root = Path(root).resolve()
    if not branch.startswith("session/") or git(root, "symbolic-ref", "--short", "HEAD") != branch:
        raise ValueError("owner receipt requires the newly created session branch")
    path = receipt_path(root, branch)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    payload = {"schema": SCHEMA_CODEX, "source": "dev_session.start",
               "branch": branch, "thread_id": owner, "worktree": str(root)}
    if provider != "codex":
        payload.update(schema=SCHEMA_PROVIDER, provider=provider)
    # Exclusive creation prevents another task from silently rebinding an owner.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream)


def resolve_owner(branch, root=None):
    root = Path(root) if root else Path.home() / "AIGCNEWS"
    try:
        path = receipt_path(root, branch)
        data = json.loads(path.read_text())
        if data.get("source") != "dev_session.start":
            return None
        if data.get("branch") != branch or not branch.startswith("session/"):
            return None
        owner = data["thread_id"]
        provider = owner_provider(owner)
        # The schema and provider must agree with the owner form; a v1 receipt
        # can never carry a non-Codex owner and vice versa.
        expected = SCHEMA_CODEX if provider == "codex" else SCHEMA_PROVIDER
        if data.get("schema") != expected or data.get("provider", "codex") != provider:
            return None
        worktree = Path(data["worktree"])
        if not worktree.is_absolute() or worktree.resolve() == root.resolve():
            return None
        if receipt_path(worktree, branch) != path:
            return None
        if git(worktree, "symbolic-ref", "--short", "HEAD") != branch:
            return None
        return owner
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None
