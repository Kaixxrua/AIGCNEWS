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
from backend.app.services.mysql_schema_inventory import (  # noqa: E402
    MySQLSchemaInventoryService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a read-only, secret-safe inventory of the live MySQL schema."
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--estimated-counts",
        action="store_true",
        help="skip exact COUNT(*) queries and retain information_schema estimates only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    try:
        artifact = MySQLSchemaInventoryService().collect(
            exact_counts=not args.estimated_counts
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "ready" if artifact["summary"]["ready_for_schema_design"] else "review_required",
                    "artifact_sha256": artifact["artifact_sha256"],
                    "output": str(output),
                    "table_count": artifact["summary"]["table_count"],
                    "unknown_tables": artifact["summary"]["unknown_tables"],
                },
                sort_keys=True,
            )
        )
        return 0 if artifact["summary"]["ready_for_schema_design"] else 2
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


if __name__ == "__main__":
    raise SystemExit(main())
