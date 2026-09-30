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
from backend.app.repositories.postgres_document_semantic_source_repository import (  # noqa: E402
    PostgresDocumentSemanticSourceRepository,
)
from backend.app.services.indexing.document_semantic_indexer import (  # noqa: E402
    sync_document_semantic_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the per-document semantic index (idempotent)")
    parser.add_argument("--max-embed", type=int, default=0, help="0 = embed every stale document")
    parser.add_argument("--no-prune", action="store_true", help="keep vectors whose documents were deleted")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = sync_document_semantic_index(
            db=PostgresDocumentSemanticSourceRepository(postgres_database),
            force=True,
            max_embed=args.max_embed,
            prune=not args.no_prune,
            dry_run=args.dry_run,
        )
    finally:
        postgres_database.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
