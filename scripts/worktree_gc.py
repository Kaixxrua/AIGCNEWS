#!/usr/bin/env python3
"""Safely reclaim completed public and explicitly preserved private worktrees."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = "aigcnews.worktree-gc-authorization.v1"
SESSION_PREFIX = "refs/heads/session/"
PRIVATE_PREFIXES = ("refs/heads/session/", "refs/heads/codex/")


class CleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch_ref: str | None
    locked: bool
    prunable: bool

    @property
    def branch(self) -> str | None:
        return self.branch_ref.removeprefix("refs/heads/") if self.branch_ref else None


@dataclass(frozen=True)
class Decision:
    path: str
    branch: str | None
    head: str
    action: str
    reason: str


def git_env() -> dict[str, str]:
    blocked = {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_QUARANTINE_PATH",
        "GIT_NAMESPACE",
    }
    return {key: value for key, value in os.environ.items() if key not in blocked}


def run(
    command: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=git_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if check and completed.returncode:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or str(completed.returncode)
        )
        raise CleanupError(f"{' '.join(command)} failed: {detail}")
    return completed


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], repo, check=check)


def parse_worktrees(repo: Path) -> list[Worktree]:
    raw = git(repo, "worktree", "list", "--porcelain").stdout
    entries: list[Worktree] = []
    current: dict[str, str] = {}
    flags: set[str] = set()
    for line in (*raw.splitlines(), ""):
        if line:
            key, separator, value = line.partition(" ")
            if separator:
                current[key] = value
            else:
                flags.add(key)
            continue
        if current:
            entries.append(
                Worktree(
                    path=Path(current["worktree"]).resolve(),
                    head=current.get("HEAD", ""),
                    branch_ref=current.get("branch"),
                    locked="locked" in flags,
                    prunable="prunable" in current or "prunable" in flags,
                )
            )
        current = {}
        flags = set()
    return entries


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def status_is_clean(path: Path) -> bool:
    return not git(
        path, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.strip()


def patch_is_in_main(repo: Path, head: str) -> bool:
    ancestor = git(
        repo, "merge-base", "--is-ancestor", head, "origin/main", check=False
    )
    if ancestor.returncode == 0:
        return True
    cherry = git(repo, "cherry", "origin/main", head, check=False)
    if cherry.returncode:
        return False
    lines = [line for line in cherry.stdout.splitlines() if line]
    return bool(lines) and all(line.startswith("- ") for line in lines)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authorization_name(path: Path) -> str:
    return hashlib.sha256(os.fsencode(str(path.resolve()))).hexdigest() + ".json"


def authorization_path(directory: Path, worktree: Path) -> Path:
    return directory / authorization_name(worktree)


def process_uses(path: Path) -> str | None:
    uid = os.getuid()
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return "process inspection is unavailable"
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
        except OSError:
            continue
        links = [proc / "cwd", proc / "root", proc / "exe"]
        try:
            links.extend((proc / "fd").iterdir())
        except OSError:
            pass
        for link in links:
            try:
                target = Path(os.readlink(link))
            except OSError:
                continue
            if not target.is_absolute():
                continue
            target_text = str(target).removesuffix(" (deleted)")
            try:
                resolved = Path(target_text).resolve(strict=False)
            except OSError:
                continue
            if resolved == path or path in resolved.parents:
                return proc.name
    return None


def last_activity(worktree: Worktree) -> float:
    candidates = [worktree.path, worktree.path / ".git"]
    try:
        git_dir = Path(
            git(worktree.path, "rev-parse", "--absolute-git-dir").stdout.strip()
        )
        # `git status` may refresh the index stat cache, so index mtime is not
        # a user-activity signal and would keep every scanned worktree alive.
        candidates.append(git_dir / "HEAD")
    except CleanupError:
        pass
    mtimes = []
    for candidate in candidates:
        try:
            mtimes.append(candidate.stat().st_mtime)
        except OSError:
            pass
    return max(mtimes, default=time.time())


def load_authorization(directory: Path, worktree: Worktree) -> dict[str, object]:
    path = authorization_path(directory, worktree.path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanupError(
            f"private cleanup authorization is unavailable: {exc}"
        ) from None
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise CleanupError("private cleanup authorization has an unsupported schema")
    if document.get("worktree") != str(worktree.path):
        raise CleanupError("private cleanup authorization path mismatch")
    if (
        document.get("head") != worktree.head
        or document.get("branch") != worktree.branch
    ):
        raise CleanupError("private cleanup authorization revision mismatch")
    snapshot = Path(str(document.get("preserved_release_root", ""))).resolve()
    if ".private-releases" not in snapshot.parts or worktree.path == snapshot:
        raise CleanupError(
            "private cleanup authorization lacks an external release snapshot"
        )
    descriptor = snapshot / "aigcnews-private-release.json"
    expected = document.get("descriptor_sha256")
    if (
        not descriptor.is_file()
        or descriptor.is_symlink()
        or sha256(descriptor) != expected
    ):
        raise CleanupError("preserved private release descriptor mismatch")
    return document


def remote_preserves_private_head(repo: Path, worktree: Worktree) -> bool:
    if not worktree.branch:
        return False
    result = git(repo, "ls-remote", "--heads", "origin", worktree.branch, check=False)
    if result.returncode:
        return False
    return any(
        line.split()[0] == worktree.head
        for line in result.stdout.splitlines()
        if line.split()
    )


def evaluate(
    repo: Path,
    managed_root: Path,
    worktree: Worktree,
    *,
    private_authorizations: Path | None,
    grace_seconds: float,
    now: float,
    all_worktrees: list[Worktree],
) -> Decision:
    branch = worktree.branch
    skipped = lambda reason: Decision(
        str(worktree.path), branch, worktree.head, "skip", reason
    )
    if not is_within(worktree.path, managed_root):
        return skipped("outside managed root")
    if worktree.locked:
        return skipped("git worktree is locked")
    if worktree.prunable or not worktree.path.is_dir():
        return skipped("worktree path is unavailable")
    if private_authorizations is None:
        if not worktree.branch_ref or not worktree.branch_ref.startswith(
            SESSION_PREFIX
        ):
            return skipped("not a managed session branch")
        if not patch_is_in_main(repo, worktree.head):
            return skipped("session changes are not proven present in origin/main")
    else:
        if not worktree.branch_ref or not worktree.branch_ref.startswith(
            PRIVATE_PREFIXES
        ):
            return skipped("not a managed private branch")
        try:
            authorization = load_authorization(private_authorizations, worktree)
        except CleanupError as exc:
            return skipped(str(exc))
        if not remote_preserves_private_head(repo, worktree):
            return skipped("private branch head is not preserved on origin")
        authorized_at = authorization.get("authorized_at")
        if (
            not isinstance(authorized_at, int | float)
            or now - authorized_at < grace_seconds
        ):
            return skipped("private cleanup authorization is inside the grace period")
    if not status_is_clean(worktree.path):
        return skipped("tracked or untracked changes remain")
    nested = [
        item.path
        for item in all_worktrees
        if item.path != worktree.path and is_within(item.path, worktree.path)
    ]
    if nested:
        return skipped(f"contains registered nested worktree {nested[0]}")
    pid = process_uses(worktree.path)
    if pid:
        return skipped(f"used by process {pid}")
    if private_authorizations is None and now - last_activity(worktree) < grace_seconds:
        return skipped("worktree activity is inside the grace period")
    return Decision(
        str(worktree.path),
        branch,
        worktree.head,
        "remove",
        "completion proven and safe",
    )


def collect(
    repo: Path,
    managed_root: Path,
    *,
    private_authorizations: Path | None,
    grace_hours: float,
    apply: bool,
) -> list[Decision]:
    repo = repo.resolve()
    managed_root = managed_root.resolve()
    if not repo.is_dir() or not managed_root.is_dir():
        raise CleanupError("repository or managed root is unavailable")
    if private_authorizations is None:
        git(
            repo,
            "fetch",
            "--quiet",
            "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
    entries = parse_worktrees(repo)
    now = time.time()
    decisions = [
        evaluate(
            repo,
            managed_root,
            item,
            private_authorizations=private_authorizations,
            grace_seconds=grace_hours * 3600,
            now=now,
            all_worktrees=entries,
        )
        for item in sorted(
            entries, key=lambda value: len(value.path.parts), reverse=True
        )
    ]
    if not apply:
        return decisions
    applied: list[Decision] = []
    for decision in decisions:
        if decision.action != "remove":
            applied.append(decision)
            continue
        result = git(repo, "worktree", "remove", decision.path, check=False)
        if result.returncode:
            detail = (
                result.stderr.strip() or result.stdout.strip() or str(result.returncode)
            )
            applied.append(
                Decision(
                    decision.path,
                    decision.branch,
                    decision.head,
                    "skip",
                    f"git refused removal: {detail}",
                )
            )
            continue
        if private_authorizations is not None:
            authorization_path(private_authorizations, Path(decision.path)).unlink(
                missing_ok=True
            )
        applied.append(
            Decision(
                decision.path,
                decision.branch,
                decision.head,
                "removed",
                decision.reason,
            )
        )
    git(repo, "worktree", "prune", "--expire=now")
    return applied


def authorize_private(
    repo: Path, worktree_path: Path, snapshot: Path, directory: Path
) -> Path:
    repo = repo.resolve()
    worktree_path = worktree_path.resolve()
    snapshot = snapshot.resolve()
    matches = [item for item in parse_worktrees(repo) if item.path == worktree_path]
    if len(matches) != 1:
        raise CleanupError("private worktree is not uniquely registered")
    worktree = matches[0]
    if not worktree.branch_ref or not worktree.branch_ref.startswith(PRIVATE_PREFIXES):
        raise CleanupError("private worktree is not on a managed branch")
    if not status_is_clean(worktree.path):
        raise CleanupError("private worktree still has tracked or untracked changes")
    if process_uses(worktree.path):
        raise CleanupError("private worktree is still used by a process")
    if not remote_preserves_private_head(repo, worktree):
        raise CleanupError("private worktree head is not preserved on origin")
    descriptor = snapshot / "aigcnews-private-release.json"
    if not descriptor.is_file() or descriptor.is_symlink():
        raise CleanupError("preserved release descriptor is unavailable")
    snapshot_head = git(snapshot, "rev-parse", "HEAD", check=False)
    if snapshot_head.returncode or snapshot_head.stdout.strip() != worktree.head:
        raise CleanupError(
            "preserved release snapshot does not retain the private worktree head"
        )
    document = {
        "schema": SCHEMA,
        "worktree": str(worktree.path),
        "head": worktree.head,
        "branch": worktree.branch,
        "preserved_release_root": str(snapshot),
        "descriptor_sha256": sha256(descriptor),
        "authorized_at": int(time.time()),
    }
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = authorization_path(directory, worktree.path)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target


def emit(decisions: list[Decision]) -> None:
    summary = {
        "removed": sum(item.action == "removed" for item in decisions),
        "eligible": sum(item.action == "remove" for item in decisions),
        "skipped": sum(item.action == "skip" for item in decisions),
        "decisions": [asdict(item) for item in decisions if item.action != "skip"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--repo", type=Path, required=True)
    collect_parser.add_argument("--managed-root", type=Path, required=True)
    collect_parser.add_argument("--private-authorizations", type=Path)
    collect_parser.add_argument("--grace-hours", type=float, default=24)
    collect_parser.add_argument("--apply", action="store_true")
    authorize_parser = subparsers.add_parser("authorize-private")
    authorize_parser.add_argument("--repo", type=Path, required=True)
    authorize_parser.add_argument("--worktree", type=Path, required=True)
    authorize_parser.add_argument("--preserved-release-root", type=Path, required=True)
    authorize_parser.add_argument("--authorization-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "authorize-private":
            target = authorize_private(
                args.repo,
                args.worktree,
                args.preserved_release_root,
                args.authorization_dir,
            )
            print(json.dumps({"authorized": str(target)}, ensure_ascii=False))
            return 0
        decisions = collect(
            args.repo,
            args.managed_root,
            private_authorizations=args.private_authorizations,
            grace_hours=args.grace_hours,
            apply=args.apply,
        )
        emit(decisions)
        return 0
    except CleanupError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
