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
from backend.app.services.project_catalog_transfer import DEFAULT_BATCH_SIZE  # noqa: E402
from backend.app.services.table_transfer_reconciliation import (  # noqa: E402
    TableTransferReconciliationService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile a completed MySQL to PostgreSQL application transfer."
    )
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--target-schema", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--source-timezone", default="UTC")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = TableTransferReconciliationService().verify(
            job_id=args.job_id,
            target_database=args.target_database,
            target_schema=args.target_schema,
            batch_size=args.batch_size,
            source_timezone=args.source_timezone,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0 if result["status"] == "match" else 1
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
