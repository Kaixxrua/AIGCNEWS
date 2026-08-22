from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _normalize_semantic_project(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["topics"] = _json_list(item.pop("topics_json", None))
    item["tags"] = _json_list(item.pop("tags_json", None))
    item["stars"] = int(item.get("stars") or 0)
    item["forks"] = int(item.get("forks") or 0)
    return item


class PostgresGitHubProjectSemanticSourceRepository:
    """PostgreSQL semantic-source state for enriched GitHub projects."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle = postgres_database,
    ) -> None:
        self._database = database

    def list_github_projects_for_readme_bootstrap(
        self,
        *,
        limit: int = 100,
        min_stars: int = 500,
        after_repo_id: str = "",
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT c.repo_id, c.full_name, c.pushed_at,
                   ss.readme_text, ss.readme_sha256, ss.readme_etag,
                   ss.readme_status, ss.readme_checked_at,
                   ss.readme_fetched_at, ss.readme_repo_pushed_at,
                   ss.readme_error, ss.readme_retry_count,
                   ss.readme_next_retry_at
            FROM github_repo_candidates c
            LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
            WHERE NOT EXISTS (
                    SELECT 1 FROM github_repo_aliases ga
                    WHERE ga.alias_repo_id = c.repo_id
                      AND ga.canonical_repo_id <> c.repo_id
                  )
              AND COALESCE(c.stars, 0) >= %s
              AND c.availability_status = 'active'
              AND BTRIM(COALESCE(c.description, '')) = ''
              AND c.repo_id COLLATE "C" > %s COLLATE "C"
              AND (
                    ss.repo_id IS NULL
                 OR COALESCE(ss.readme_repo_pushed_at, '') < COALESCE(c.pushed_at, '')
                 OR (
                        ss.readme_status IN ('failed', 'rate_limited')
                    AND (
                        ss.readme_next_retry_at IS NULL
                        OR ss.readme_next_retry_at <= CURRENT_TIMESTAMP::text
                    )
                 )
              )
            ORDER BY c.repo_id COLLATE "C" ASC
            LIMIT %s
        """
        params = (
            min_stars,
            after_repo_id,
            max(1, min(int(limit or 100), 1000)),
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def upsert_github_project_readme_snapshot(self, payload: dict[str, Any]) -> None:
        data = dict(payload)
        now = str(data.get("readme_checked_at") or _utcnow())
        defaults = {
            "readme_text": None,
            "readme_sha256": "",
            "readme_etag": "",
            "readme_status": "pending",
            "readme_checked_at": now,
            "readme_fetched_at": None,
            "readme_repo_pushed_at": None,
            "readme_error": None,
            "readme_retry_count": 0,
            "readme_next_retry_at": None,
            "updated_at": now,
        }
        for key, value in defaults.items():
            data.setdefault(key, value)
        columns = ("repo_id", *defaults.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in defaults
        )
        sql = f"""
            INSERT INTO github_project_semantic_sources ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (repo_id) DO UPDATE SET {assignments}
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                data["repo_id"] = self._resolve_repo_id(
                    cursor, str(data.get("repo_id") or "")
                )
                cursor.execute(sql, tuple(data[column] for column in columns))

    def list_github_projects_for_semantic_sync(
        self,
        *,
        limit: int = 100,
        min_stars: int = 500,
        after_repo_id: str = "",
        retry_failed: bool = True,
    ) -> list[dict[str, Any]]:
        stale_statuses = ("pending", "failed") if retry_failed else ("pending",)
        sql = """
            SELECT
                c.repo_id, c.full_name, c.title, c.url, c.description, c.language,
                c.topics_json, c.pushed_at, c.stars, c.forks,
                ge.description_zh, ge.category_slug, ge.category_name,
                ge.category_name_zh, ge.category_name_en, ge.subcategory_slug,
                ge.subcategory_name, ge.subcategory_name_zh, ge.subcategory_name_en,
                ge.tags_json,
                ss.readme_text, ss.readme_sha256, ss.readme_etag,
                ss.readme_status, ss.readme_checked_at, ss.readme_fetched_at,
                ss.readme_repo_pushed_at,
                ss.source_fingerprint, ss.indexed_fingerprint, ss.index_status,
                ss.index_retry_count
            FROM github_repo_candidates c
            JOIN github_repo_enrichments ge
              ON ge.repo_id = c.repo_id AND ge.status = 'succeeded'
            LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
            WHERE NOT EXISTS (
                    SELECT 1 FROM github_repo_aliases ga
                    WHERE ga.alias_repo_id = c.repo_id
                      AND ga.canonical_repo_id <> c.repo_id
                  )
              AND COALESCE(c.stars, 0) >= %s
              AND c.repo_id COLLATE "C" > %s COLLATE "C"
              AND (
                    ss.repo_id IS NULL
                 OR ss.index_status = ANY(%s)
                 OR COALESCE(ss.source_fingerprint, '') <> COALESCE(ss.indexed_fingerprint, '')
                 OR COALESCE(ss.index_version, '') <> %s
                 OR COALESCE(ss.readme_repo_pushed_at, '') < COALESCE(c.pushed_at, '')
              )
            ORDER BY c.repo_id COLLATE "C" ASC
            LIMIT %s
        """
        params = (
            min_stars,
            after_repo_id,
            list(stale_statuses),
            settings.project_semantic_index_version,
            max(1, min(int(limit or 100), 1000)),
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [_normalize_semantic_project(row) for row in rows]

    def upsert_github_project_semantic_source(
        self, payload: dict[str, Any]
    ) -> None:
        data = dict(payload)
        defaults = {
            "readme_text": None,
            "readme_sha256": "",
            "readme_etag": "",
            "readme_status": "pending",
            "readme_checked_at": None,
            "readme_fetched_at": None,
            "readme_repo_pushed_at": None,
            "readme_error": None,
            "readme_retry_count": 0,
            "readme_next_retry_at": None,
            "source_fingerprint": "",
            "indexed_fingerprint": "",
            "index_version": "",
            "embedding_provider": "",
            "embedding_model": "",
            "embedding_dimension": 0,
            "chunk_count": 0,
            "index_status": "pending",
            "index_error": None,
            "index_retry_count": 0,
            "index_next_retry_at": None,
            "indexed_at": None,
            "updated_at": _utcnow(),
        }
        for key, value in defaults.items():
            data.setdefault(key, value)

        columns = ("repo_id", *defaults.keys())
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in defaults
        )
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"""
            INSERT INTO github_project_semantic_sources ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (repo_id) DO UPDATE SET {assignments}
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                repo_id = self._resolve_repo_id(cursor, str(data.get("repo_id") or ""))
                data["repo_id"] = repo_id
                cursor.execute(sql, tuple(data[column] for column in columns))

    def mark_github_project_semantic_snapshot_current(
        self,
        repo_id: str,
        *,
        repo_pushed_at: str,
        checked_at: str,
    ) -> None:
        """轻量推进快照水位：内容未变时只更新 pushed_at/检查时间。

        与 upsert 的全列覆盖语义不同，这里只动三个字段，避免把
        未指定的索引状态列重置回默认值。
        """
        sql = """
            UPDATE github_project_semantic_sources
            SET readme_repo_pushed_at = %s,
                readme_checked_at = %s,
                updated_at = %s
            WHERE repo_id = %s
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (repo_pushed_at, checked_at, checked_at, repo_id))

    def get_github_project_semantic_status(
        self, *, min_stars: int = 500
    ) -> dict[str, Any]:
        sql = """
            SELECT
                COUNT(*) AS eligible,
                COUNT(*) FILTER (WHERE ss.index_status = 'succeeded') AS indexed,
                COUNT(*) FILTER (WHERE ss.index_status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE ss.readme_status = 'succeeded') AS readme_succeeded,
                COALESCE(SUM(ss.chunk_count), 0) AS chunk_count,
                MAX(ss.indexed_at) AS last_indexed_at
            FROM github_repo_candidates c
            JOIN github_repo_enrichments ge
              ON ge.repo_id = c.repo_id AND ge.status = 'succeeded'
            LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
            WHERE NOT EXISTS (
                    SELECT 1 FROM github_repo_aliases ga
                    WHERE ga.alias_repo_id = c.repo_id
                      AND ga.canonical_repo_id <> c.repo_id
                  )
              AND COALESCE(c.stars, 0) >= %s
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (min_stars,))
                row = cursor.fetchone() or {}
        eligible = int(row.get("eligible") or 0)
        indexed = int(row.get("indexed") or 0)
        failed = int(row.get("failed") or 0)
        return {
            "eligible": eligible,
            "indexed": indexed,
            "failed": failed,
            "pending": max(eligible - indexed - failed, 0),
            "readme_succeeded": int(row.get("readme_succeeded") or 0),
            "chunk_count": int(row.get("chunk_count") or 0),
            "last_indexed_at": row.get("last_indexed_at"),
        }

    @staticmethod
    def _resolve_repo_id(cursor: Any, repo_id: str) -> str:
        repo_id = repo_id.strip()
        cursor.execute(
            """
            SELECT canonical_repo_id
            FROM github_repo_aliases
            WHERE alias_repo_id = %s
            LIMIT 1
            """,
            (repo_id,),
        )
        row = cursor.fetchone()
        if row and row.get("canonical_repo_id"):
            return str(row["canonical_repo_id"])
        return repo_id
