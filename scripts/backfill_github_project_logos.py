#!/usr/bin/env python3
"""Resume bounded logo collection for historical and newly discovered projects."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RepairQueue:
    """One fixed pass: failed hot projects cannot starve the rest of the catalog."""
    def __init__(self, repository, rows, report=None):
        self.repository = repository
        self.rows = {row["repo_id"]: row for row in rows}
        self.report = report

    def pending(self, limit):
        from itertools import islice
        return list(islice(self.rows.values(), limit))

    def save(self, repo_id, result):
        self.repository.save(repo_id, result)
        self.rows.pop(repo_id)
        if self.report:
            record = {key: value for key, value in result.items() if key != "content"}
            self.report.write(json.dumps({"repo_id": repo_id, **record}) + "\n")
            self.report.flush()


def main() -> None:
    from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository
    from backend.app.services.ingestion.github_project_logos import refresh_project_logos

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Maximum projects; 0 drains the due queue")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="Schedule all existing logos once, preserving cached images")
    parser.add_argument("--repair", action="store_true", help="Retry missing and default images now, preserving good artwork")
    parser.add_argument("--report", type=Path, help="Write per-project repair outcomes to a new JSONL file")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 33))
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.all and args.repair:
        parser.error("--all and --repair are mutually exclusive")
    repository = PostgresGitHubLogoRepository()
    targets = repository.repair_targets() if args.repair else None
    if args.dry_run:
        print(json.dumps({"repair_targets": len(targets)} if targets is not None else
                         {"due_sample": len(repository.pending(min(args.limit or 1000, 1000)))}))
        return
    if args.all:
        print(json.dumps({"rescheduled": repository.enqueue_all()}), flush=True)
    elif targets is not None:
        report = args.report.open("x") if args.report else None
        repository = RepairQueue(repository, targets, report)
        print(json.dumps({"repair_targets": len(targets)}), flush=True)
    remaining = args.limit
    while True:
        count = remaining if args.limit else 0
        result = refresh_project_logos(repository, limit=count, interval=0.1, workers=args.workers)
        print(json.dumps(result), flush=True)
        remaining -= result["selected"]
        if not result["selected"] or (args.limit and remaining <= 0):
            break


if __name__ == "__main__":
    main()
