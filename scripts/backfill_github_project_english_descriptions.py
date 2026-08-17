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
from backend.app.repositories.application_repository_context import (  # noqa: E402
    configure_application_repositories,
)
from backend.app.repositories.application_repository_factory import (  # noqa: E402
    create_application_repositories,
)
from backend.app.services.ingestion.github_project_enricher import GitHubProjectEnricher  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill model-authored English descriptions for enriched GitHub projects"
    )
    parser.add_argument("--after-repo-id", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument(
        "--all",
        action="store_true",
        help="循环翻页直到无候选（每页 limit 条，逐页输出进度）",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repositories = create_application_repositories(postgres=postgres_database)
    configure_application_repositories(repositories)
    enricher = GitHubProjectEnricher(repositories.github_enrichment)

    totals: dict[str, object] = {
        "status": "dry_run" if args.dry_run else "success",
        "pages": 0,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
    }
    after = args.after_repo_id
    while True:
        page = enricher.backfill_english_descriptions(
            after_repo_id=after,
            limit=args.limit,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
        )
        totals["pages"] = int(totals["pages"]) + 1
        for key in ("processed", "succeeded", "failed"):
            totals[key] = int(totals[key]) + int(page.get(key) or 0)
        print(json.dumps({"page": totals["pages"], **page}, ensure_ascii=False), flush=True)
        if not args.all or not page.get("has_more") or int(page.get("processed") or 0) == 0:
            if int(page.get("failed") or 0) > 0:
                totals["status"] = "partial"
            break
        after = str(page.get("next_cursor") or after)
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    postgres_database.close()
    return 0 if totals["status"] in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
