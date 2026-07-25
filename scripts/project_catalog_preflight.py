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
    parser.add_argument("--smoke-evidence", required=True)
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


def _smoke_evidence(path: str, *, revision: str) -> dict[str, object]:
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("smoke evidence must be an object")
    if result.get("revision") != revision:
        raise ValueError("smoke evidence revision does not match")
    if not str(result.get("suite") or "").strip():
        raise ValueError("smoke evidence suite is required")
    if result.get("status") not in {"passed", "failed"}:
        raise ValueError("smoke evidence status is invalid")
    supplied_digest = str(result.get("result_sha256") or "").strip().lower()
    if len(supplied_digest) != 64:
        raise ValueError("smoke evidence digest is invalid")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        revision = _revision(args.revision)
        smoke = _smoke_evidence(args.smoke_evidence, revision=revision)
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
