#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.postgres_database import postgres_database  # noqa: E402
from backend.app.repositories.application_repository_factory import (  # noqa: E402
    create_application_repositories,
)
from backend.app.services.indexing.github_project_semantic_indexer import (  # noqa: E402
    sync_github_project_semantic_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the GitHub project semantic index")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-stars", type=int, default=500)
    parser.add_argument("--after-repo-id", default="")
    parser.add_argument("--profiles-only", action="store_true")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repositories = create_application_repositories(postgres=postgres_database)
    try:
        result = sync_github_project_semantic_index(
            db=repositories.github_semantic_sources,
            force=True,
            limit=args.limit,
            min_stars=args.min_stars,
            after_repo_id=args.after_repo_id,
            fetch_readme=not args.profiles_only,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
        )
    finally:
        postgres_database.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
