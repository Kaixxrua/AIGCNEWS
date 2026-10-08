#!/usr/bin/env python3
"""Read-only identity audit; redirect JSON outside the repository for review.

Run in the backend environment. --verify-github resolves suspicious names and
node IDs against GitHub without writing observations or changing any aliases.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.postgres_database import postgres_database


def audit(database, *, since: str) -> dict:
    date.fromisoformat(since)
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute("SELECT COUNT(*) AS count FROM github_repo_candidates")
            count = cursor.fetchone()["count"]
            cursor.execute("""
                SELECT a.alias_repo_id,a.canonical_repo_id,c.repo_id,c.full_name
                FROM github_repo_aliases a JOIN github_repo_candidates c
                  ON LOWER(c.full_name)=LOWER(a.alias_repo_id)
                WHERE c.repo_id<>a.canonical_repo_id ORDER BY a.alias_repo_id
            """)
            name_collisions = list(cursor.fetchall())
            cursor.execute("SELECT alias_repo_id,canonical_repo_id FROM github_repo_aliases WHERE POSITION('/' IN alias_repo_id)>0 ORDER BY alias_repo_id")
            name_aliases = list(cursor.fetchall())
            cursor.execute("""
                WITH identities AS (
                    SELECT canonical_repo_id,alias_repo_id FROM github_repo_aliases
                    UNION SELECT repo_id,repo_id FROM github_repo_candidates
                ) SELECT canonical_repo_id,array_agg(alias_repo_id ORDER BY alias_repo_id) AS nodes
                FROM identities
                WHERE POSITION('/' IN alias_repo_id)=0 AND alias_repo_id !~ '^[0-9]+$'
                GROUP BY canonical_repo_id HAVING COUNT(*)>1 ORDER BY canonical_repo_id
            """)
            node_conflicts = list(cursor.fetchall())
            cursor.execute("""
                SELECT s.repo_id,c.full_name,c.created_at,
                       array_agg(DISTINCT LEFT(s.repo_created_at,10)) AS creation_dates,
                       COUNT(*) AS snapshots
                FROM github_repo_snapshots s JOIN github_repo_candidates c USING(repo_id)
                WHERE s.snapshot_date>=%s AND LENGTH(s.repo_created_at)>=10
                  AND LENGTH(c.created_at)>=10 AND LEFT(s.repo_created_at,10)<>LEFT(c.created_at,10)
                GROUP BY s.repo_id,c.full_name,c.created_at ORDER BY s.repo_id
            """, (since,))
            creation_mismatches = list(cursor.fetchall())
            cursor.execute("""
                WITH changes AS (
                    SELECT repo_id,snapshot_date,stars,
                           LAG(stars) OVER (PARTITION BY repo_id ORDER BY snapshot_date) AS previous_stars
                    FROM github_repo_snapshots WHERE snapshot_date>=%s
                ) SELECT repo_id,COUNT(*) AS drops,MIN(snapshot_date) AS first_drop,
                         MAX(previous_stars-stars) AS largest_drop
                  FROM changes WHERE stars<previous_stars*0.5 AND previous_stars-stars>=500
                  GROUP BY repo_id ORDER BY repo_id
            """, (since,))
            star_discontinuities = list(cursor.fetchall())
            ids = {r["repo_id"] for r in creation_mismatches + star_discontinuities}
            ids.update(r["canonical_repo_id"] for r in node_conflicts + name_collisions)
            ids.update(r["repo_id"] for r in name_collisions)
            ids.update(r["canonical_repo_id"] for r in name_aliases)
            cursor.execute("SELECT * FROM github_repo_candidates WHERE repo_id=ANY(%s) ORDER BY repo_id", (sorted(ids),))
            candidates = list(cursor.fetchall())
            cursor.execute("SELECT * FROM github_repo_aliases WHERE canonical_repo_id=ANY(%s) ORDER BY alias_repo_id", (sorted(ids),))
            aliases = list(cursor.fetchall())
    return dict(candidate_count=count, since=since, name_aliases=name_aliases, name_collisions=name_collisions,
                node_conflicts=node_conflicts, creation_mismatches=creation_mismatches,
                star_discontinuities=star_discontinuities, candidates=candidates, aliases=aliases)


def verify_github(report: dict) -> dict:
    import httpx

    from backend.app.services.ingestion.source_github import _build_headers

    fields = """id databaseId nameWithOwner url description createdAt pushedAt
        stargazerCount forkCount watchers { totalCount } issues(states:OPEN) { totalCount }
        primaryLanguage { name } licenseInfo { spdxId } isArchived"""
    nodes = sorted({row["alias_repo_id"] for row in report["aliases"]
                    if "/" not in row["alias_repo_id"] and not row["alias_repo_id"].isdecimal()}
                   | {row["repo_id"] for row in report["candidates"]
                      if "/" not in row["repo_id"] and not row["repo_id"].isdecimal()})
    names = sorted({row["full_name"] for row in report["candidates"]}
                   | {row["alias_repo_id"] for row in report["name_aliases"]})
    verified = {"nodes": {}, "names": {}, "errors": []}
    with httpx.Client(timeout=40, trust_env=True) as client:
        for start in range(0, len(nodes), 40):
            batch = nodes[start:start + 40]
            response = client.post("https://api.github.com/graphql", headers=_build_headers(), json={
                "query": "query($ids:[ID!]!) { nodes(ids:$ids) { ... on Repository { " + fields + " } } }",
                "variables": {"ids": batch},
            })
            response.raise_for_status()
            result = response.json()
            returned = (result.get("data") or {}).get("nodes")
            if returned is None:
                raise RuntimeError("GitHub did not return node evidence")
            verified["nodes"].update(zip(batch, returned))
            verified["errors"].extend(result.get("errors", []))
        for start in range(0, len(names), 40):
            batch = names[start:start + 40]
            queries = []
            for i, name in enumerate(batch):
                owner, repo = name.split("/", 1)
                queries.append(f"r{i}:repository(owner:{json.dumps(owner)},name:{json.dumps(repo)}) {{ {fields} }}")
            response = client.post("https://api.github.com/graphql", headers=_build_headers(), json={"query": "{" + " ".join(queries) + "}"})
            response.raise_for_status()
            result = response.json()
            data = result.get("data")
            if data is None:
                raise RuntimeError("GitHub did not return repository evidence")
            verified["names"].update({name: data.get(f"r{i}") for i, name in enumerate(batch)})
            verified["errors"].extend(result.get("errors", []))
    return verified


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2000-01-01", type=date.fromisoformat)
    parser.add_argument("--verify-github", action="store_true")
    args = parser.parse_args()
    try:
        report = audit(postgres_database, since=args.since.isoformat())
        if args.verify_github:
            report["github"] = verify_github(report)
        print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
    finally:
        postgres_database.close()


if __name__ == "__main__":
    main()
