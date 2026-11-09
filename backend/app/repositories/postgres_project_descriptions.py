"""Exact, bounded reads for standalone descriptions; never writes the catalog."""

from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database


class PostgresProjectDescriptionRepository:
    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database

    def lookup(self, repos: list[str]) -> dict[str, dict[str, Any]]:
        # repo_id is the normalized owner/repo primary key. Keep the same alias
        # and quarantine boundary as the public catalog and peek repository.
        with self._database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT set_config('statement_timeout', '2000', true)")
            cursor.execute(
                "SELECT c.repo_id, c.full_name, ge.description_zh, ge.status,"
                " (EXISTS (SELECT 1 FROM github_repo_aliases ga WHERE ga.alias_repo_id=c.repo_id"
                " AND ga.canonical_repo_id<>c.repo_id)"
                " OR EXISTS (SELECT 1 FROM github_repo_quarantine gq WHERE gq.repo_id=c.repo_id)"
                " OR c.availability_status<>'active') AS blocked"
                " FROM github_repo_candidates c"
                " LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id"
                " WHERE c.repo_id=ANY(%s)",
                (repos,),
            )
            rows = cursor.fetchall()
        result = {}
        for row in rows:
            key = str(row.get("repo_id") or "").lower()
            if key not in repos:
                continue
            blocked = bool(row.get("blocked")) or str(row.get("full_name") or "").lower() != key
            result[key] = {
                "blocked": blocked,
                "descriptionZh": str(row.get("description_zh") or "")
                if not blocked and row.get("status") == "succeeded" else "",
            }
        return result
