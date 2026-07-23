#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.repositories.mysql_repo import MySQLRepository  # noqa: E402
from backend.app.repositories.project_vector_repo import ProjectVectorRepository  # noqa: E402


def list_semantic_aliases(db: MySQLRepository, *, min_stars: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            c.repo_id AS alias_repo_id,
            c.full_name AS alias_full_name,
            ga.canonical_repo_id,
            canonical.full_name AS canonical_full_name,
            CASE WHEN canonical.repo_id IS NULL THEN 0 ELSE 1 END AS canonical_candidate_exists,
            CASE WHEN canonical_enrichment.status = 'succeeded' THEN 1 ELSE 0 END AS canonical_enrichment_ready,
            COALESCE(alias_source.index_status, '') AS alias_index_status,
            COALESCE(canonical_source.index_status, '') AS canonical_index_status
        FROM github_repo_candidates c
        JOIN github_repo_aliases ga
          ON ga.alias_repo_id = c.repo_id AND ga.canonical_repo_id <> c.repo_id
        JOIN github_repo_enrichments alias_enrichment
          ON alias_enrichment.repo_id = c.repo_id AND alias_enrichment.status = 'succeeded'
        LEFT JOIN github_repo_candidates canonical ON canonical.repo_id = ga.canonical_repo_id
        LEFT JOIN github_repo_enrichments canonical_enrichment
          ON canonical_enrichment.repo_id = ga.canonical_repo_id
        LEFT JOIN github_project_semantic_sources alias_source
          ON alias_source.repo_id = c.repo_id
        LEFT JOIN github_project_semantic_sources canonical_source
          ON canonical_source.repo_id = ga.canonical_repo_id
        WHERE COALESCE(c.stars, 0) >= %s
        ORDER BY c.repo_id
    """
    conn = db._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (min_stars,))
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit stale GitHub alias identities in the project semantic index"
    )
    parser.add_argument("--min-stars", type=int, default=500)
    parser.add_argument("--delete-alias-vectors", action="store_true")
    args = parser.parse_args()

    db = MySQLRepository()
    vectors = ProjectVectorRepository()
    try:
        aliases = list_semantic_aliases(db, min_stars=args.min_stars)
        blockers = 0
        deleted = 0
        for item in aliases:
            alias_id = str(item["alias_repo_id"])
            canonical_id = str(item["canonical_repo_id"])
            item["alias_vector_chunks"] = vectors.count_project_chunks(alias_id)
            item["canonical_vector_chunks"] = vectors.count_project_chunks(canonical_id)
            item["blocked"] = not bool(item["canonical_candidate_exists"] and item["canonical_enrichment_ready"])
            blockers += int(item["blocked"])
            if args.delete_alias_vectors and not item["blocked"]:
                vectors.delete_project(alias_id)
                item["deleted_alias_vector_chunks"] = item["alias_vector_chunks"]
                deleted += item["alias_vector_chunks"]

        print(
            json.dumps(
                {
                    "status": "blocked" if blockers else "success",
                    "dry_run": not args.delete_alias_vectors,
                    "collection": vectors.collection_name,
                    "aliases": aliases,
                    "summary": {
                        "aliases": len(aliases),
                        "blockers": blockers,
                        "alias_vector_chunks": sum(int(item["alias_vector_chunks"]) for item in aliases),
                        "deleted_alias_vector_chunks": deleted,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if blockers else 0
    finally:
        vectors.close()


if __name__ == "__main__":
    raise SystemExit(main())
