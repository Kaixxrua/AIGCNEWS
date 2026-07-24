#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.services.project_catalog_sequence import (  # noqa: E402
    ProjectCatalogSequenceService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or explicitly repair PostgreSQL project catalog sequences."
    )
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--target-schema", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorize-production", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = ProjectCatalogSequenceService().repair(
            target_database=args.target_database,
            target_schema=args.target_schema,
            apply=args.apply,
            production_authorized=args.authorize_production,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "ready" else 1
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
        postgres_database.close()


if __name__ == "__main__":
    raise SystemExit(main())
