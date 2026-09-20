#!/usr/bin/env python3
"""Resume bounded logo collection for historical and newly discovered projects."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository
    from backend.app.services.ingestion.github_project_logos import refresh_project_logos

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Maximum projects; 0 drains the due queue")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="Schedule all existing logos once, preserving cached images")
    parser.add_argument("--repair", action="store_true", help="Retry missing and default images now, preserving good artwork")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    repository = PostgresGitHubLogoRepository()
    if args.dry_run:
        print(json.dumps({"due_sample": len(repository.pending(min(args.limit or 1000, 1000)))}))
        return
    if args.all:
        print(json.dumps({"rescheduled": repository.enqueue_all()}), flush=True)
    elif args.repair:
        print(json.dumps({"rescheduled": repository.enqueue_missing()}), flush=True)
    remaining = args.limit
    while True:
        count = min(remaining, 100) if args.limit else 100
        result = refresh_project_logos(repository, limit=count, interval=0.1)
        print(json.dumps(result), flush=True)
        remaining -= result["selected"]
        if not result["selected"] or (args.limit and remaining <= 0):
            break


if __name__ == "__main__":
    main()
