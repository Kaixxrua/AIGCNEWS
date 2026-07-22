#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.indexing.github_project_semantic_indexer import (  # noqa: E402
    sync_github_project_semantic_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the GitHub project semantic index")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-stars", type=int, default=500)
    parser.add_argument("--after-repo-id", default="")
    parser.add_argument("--profiles-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = sync_github_project_semantic_index(
        force=True,
        limit=args.limit,
        min_stars=args.min_stars,
        after_repo_id=args.after_repo_id,
        fetch_readme=not args.profiles_only,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
