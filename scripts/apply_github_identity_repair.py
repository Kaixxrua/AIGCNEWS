#!/usr/bin/env python3
"""Apply a reviewed identity repair manifest atomically, with a durable backup.

The default is a dry run. Each operation names a whitelisted table, its key,
expected preimage (or null for inserts), and changed fields (or null to remove
an archived contaminated row). Changed preimages abort the entire repair.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.postgres_database import postgres_database

KEYS = {
    "github_repo_candidates": ("repo_id",),
    "github_repo_aliases": ("alias_repo_id",),
    "github_repo_snapshots": ("repo_id", "snapshot_date"),
    "github_repo_star_observations": ("repo_id", "observed_at"),
    "github_repo_daily_metrics": ("repo_id", "metric_date"),
    "github_trending_hits": ("repo_id", "period", "observed_date"),
    "github_repo_enrichments": ("repo_id",),
    "github_project_semantic_sources": ("repo_id",),
}


def apply_plan(database, plan: dict, *, apply: bool = False, backup: Path | None = None) -> dict:
    operations = plan["operations"]
    if apply and backup is None:
        raise ValueError("A new backup path is required")
    tables = sorted({op["table"] for op in operations})
    if not set(tables).issubset(KEYS):
        raise ValueError("Unsupported repair table")
    seen = set()
    for op in operations:
        if set(op["key"]) != set(KEYS[op["table"]]):
            raise ValueError("Invalid repair key")
        identity = (op["table"], json.dumps(op["key"], sort_keys=True))
        if identity in seen:
            raise ValueError("Duplicate repair operation")
        seen.add(identity)
        if op["after"] is not None and any(op["after"].get(k, v) != v for k, v in op["key"].items()):
            raise ValueError("Move rows using separate remove and insert operations")

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute("SELECT current_database() AS database,current_schema() AS schema")
            target = dict(cursor.fetchone())
            if target != plan["target"]:
                raise ValueError("Repair target does not match the reviewed manifest")
            if tables:
                # Stop concurrent ingestion from changing checked identities or
                # derived metrics between the backup and commit. Readers proceed.
                cursor.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                    sql.SQL(",").join(map(sql.Identifier, tables))))
            preimages = []
            predicates = []
            for op in operations:
                predicate = sql.SQL(" AND ").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in op["key"])
                predicates.append(predicate)
                cursor.execute(sql.SQL("SELECT * FROM {} WHERE {}").format(sql.Identifier(op["table"]), predicate), tuple(op["key"].values()))
                row = cursor.fetchone()
                expected = op["before"]
                if expected is None:
                    matches = row is None
                else:
                    matches = row is not None and all(json.dumps(row.get(k), default=str) == json.dumps(v, default=str) for k, v in expected.items())
                if not matches:
                    raise ValueError(f"Repair preimage changed: {op['table']} {op['key']}")
                preimages.append({"table": op["table"], "key": op["key"], "row": dict(row) if row else None})
            result = {"target": target, "operations": len(operations), "applied": apply}
            if not apply:
                return result
            assert backup is not None
            backup.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"target": target, "plan": plan, "preimages": preimages}, stream, ensure_ascii=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            # Make the directory entry durable as well as the backup contents.
            directory_fd = os.open(backup.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            for op, predicate in zip(operations, predicates):
                after = op["after"]
                table = sql.Identifier(op["table"])
                if after is None:
                    cursor.execute(sql.SQL("DELETE FROM {} WHERE {}").format(table, predicate), tuple(op["key"].values()))
                elif op["before"] is None:
                    values = {**op["key"], **after}
                    cursor.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        table, sql.SQL(",").join(map(sql.Identifier, values)),
                        sql.SQL(",").join(sql.Placeholder() for _ in values)), tuple(values.values()))
                else:
                    cursor.execute(sql.SQL("UPDATE {} SET {} WHERE {}").format(
                        table, sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in after), predicate),
                        (*after.values(), *op["key"].values()))
            return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(apply_plan(postgres_database, json.loads(args.plan.read_text()), apply=args.apply, backup=args.backup)))
    finally:
        postgres_database.close()


if __name__ == "__main__":
    main()
