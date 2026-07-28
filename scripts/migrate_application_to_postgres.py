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
from backend.app.services.application_transfer_service import (  # noqa: E402
    ApplicationTransferService,
)
from backend.app.services.project_catalog_transfer import DEFAULT_BATCH_SIZE  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transfer application tables from authoritative MySQL to PostgreSQL."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_target_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--target-database", required=True)
        command.add_argument("--target-schema", required=True)
        command.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    plan = subparsers.add_parser("plan", help="Inspect an application transfer without writes.")
    plan.add_argument("--job-id", required=True)
    add_target_arguments(plan)
    plan.add_argument("--source-timezone", default="UTC")

    load = subparsers.add_parser(
        "load", help="Load application tables with durable resume state."
    )
    load.add_argument("--job-id", required=True)
    add_target_arguments(load)
    load.add_argument("--source-timezone", default="UTC")
    load.add_argument("--apply", action="store_true")
    load.add_argument("--authorize-production", action="store_true")

    status = subparsers.add_parser("status", help="Inspect durable transfer state.")
    status.add_argument("--job-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = ApplicationTransferService()
    try:
        if args.command == "plan":
            result = service.plan_application(
                job_id=args.job_id,
                batch_size=args.batch_size,
                target_database=args.target_database,
                target_schema=args.target_schema,
                source_timezone=args.source_timezone,
            )
        elif args.command == "load":
            result = service.load_application(
                job_id=args.job_id,
                batch_size=args.batch_size,
                target_database=args.target_database,
                target_schema=args.target_schema,
                source_timezone=args.source_timezone,
                apply=args.apply,
                production_authorized=args.authorize_production,
            )
        else:
            result = service.status(job_id=args.job_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("status") != "failed" else 1
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
