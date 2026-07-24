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
from backend.app.core.mysql_migrations import MySQLMigrationRunner  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply versioned MySQL project catalog migrations."
    )
    parser.add_argument("command", choices=("status", "apply"))
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = MySQLMigrationRunner()
    try:
        if args.command == "apply" and args.apply:
            applied = runner.apply()
            result = {
                "status": "applied",
                "versions": [migration.version for migration in applied],
            }
        else:
            statuses = runner.status()
            result = {
                "status": "dry_run" if args.command == "apply" else "ok",
                "migrations": [
                    {
                        "version": status.version,
                        "filename": status.filename,
                        "applied": status.applied,
                    }
                    for status in statuses
                ],
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
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
