#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill bilingual saved-website enrichment")
    parser.add_argument("--after-website-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--no-retry-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = ToolWebsiteEnricher().backfill_bilingual_descriptions(
        after_website_id=args.after_website_id,
        limit=args.limit,
        retry_failed=not args.no_retry_failed,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
