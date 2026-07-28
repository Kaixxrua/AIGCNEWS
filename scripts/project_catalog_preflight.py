#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import settings  # noqa: E402
from backend.app.core.database import mysql_database  # noqa: E402
from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.services.project_catalog_consistency import (  # noqa: E402
    ProjectCatalogConsistencyService,
)
from backend.app.services.project_catalog_evidence import (  # noqa: E402
    build_project_catalog_evidence,
    sanitize_evidence_input,
    write_project_catalog_evidence,
)
from backend.app.services.project_catalog_sequence import (  # noqa: E402
    ProjectCatalogSequenceService,
)
from backend.app.services.project_catalog_sync import (  # noqa: E402
    ProjectCatalogSyncWorker,
)
from backend.app.services.project_catalog_transfer import (  # noqa: E402
    source_identity_sha256,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect project-catalog cutover evidence without switching backends."
    )
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--target-schema", required=True)
    parser.add_argument("--barrier-id", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--validity-seconds", type=int, default=1800)
    parser.add_argument(
        "--image-digest",
        help="immutable backend image reference or sha256 digest (required for v2)",
    )
    parser.add_argument(
        "--topology-file",
        help="deployed topology file hashed locally (required for v2)",
    )
    parser.add_argument("--shadow-evidence", help="versioned shadow evidence (v2)")
    parser.add_argument("--smoke-evidence", required=True)
    parser.add_argument("--rollback-evidence", help="versioned rollback evidence (v2)")
    return parser


def _revision(value: str) -> str:
    if value.strip():
        return value.strip()
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _json_object(path: str, *, kind: str) -> dict[str, object]:
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"{kind} evidence must be an object")
    return result


def _legacy_smoke_evidence(path: str, *, revision: str) -> dict[str, object]:
    result = _json_object(path, kind="smoke")
    if result.get("revision") != revision:
        raise ValueError("smoke evidence revision does not match")
    if not str(result.get("suite") or "").strip():
        raise ValueError("smoke evidence suite is required")
    if result.get("status") not in {"passed", "failed"}:
        raise ValueError("smoke evidence status is invalid")
    supplied_digest = str(result.get("result_sha256") or "").strip().lower()
    digest_payload = dict(result)
    digest_payload.pop("result_sha256", None)
    expected_digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if supplied_digest != expected_digest:
        raise ValueError("smoke evidence digest does not match")
    return result


def _topology_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _versioned_evidence(
    path: str,
    *,
    kind: str,
    release_id: str,
    revision: str,
    image_digest: str,
    topology_sha256: str,
) -> dict[str, object]:
    return sanitize_evidence_input(
        _json_object(path, kind=kind),
        kind=kind,
        release_id=release_id,
        revision=revision,
        image_sha256=image_digest,
        topology_sha256=topology_sha256,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        revision = _revision(args.revision)
        extended_values = (
            args.image_digest,
            args.topology_file,
            args.shadow_evidence,
            args.rollback_evidence,
        )
        extended = any(value is not None for value in extended_values)
        if extended and not all(value is not None for value in extended_values):
            raise ValueError(
                "image, topology, shadow, and rollback inputs are required together"
            )
        topology_sha256 = _topology_sha256(args.topology_file) if extended else None
        if extended:
            evidence_args = {
                "release_id": args.release_id,
                "revision": revision,
                "image_digest": args.image_digest,
                "topology_sha256": topology_sha256,
            }
            shadow = _versioned_evidence(
                args.shadow_evidence, kind="shadow", **evidence_args
            )
            smoke = _versioned_evidence(
                args.smoke_evidence, kind="smoke", **evidence_args
            )
            rollback = _versioned_evidence(
                args.rollback_evidence, kind="rollback", **evidence_args
            )
        else:
            shadow = rollback = None
            smoke = _legacy_smoke_evidence(args.smoke_evidence, revision=revision)
        worker = ProjectCatalogSyncWorker()
        barrier = worker.prove_barrier(args.barrier_id)
        consistency = ProjectCatalogConsistencyService().verify(
            target_database=args.target_database,
            target_schema=args.target_schema,
        )
        sequences = ProjectCatalogSequenceService().inspect(
            target_database=args.target_database,
            target_schema=args.target_schema,
        )
        artifact = build_project_catalog_evidence(
            release_id=args.release_id,
            revision=revision,
            target_database=args.target_database,
            target_schema=args.target_schema,
            consistency=consistency,
            barrier=barrier,
            sequences=sequences,
            smoke=smoke,
            expected_backend="postgres",
            capture_enabled=bool(settings.project_catalog_outbox_capture_enabled),
            sync_enabled=bool(settings.project_catalog_sync_worker_enabled),
            validity_seconds=args.validity_seconds,
            source_identity_sha256=source_identity_sha256(settings),
            image_digest=args.image_digest if extended else None,
            topology_sha256=topology_sha256,
            shadow=shadow,
            rollback=rollback,
        )
        write_project_catalog_evidence(args.output, artifact)
        print(
            json.dumps(
                {
                    "status": "ready" if artifact["ready"] else "not_ready",
                    "artifact_sha256": artifact["artifact_sha256"],
                    "output": str(Path(args.output)),
                    "failed_gates": artifact["failed_gates"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if artifact["ready"] else 1
    except Exception as error:
        print(
            json.dumps(
                {"status": "failed", "error_class": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        mysql_database.close()
        postgres_database.close()


if __name__ == "__main__":
    raise SystemExit(main())
