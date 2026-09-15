#!/usr/bin/env python3
"""Provision and tear down one explicitly named PostgreSQL test database.

The admin DSN is an explicit, test-only input.  This module never discovers or
selects databases: teardown operates only on the exact database written by the
provision step.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from psycopg import Error as PsycopgError, connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

DATABASE_PREFIX = "aigcnews_test_"
MARKER_TABLE = "aigcnews_test_run_guard"


def _safe_part(value: str) -> str:
    value = "".join(char.lower() if char.isalnum() else "_" for char in value)
    value = value.strip("_")
    return value[:24] or "run"


def _admin_params(admin_dsn: str) -> dict[str, str]:
    try:
        params = {key: str(value) for key, value in conninfo_to_dict(admin_dsn).items()}
    except Exception as exc:
        raise ValueError("invalid TEST_POSTGRES_ADMIN_DSN") from exc
    for key in ("host", "port", "user", "dbname"):
        if not params.get(key):
            raise ValueError(f"TEST_POSTGRES_ADMIN_DSN must explicitly set {key}")
    return params


def database_name(run_id: str) -> str:
    # PostgreSQL identifiers are limited to 63 bytes; the random suffix keeps
    # two runs isolated even when callers reuse a run label.
    suffix = secrets.token_hex(10)
    return f"{DATABASE_PREFIX}{_safe_part(run_id)}_{suffix}"[:63]


def _target_dsn(admin_dsn: str, database: str) -> str:
    return make_conninfo(admin_dsn, dbname=database)


def provision(admin_dsn: str, run_id: str) -> dict[str, str]:
    if not run_id or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for char in run_id):
        raise ValueError("run_id contains unsafe characters")
    _admin_params(admin_dsn)
    database = database_name(run_id)
    dsn = _target_dsn(admin_dsn, database)
    with connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        with connect(dsn, autocommit=True) as target:
            target.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public"))
            target.execute(
                "CREATE TABLE public.aigcnews_test_run_guard "
                "(run_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            target.execute(
                "INSERT INTO public.aigcnews_test_run_guard (run_id) VALUES (%s)",
                (run_id,),
            )
    except Exception:
        # Best effort cleanup is deliberately exact and cannot enumerate other
        # databases.  Preserve the original bootstrap error for the caller.
        try:
            drop_database(admin_dsn, database)
        except (OSError, PsycopgError, RuntimeError, ValueError) as cleanup_error:
            raise RuntimeError(
                f"orphaned PostgreSQL test database: {database} ({cleanup_error})"
            ) from None
        raise
    return {"database": database, "dsn": dsn, "run_id": run_id}


def drop_database(admin_dsn: str, database: str, *, run_id: str | None = None) -> None:
    if not database.startswith(DATABASE_PREFIX) or len(database) > 63:
        raise ValueError("refusing to drop a database outside the test prefix")
    target_dsn = _target_dsn(admin_dsn, database)
    if run_id is not None:
        with connect(target_dsn, autocommit=True) as target:
            row = target.execute(
                "SELECT current_database(), current_user, "
                "(SELECT run_id FROM public.aigcnews_test_run_guard WHERE run_id = %s)",
                (run_id,),
            ).fetchone()
            if not row or row[0] != database or row[2] != run_id:
                raise ValueError("live database identity or marker mismatch; refusing cleanup")
    with connect(admin_dsn, autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database,),
        )
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    provision_parser = sub.add_parser("provision")
    provision_parser.add_argument("--admin-dsn", default=os.environ.get("TEST_POSTGRES_ADMIN_DSN", ""))
    provision_parser.add_argument("--run-id", required=True)
    provision_parser.add_argument("--output", type=Path, required=True)
    drop_parser = sub.add_parser("drop")
    drop_parser.add_argument("--admin-dsn", default=os.environ.get("TEST_POSTGRES_ADMIN_DSN", ""))
    drop_parser.add_argument("--database", required=True)
    drop_parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        if not args.admin_dsn:
            raise ValueError("TEST_POSTGRES_ADMIN_DSN is required")
        if args.command == "provision":
            value: Any = provision(args.admin_dsn, args.run_id)
            args.output.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(args.output, 0o600)
        else:
            drop_database(args.admin_dsn, args.database, run_id=args.run_id)
    except (OSError, PsycopgError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
