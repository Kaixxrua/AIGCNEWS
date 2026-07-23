from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.postgres_database import postgres_database
from backend.app.core.postgres_migrations import PostgresMigrationRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or apply PostgreSQL schema migrations.")
    parser.add_argument("command", choices=("status", "apply"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = PostgresMigrationRunner()
    try:
        if args.command == "status":
            statuses = runner.status()
            if not statuses:
                print("No PostgreSQL migrations found.")
            for status in statuses:
                state = "applied" if status.applied else "pending"
                print(f"{status.version:04d} {state} {status.filename}")
        else:
            applied = runner.apply()
            if applied:
                for migration in applied:
                    print(f"Applied {migration.version:04d} {migration.filename}")
            else:
                print("PostgreSQL schema is up to date.")
        return 0
    except Exception:
        print("PostgreSQL migration failed; inspect database logs for details.", file=sys.stderr)
        return 1
    finally:
        postgres_database.close()


if __name__ == "__main__":
    raise SystemExit(main())
