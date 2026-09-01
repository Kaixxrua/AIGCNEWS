"""Build and validate an offline release-candidate manifest.

The command only reads local metadata and writes a JSON manifest; it never
pushes, deploys, contacts a registry, or mutates git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "aigcnews.release-candidate.v1"
_HEX64 = set("0123456789abcdef")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def build_manifest(*, source_sha: str, candidate_id: str, ci_run_id: str,
                   dependency_lock_hashes: dict[str, str], migration_set_digest: str,
                   migration_latest_version: str, image_digests: list[str],
                   frontend_artifact_digest: str, risk: str, actor: str,
                   evidence_digests: dict[str, str], created_at: str | None = None) -> dict[str, Any]:
    return {
        "source_sha": source_sha,
        "candidate_id": candidate_id,
        "ci_run_id": ci_run_id,
        "dependency_lock_hashes": dependency_lock_hashes,
        "migration_set_digest": migration_set_digest,
        "migration_latest_version": migration_latest_version,
        "image_digests": image_digests,
        "frontend_artifact_digest": frontend_artifact_digest,
        "risk": risk,
        "actor": actor,
        "evidence_digests": evidence_digests,
        "created_at": created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "schema_version": SCHEMA_VERSION,
    }


def _parse_hashes(values: list[str], label: str) -> dict[str, str]:
    result = {}
    for value in values:
        try:
            name, digest = value.split("=", 1)
        except ValueError as exc:
            raise ValueError(f"{label} must use NAME=SHA256") from exc
        if not name or len(digest) != 64 or any(char not in _HEX64 for char in digest):
            raise ValueError(f"{label} contains an invalid SHA-256 digest")
        result[name] = digest
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", default=None)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--ci-run-id", required=True)
    parser.add_argument("--lock", action="append", default=[], metavar="NAME=SHA256")
    parser.add_argument("--migration-set-digest", required=True)
    parser.add_argument("--migration-latest-version", required=True)
    parser.add_argument("--image-digest", action="append", default=[])
    parser.add_argument("--frontend-artifact-digest", required=True)
    parser.add_argument("--risk", choices=("green", "yellow", "red"), required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--evidence", action="append", default=[], metavar="NAME=SHA256")
    args = parser.parse_args(argv)
    source_sha = args.source_sha or git_output(args.root, "rev-parse", "HEAD")
    manifest = build_manifest(
        source_sha=source_sha, candidate_id=args.candidate_id, ci_run_id=args.ci_run_id,
        dependency_lock_hashes=_parse_hashes(args.lock, "--lock"),
        migration_set_digest=args.migration_set_digest,
        migration_latest_version=args.migration_latest_version,
        image_digests=args.image_digest,
        frontend_artifact_digest=args.frontend_artifact_digest,
        risk=args.risk, actor=args.actor,
        evidence_digests=_parse_hashes(args.evidence, "--evidence"),
    )
    from verify_candidate import validate_manifest
    validate_manifest(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
