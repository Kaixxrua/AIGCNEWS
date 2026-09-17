#!/usr/bin/env python3
"""Serialize and apply an immutable production release on the deployment host.

The GitHub deployment queue is the first serialization layer.  This controller
adds a host-local lock, rejects superseded main commits before mutation, writes
the exact image digests atomically, and only rolls back a release that it still
owns.  It deliberately never builds images or accepts mutable image tags.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SCHEMA = "aigcnews.production-state.v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class DeployError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    source_sha: str
    backend_image: str
    mcp_image: str
    frontend_image: str

    def __post_init__(self) -> None:
        if SHA_RE.fullmatch(self.source_sha) is None:
            raise DeployError("source SHA must be 40 lowercase hexadecimal characters")
        for image in (self.backend_image, self.mcp_image, self.frontend_image):
            if IMAGE_RE.fullmatch(image) is None:
                raise DeployError("application images must be immutable repository@sha256 references")

    def env_text(self) -> str:
        return (
            f"AIGCNEWS_RELEASE_SHA={self.source_sha}\n"
            f"AIGCNEWS_BACKEND_IMAGE_DIGEST={self.backend_image}\n"
            f"AIGCNEWS_MCP_IMAGE_DIGEST={self.mcp_image}\n"
            f"AIGCNEWS_FRONTEND_IMAGE_DIGEST={self.frontend_image}\n"
        )


def run(command: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise DeployError(f"command failed ({command[0]}): {detail}")
    return result.stdout.strip()


def atomic_write(path: Path, content: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema": SCHEMA, "active_release": None, "in_progress": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError(f"invalid production state: {exc}") from None
    if state.get("schema") != SCHEMA:
        raise DeployError("unsupported production state schema")
    for field in ("active_release", "in_progress"):
        value = state.get(field)
        if value is not None and (not isinstance(value, str) or SHA_RE.fullmatch(value) is None):
            raise DeployError(f"invalid {field} in production state")
    return state


def write_state(path: Path, state: dict[str, object]) -> None:
    atomic_write(path, json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


@contextmanager
def deployment_lock(path: Path, timeout: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DeployError("another production deployment holds the host lock") from None
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def ensure_clean_tracked_tree(root: Path) -> None:
    if run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root):
        raise DeployError("production checkout has tracked modifications")


def refresh_and_classify(root: Path, release_sha: str) -> str:
    run(["git", "fetch", "origin", "main"], cwd=root)
    remote = run(["git", "rev-parse", "origin/main"], cwd=root)
    if remote == release_sha:
        return "current"
    contains = subprocess.run(
        ["git", "merge-base", "--is-ancestor", release_sha, remote], cwd=root, check=False
    )
    if contains.returncode == 0:
        return "superseded"
    raise DeployError("candidate is not the current main commit or its ancestor")


def checkout(root: Path, source_sha: str) -> None:
    run(["git", "checkout", "--detach", source_sha], cwd=root)


def reconcile(root: Path, release: Release) -> None:
    for image in (release.backend_image, release.mcp_image, release.frontend_image):
        # Inspect the immutable reference, never a tag: a local build can be
        # deployed without uploading and downloading the same layers via GHCR.
        try:
            run(["docker", "image", "inspect", image], cwd=root)
        except DeployError:
            run(["docker", "pull", image], cwd=root)
    environment = os.environ.copy()
    environment["AIGCNEWS_RELEASE_ENV"] = str(root / ".release.env")
    run([str(root / "scripts" / "manage_main_stack.sh"), "up"], cwd=root, env=environment)
    probe_backend()


def reconcile_existing(root: Path) -> None:
    environment = os.environ.copy()
    environment["AIGCNEWS_RELEASE_ENV"] = str(root / ".release.env")
    run([str(root / "scripts" / "manage_main_stack.sh"), "up"], cwd=root, env=environment)
    probe_backend()


def probe_backend() -> None:
    for path in ("/api/live", "/api/ready"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=10) as response:
                if response.status != 200:
                    raise DeployError(f"production probe {path} returned HTTP {response.status}")
        except OSError as exc:
            raise DeployError(f"production probe {path} failed: {exc}") from None


def deploy(root: Path, release: Release, *, lock_timeout: float = 600) -> str:
    root = root.resolve()
    control = root / ".aigcnews-deploy"
    state_path = control / "state.json"
    env_path = root / ".release.env"
    with deployment_lock(control / "deploy.lock", lock_timeout):
        ensure_clean_tracked_tree(root)
        classification = refresh_and_classify(root, release.source_sha)
        if classification == "superseded":
            return "superseded"

        state = read_state(state_path)
        if state.get("active_release") == release.source_sha and state.get("in_progress") is None:
            return "already-active"
        if state.get("in_progress") is not None:
            raise DeployError("production state contains an unfinished deployment")

        old_sha = state.get("active_release")
        old_checkout = run(["git", "rev-parse", "HEAD"], cwd=root)
        old_env = env_path.read_text(encoding="utf-8") if env_path.exists() else None
        state["in_progress"] = release.source_sha
        write_state(state_path, state)

        try:
            checkout(root, release.source_sha)
            atomic_write(env_path, release.env_text())
            reconcile(root, release)
        except Exception as deploy_error:
            current = read_state(state_path)
            if current.get("in_progress") != release.source_sha:
                raise DeployError("deployment ownership changed; refusing unsafe rollback") from deploy_error
            rollback_error: Exception | None = None
            try:
                if isinstance(old_sha, str) and old_env is not None:
                    checkout(root, old_sha)
                    atomic_write(env_path, old_env)
                    previous = parse_release_env(old_env)
                    reconcile(root, previous)
                elif old_env is None:
                    checkout(root, old_checkout)
                    env_path.unlink(missing_ok=True)
                    reconcile_existing(root)
            except Exception as exc:  # preserve both deployment and rollback evidence
                rollback_error = exc
            state["in_progress"] = None
            state["last_failed_release"] = release.source_sha
            write_state(state_path, state)
            if rollback_error is not None:
                raise DeployError(f"deployment failed ({deploy_error}); rollback also failed ({rollback_error})") from deploy_error
            raise DeployError(f"deployment failed and previous runtime was restored: {deploy_error}") from deploy_error

        state.update({
            "active_release": release.source_sha,
            "in_progress": None,
            "previous_release": old_sha,
            "images": {
                "backend": release.backend_image,
                "mcp": release.mcp_image,
                "frontend": release.frontend_image,
            },
        })
        write_state(state_path, state)
        return "deployed"


def parse_release_env(content: str) -> Release:
    values: dict[str, str] = {}
    for line in content.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    try:
        return Release(
            source_sha=values["AIGCNEWS_RELEASE_SHA"],
            backend_image=values["AIGCNEWS_BACKEND_IMAGE_DIGEST"],
            mcp_image=values["AIGCNEWS_MCP_IMAGE_DIGEST"],
            frontend_image=values["AIGCNEWS_FRONTEND_IMAGE_DIGEST"],
        )
    except KeyError as exc:
        raise DeployError(f"previous release environment lacks {exc.args[0]}") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--mcp-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--lock-timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        result = deploy(
            args.root,
            Release(args.source_sha, args.backend_image, args.mcp_image, args.frontend_image),
            lock_timeout=args.lock_timeout,
        )
    except DeployError as exc:
        print(f"production deployment rejected: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
