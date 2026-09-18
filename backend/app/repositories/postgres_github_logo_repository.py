from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import postgres_database


class PostgresGitHubLogoRepository:
    def __init__(self, database: Any = postgres_database) -> None:
        self.database = database

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.repo_id, c.full_name
                FROM github_repo_candidates c
                LEFT JOIN github_project_logos l ON l.repo_id = c.repo_id
                WHERE c.availability_status = 'active'
                  AND (l.repo_id IS NULL OR l.next_check_at <= CURRENT_TIMESTAMP)
                  AND NOT EXISTS (SELECT 1 FROM github_repo_aliases a
                      WHERE a.alias_repo_id = c.repo_id AND a.canonical_repo_id <> c.repo_id)
                ORDER BY l.checked_at ASC NULLS FIRST, c.stars DESC, c.repo_id
                LIMIT %s
            """, (max(1, min(limit, 1000)),))
            return [dict(row) for row in cursor.fetchall()]

    def save(self, repo_id: str, result: dict[str, Any]) -> None:
        # Failed refreshes retain the last good artwork; missing logos retry weekly.
        days = 30 if result["status"] == "found" else 7 if result["status"] == "not_found" else 1
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO github_project_logos
                    (repo_id, status, source_url, content, content_type, sha256, next_check_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP + %s * INTERVAL '1 day')
                ON CONFLICT (repo_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    source_url = CASE WHEN EXCLUDED.content IS NULL THEN github_project_logos.source_url ELSE EXCLUDED.source_url END,
                    content = COALESCE(EXCLUDED.content, github_project_logos.content),
                    content_type = CASE WHEN EXCLUDED.content IS NULL THEN github_project_logos.content_type ELSE EXCLUDED.content_type END,
                    sha256 = CASE WHEN EXCLUDED.content IS NULL THEN github_project_logos.sha256 ELSE EXCLUDED.sha256 END,
                    checked_at = CURRENT_TIMESTAMP, next_check_at = EXCLUDED.next_check_at
            """, (repo_id, result["status"], result.get("source_url", ""),
                  result.get("content"), result.get("content_type", ""), result.get("sha256", ""), days))

    def get(self, repo_id: str) -> dict[str, Any] | None:
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT l.content, l.content_type, l.sha256 FROM github_project_logos l
                JOIN github_repo_candidates c ON c.repo_id = l.repo_id
                WHERE l.repo_id = COALESCE(
                    (SELECT canonical_repo_id FROM github_repo_aliases WHERE alias_repo_id = %s), %s)
                  AND c.availability_status = 'active' AND l.content IS NOT NULL
            """, (repo_id, repo_id))
            row = cursor.fetchone()
            return dict(row) if row else None
