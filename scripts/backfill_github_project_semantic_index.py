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
    parser.add_argument(
        "--max-batches",
        type=int,
        default=1,
        help="沿 repo_id 游标连续跑的批数；0 表示直到没有待索引项目",
    )
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="跳过开跑前的台账↔Milvus 对账（默认先把向量已丢失的项目退回待索引）",
    )
    args = parser.parse_args()
    repositories = create_application_repositories(postgres=postgres_database)
    results: list[dict] = []
    cursor = args.after_repo_id
    try:
        while not args.max_batches or len(results) < args.max_batches:
            result = sync_github_project_semantic_index(
                db=repositories.github_semantic_sources,
                force=True,
                limit=args.limit,
                min_stars=args.min_stars,
                after_repo_id=cursor,
                fetch_readme=not args.profiles_only,
                concurrency=args.concurrency,
                dry_run=args.dry_run,
                reconcile=not args.no_reconcile and not results,
            )
            results.append(result)
            if args.max_batches != 1:
                print(json.dumps({"batch": len(results), **result}, ensure_ascii=False), flush=True)
            if result.get("status") not in {"success", "dry_run"} or int(result.get("selected") or 0) < args.limit:
                break
            cursor = str(result.get("last_repo_id") or "")
    finally:
        postgres_database.close()
    if args.max_batches == 1:
        print(json.dumps(results[0], ensure_ascii=False, indent=2))
    else:
        counts: dict[str, int] = {}
        for result in results:
            for status, count in (result.get("counts") or {}).items():
                counts[status] = counts.get(status, 0) + int(count)
        last_repo_id = str(results[-1].get("last_repo_id") or cursor)
        print(json.dumps({"batches": len(results), "counts": counts, "last_repo_id": last_repo_id}, ensure_ascii=False))
    return 0 if all(result.get("status") in {"success", "dry_run"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
