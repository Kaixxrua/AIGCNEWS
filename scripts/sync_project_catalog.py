#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.database import mysql_database  # noqa: E402
from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.services.project_catalog_sync import (  # noqa: E402
    ProjectCatalogReconciliationWriter,
    ProjectCatalogSyncWorker,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay MySQL project-catalog outbox events.")
    parser.add_argument(
        "command",
        choices=(
            "status",
            "run-once",
            "capture-barrier",
            "prove-barrier",
            "drain-to-barrier",
        ),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--barrier-id", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--authorize-production", action="store_true")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--lease-seconds", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--source-timezone", default="UTC")
    parser.add_argument("--quiet-window-seconds", type=float, default=0.0)
    parser.add_argument("--producer-freeze", action="store_true")
    parser.add_argument("--quiet-window-started-at", default=None)
    parser.add_argument("--quiet-window-ended-at", default=None)
    parser.add_argument("--release-id", default=None)
    parser.add_argument("--target-database", default=None)
    parser.add_argument("--target-schema", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    writer = ProjectCatalogReconciliationWriter(source_timezone=args.source_timezone)
    worker = ProjectCatalogSyncWorker(
        writer=writer,
        batch_size=args.batch_size,
        lease_seconds=args.lease_seconds,
        max_attempts=args.max_attempts,
    )
    try:
        if args.command == "status":
            result = {"status": "ok", **worker.status()}
        elif args.command == "capture-barrier":
            barrier = worker.capture_barrier(
                release_id=args.release_id,
                target_database=args.target_database,
                target_schema=args.target_schema,
            )
            result = {
                "status": "captured",
                "barrier_id": barrier.id,
                "captured_at": barrier.captured_at,
                "attestation_version": barrier.attestation_version,
                "release_id": barrier.release_id,
                "source_identity_sha256": barrier.source_identity_sha256,
                "target": {
                    "database": barrier.target_database,
                    "schema": barrier.target_schema,
                },
            }
        elif args.command in {"prove-barrier", "drain-to-barrier"}:
            if args.barrier_id is None:
                raise ValueError("--barrier-id is required")
            proof_args = {}
            if args.quiet_window_seconds:
                proof_args["quiet_window_seconds"] = args.quiet_window_seconds
            if args.producer_freeze:
                proof_args["producer_freeze"] = True
            if args.quiet_window_started_at is not None:
                proof_args["quiet_window_started_at"] = args.quiet_window_started_at
            if args.quiet_window_ended_at is not None:
                proof_args["quiet_window_ended_at"] = args.quiet_window_ended_at
            if args.release_id is not None:
                proof_args["release_id"] = args.release_id
            if args.target_database is not None:
                proof_args["target_database"] = args.target_database
            if args.target_schema is not None:
                proof_args["target_schema"] = args.target_schema
            if args.command == "prove-barrier":
                proof = worker.prove_barrier(args.barrier_id, **proof_args)
                result = {
                    "status": "ready" if proof["barrier_proven"] else "not_ready",
                    **proof,
                }
            elif not args.apply:
                result = {
                    "status": "dry_run",
                    **worker.prove_barrier(args.barrier_id, **proof_args),
                }
            else:
                result = worker.drain_to_barrier(
                    args.barrier_id,
                    timeout_seconds=args.timeout_seconds,
                    production_authorized=args.authorize_production,
                )
        elif not args.apply:
            result = {"status": "dry_run", **worker.status()}
        else:
            batch = worker.run_once()
            result = {
                "status": "applied",
                "claimed": batch.claimed,
                "processed": batch.processed,
                "retried": batch.retried,
                "dead": batch.dead,
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") not in {"not_ready", "blocked", "timeout"} else 1
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
