"""Offline release-candidate manifest verification."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "aigcnews.release-candidate.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_REQUIRED = ("source_sha", "candidate_id", "ci_run_id", "dependency_lock_hashes", "migration_set_digest", "migration_latest_version", "image_digests", "frontend_artifact_digest", "risk", "actor", "evidence_digests", "created_at", "schema_version")


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _fail(message: str) -> None:
    raise ValueError(message)


def validate_manifest(manifest: dict[str, Any]) -> None:
    if set(manifest) != set(_REQUIRED):
        _fail("manifest fields must exactly match the release-candidate contract")
    if manifest["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported schema_version")
    if not isinstance(manifest["source_sha"], str) or not _SHA40.fullmatch(manifest["source_sha"]):
        _fail("source_sha must be a lowercase 40-character SHA")
    for field in ("migration_set_digest", "frontend_artifact_digest"):
        if not isinstance(manifest[field], str) or not _SHA64.fullmatch(manifest[field]):
            _fail(f"{field} must be a lowercase SHA-256 digest")
    if manifest["risk"] not in {"green", "yellow", "red"}:
        _fail("risk must be green, yellow, or red")
    for field in ("candidate_id", "ci_run_id", "migration_latest_version", "actor", "created_at"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            _fail(f"{field} must be non-empty")
    locks = manifest["dependency_lock_hashes"]
    evidence = manifest["evidence_digests"]
    for field, values in (("dependency_lock_hashes", locks), ("evidence_digests", evidence)):
        if not isinstance(values, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not _SHA64.fullmatch(v) for k, v in values.items()):
            _fail(f"{field} must map names to SHA-256 digests")
    if not isinstance(manifest["image_digests"], list) or any(not isinstance(item, str) or not _IMAGE.fullmatch(item) for item in manifest["image_digests"]):
        _fail("image_digests must contain immutable repository@sha256 references")


def verify_candidate(*, manifest: dict[str, Any], root: Path, protected_sha: str, dirty: bool | None = None, expected_images: list[str] | None = None, expected_frontend_digest: str | None = None) -> None:
    validate_manifest(manifest)
    if not _SHA40.fullmatch(protected_sha) or manifest["source_sha"] != protected_sha:
        _fail("candidate source_sha must exactly match protected-main SHA")
    if dirty is None:
        dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=all"))
    if dirty:
        _fail("source tree is dirty")
    images = manifest["image_digests"]
    if expected_images is not None and images != expected_images:
        _fail("image digests do not exactly match the verified build")
    if expected_frontend_digest is not None and manifest["frontend_artifact_digest"] != expected_frontend_digest:
        _fail("frontend artifact digest does not match the verified build")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--protected-sha", required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify_candidate(manifest=manifest, root=args.root, protected_sha=args.protected_sha, dirty=False if args.allow_dirty else None)
    print("candidate verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
