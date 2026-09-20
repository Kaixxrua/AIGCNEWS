from __future__ import annotations

from typing import Any

from backend.app.core.github_artwork import GITHUB_DEFAULT_AVATAR_SHA256
from backend.app.core.postgres_database import postgres_database


class PostgresGitHubLogoRepository:
    def __init__(self, database: Any = postgres_database) -> None:
        self.database = database

    def enqueue_all(self) -> int:
        """Schedule one full refresh without deleting the last good artwork."""
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE github_project_logos SET next_check_at = CURRENT_TIMESTAMP")
            return cursor.rowcount

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.repo_id, c.full_name
                FROM github_repo_candidates c
                LEFT JOIN github_project_logos l ON l.repo_id = c.repo_id
                LEFT JOIN github_repo_daily_metrics m ON m.repo_id = c.repo_id
                  AND m.metric_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date::text
                WHERE c.availability_status = 'active'
                  AND (l.repo_id IS NULL OR l.next_check_at <= CURRENT_TIMESTAMP
                       OR (l.status = 'not_found' AND l.content IS NULL)
                       OR (l.status = 'found' AND l.sha256 = %s))
                  AND NOT EXISTS (SELECT 1 FROM github_repo_aliases a
                      WHERE a.alias_repo_id = c.repo_id AND a.canonical_repo_id <> c.repo_id)
                ORDER BY CASE WHEN m.daily_growth_available AND m.daily_star_growth > 0
                              THEN m.hot_score END DESC NULLS LAST,
                         (l.content IS NULL) DESC,
                         (NULLIF(c.first_seen_at, '')::timestamptz >= CURRENT_TIMESTAMP - INTERVAL '1 day') DESC NULLS LAST,
                         l.checked_at ASC NULLS FIRST, c.stars DESC, c.repo_id
                LIMIT %s
            """, (GITHUB_DEFAULT_AVATAR_SHA256, max(1, min(limit, 1000))))
            return [dict(row) for row in cursor.fetchall()]

    def save(self, repo_id: str, result: dict[str, Any]) -> None:
        # Transient failures must be retryable by the next intraday ranking refresh.
        hours = 720 if result["status"] == "found" else 168 if result["status"] == "not_found" else 1
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO github_project_logos
                    (repo_id, status, source_url, content, content_type, sha256, next_check_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP + %s * INTERVAL '1 hour')
                ON CONFLICT (repo_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    source_url = CASE WHEN EXCLUDED.content IS NULL THEN github_project_logos.source_url ELSE EXCLUDED.source_url END,
                    content = COALESCE(EXCLUDED.content, github_project_logos.content),
                    content_type = CASE WHEN EXCLUDED.content IS NULL THEN github_project_logos.content_type ELSE EXCLUDED.content_type END,
                    sha256 = CASE WHEN EXCLUDED.content IS NULL THEN github_project_logos.sha256 ELSE EXCLUDED.sha256 END,
                    checked_at = CURRENT_TIMESTAMP, next_check_at = EXCLUDED.next_check_at
            """, (repo_id, result["status"], result.get("source_url", ""),
                  result.get("content"), result.get("content_type", ""), result.get("sha256", ""), hours))

    def enqueue_missing(self) -> int:
        """Recover historical failures without invalidating successful artwork."""
        with self.database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""
                UPDATE github_project_logos SET next_check_at = CURRENT_TIMESTAMP
                WHERE content IS NULL OR sha256 = %s
            """, (GITHUB_DEFAULT_AVATAR_SHA256,))
            return cursor.rowcount

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
