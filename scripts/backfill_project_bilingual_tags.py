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
from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill bilingual system project tags")
    parser.add_argument("--source", choices=("github", "website", "all"), default="all")
    parser.add_argument("--after-repo-id", default="")
    parser.add_argument("--after-website-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-stars", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_application_repositories(
        create_application_repositories(postgres=postgres_database)
    )
    result: dict[str, object] = {"status": "dry_run" if args.dry_run else "success"}
    if args.source in {"github", "all"}:
        result["github"] = GitHubProjectEnricher().backfill_bilingual_tags(
            after_repo_id=args.after_repo_id,
            limit=args.limit,
            min_stars=args.min_stars,
            dry_run=args.dry_run,
        )
    if args.source in {"website", "all"}:
        result["website"] = ToolWebsiteEnricher().backfill_bilingual_tags(
            after_website_id=args.after_website_id,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    statuses = [value.get("status") for value in result.values() if isinstance(value, dict)]
    if "partial" in statuses:
        result["status"] = "partial"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    postgres_database.close()
    return 0 if result["status"] in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
