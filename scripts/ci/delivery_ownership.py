"""Creation-time ownership receipts; dashboard labels never authorize wakeups."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.check_output(["git", "-C", str(root), *args], env=env,
                                   text=True, stderr=subprocess.DEVNULL, timeout=10).strip()


def receipt_path(root, branch):
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common / "delivery-owners" / (hashlib.sha256(branch.encode()).hexdigest() + ".json")


def record_owner(root, branch, thread_id):
    """Called only by dev_session start, never inferred from a later observer."""
    uuid.UUID(thread_id)
    root = Path(root).resolve()
    if not branch.startswith("session/") or git(root, "symbolic-ref", "--short", "HEAD") != branch:
        raise ValueError("owner receipt requires the newly created session branch")
    path = receipt_path(root, branch)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    payload = {"schema": "aigcnews.delivery-owner.v1", "source": "dev_session.start",
               "branch": branch, "thread_id": thread_id, "worktree": str(root)}
    # Exclusive creation prevents another task from silently rebinding an owner.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream)


def resolve_owner(branch, root=None):
    root = Path(root) if root else Path.home() / "AIGCNEWS"
    try:
        path = receipt_path(root, branch)
        data = json.loads(path.read_text())
        if data.get("schema") != "aigcnews.delivery-owner.v1" or data.get("source") != "dev_session.start":
            return None
        if data.get("branch") != branch or not branch.startswith("session/"):
            return None
        thread_id = data["thread_id"]
        uuid.UUID(thread_id)
        worktree = Path(data["worktree"])
        if not worktree.is_absolute() or worktree.resolve() == root.resolve():
            return None
        if receipt_path(worktree, branch) != path:
            return None
        if git(worktree, "symbolic-ref", "--short", "HEAD") != branch:
            return None
        return thread_id
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None
