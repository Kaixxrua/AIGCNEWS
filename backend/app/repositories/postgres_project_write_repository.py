from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.domain.project_taxonomy import ENGLISH_LABEL_BY_SLUG
from backend.app.repositories.postgres_project_catalog import (
    PostgresProjectCatalogRepository,
)
from backend.app.repositories.project_catalog_normalization import normalize_project_row


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        try:
            values = json.loads(value or "[]")
        except (TypeError, ValueError):
            values = []
    return [str(item).strip() for item in values if str(item).strip()]


class PostgresProjectWriteRepository(PostgresProjectCatalogRepository):
    """PostgreSQL aggregate adapter for personal collections and recommendations."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle = postgres_database,
        *,
        statement_timeout_ms: int | None = None,
    ) -> None:
        super().__init__(database, statement_timeout_ms=statement_timeout_ms)

    @staticmethod
    def _resolve_github_repo_id(cursor: Any, repo_id: str = "", full_name: str = "") -> str:
        repo_id = (repo_id or "").strip()
        full_name = (full_name or "").strip()
        if repo_id:
            cursor.execute(
                "SELECT canonical_repo_id FROM github_repo_aliases "
                "WHERE alias_repo_id = %s LIMIT 1",
                (repo_id,),
            )
            row = cursor.fetchone()
            if row and row.get("canonical_repo_id"):
                return str(row["canonical_repo_id"])
        if full_name:
            cursor.execute(
                """SELECT repo_id FROM github_repo_candidates
                   WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                   ORDER BY (repo_id = full_name) DESC, COALESCE(stars, 0) DESC,
                            COALESCE(last_seen_at, '') DESC
                   LIMIT 1""",
                (full_name,),
            )
            row = cursor.fetchone()
            if row and row.get("repo_id"):
                return str(row["repo_id"])
        return full_name or repo_id

    def _github_candidate(self, cursor: Any, repo_id: str, full_name: str) -> dict[str, Any]:
        resolved = self._resolve_github_repo_id(cursor, repo_id, full_name or repo_id)
        cursor.execute(
            """SELECT repo_id, full_name FROM github_repo_candidates
               WHERE repo_id = %s
                  OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                  OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
               ORDER BY (repo_id = %s) DESC, COALESCE(stars, 0) DESC,
                        COALESCE(last_seen_at, '') DESC
               LIMIT 1""",
            (resolved, repo_id, full_name, resolved),
        )
        row = cursor.fetchone()
        if not row or not row.get("repo_id"):
            raise LookupError("GitHub 项目不存在")
        return row

    def recommend_github_project(
        self,
        *,
        repo_id: Any = None,
        full_name: str = "",
        recommended_by_user_id: int | None = None,
    ) -> dict[str, Any]:
        identity = str(repo_id or "").strip()
        clean_name = (full_name or "").strip()
        if not identity and not clean_name:
            raise ValueError("repo_id 或 full_name 不能为空")
        user_id = int(recommended_by_user_id) if recommended_by_user_id else None
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                row = self._github_candidate(cursor, identity, clean_name)
                canonical_id = str(row["repo_id"])
                cursor.execute(
                    """INSERT INTO github_repo_recommendations
                           (repo_id, active, recommended_by_user_id)
                       VALUES (%s, TRUE, %s)
                       ON CONFLICT (repo_id) DO UPDATE SET
                           active = TRUE,
                           recommended_by_user_id = EXCLUDED.recommended_by_user_id,
                           updated_at = CURRENT_TIMESTAMP
                       RETURNING recommended_at""",
                    (canonical_id, user_id),
                )
                recommendation = cursor.fetchone() or {}
        return {
            "repo_id": canonical_id,
            "full_name": row.get("full_name") or clean_name or identity,
            "is_recommended": True,
            "recommended_at": _iso(recommendation.get("recommended_at")),
        }

    def unrecommend_github_project(
        self, *, repo_id: Any = None, full_name: str = ""
    ) -> dict[str, Any]:
        identity = str(repo_id or "").strip()
        clean_name = (full_name or "").strip()
        if not identity and not clean_name:
            raise ValueError("repo_id 或 full_name 不能为空")
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                row = self._github_candidate(cursor, identity, clean_name)
                canonical_id = str(row["repo_id"])
                cursor.execute(
                    """UPDATE github_repo_recommendations
                       SET active = FALSE, updated_at = CURRENT_TIMESTAMP
                       WHERE repo_id = %s AND active = TRUE""",
                    (canonical_id,),
                )
                removed = cursor.rowcount > 0
        return {
            "repo_id": canonical_id,
            "full_name": row.get("full_name") or clean_name or identity,
            "is_recommended": False,
            "recommended_at": None,
            "removed": removed,
        }

    def _favorite_key(
        self,
        cursor: Any,
        *,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
        user_id: int | None = None,
        require_access: bool = False,
    ) -> tuple[str, str]:
        source = (source or "").strip().lower()
        if source == "github":
            identity = str(repo_id or "").strip()
            if not identity:
                raise ValueError("repo_id 不能为空")
            row = self._github_candidate(cursor, identity, identity)
            return "github", str(row["repo_id"])
        if source != "website":
            raise ValueError("source 只能是 github 或 website")
        try:
            website = int(website_id or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("website_id 无效") from exc
        if website <= 0:
            raise ValueError("website_id 不能为空")
        if require_access:
            if not user_id:
                raise LookupError("工具网站不存在或不可收藏")
            cursor.execute(
                """SELECT w.id FROM tool_websites w
                   LEFT JOIN user_tool_websites utw
                     ON utw.website_id = w.id AND utw.user_id = %s
                   WHERE w.id = %s
                     AND (w.added_by_user_id = %s OR utw.id IS NOT NULL)
                   LIMIT 1""",
                (int(user_id), website, int(user_id)),
            )
        else:
            cursor.execute("SELECT id FROM tool_websites WHERE id = %s LIMIT 1", (website,))
        row = cursor.fetchone()
        if not row or not row.get("id"):
            raise LookupError("工具网站不存在或不可收藏")
        return "website", str(row["id"])

    def add_project_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> dict[str, Any]:
        user_id = int(user_id)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                project_source, project_id = self._favorite_key(
                    cursor,
                    source=source,
                    repo_id=repo_id,
                    website_id=website_id,
                    user_id=user_id,
                    require_access=True,
                )
                cursor.execute(
                    """INSERT INTO project_favorites (user_id, project_source, project_id)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (user_id, project_source, project_id) DO UPDATE
                           SET created_at = project_favorites.created_at
                       RETURNING created_at""",
                    (user_id, project_source, project_id),
                )
                row = cursor.fetchone() or {}
        result: dict[str, Any] = {
            "source": project_source,
            "project_id": project_id,
            "is_favorited": True,
            "favorited_at": _iso(row.get("created_at")),
        }
        result["repo_id" if project_source == "github" else "website_id"] = (
            project_id if project_source == "github" else int(project_id)
        )
        return result

    def remove_project_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> bool:
        user_id = int(user_id)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                if (source or "").strip().lower() == "website":
                    try:
                        website = int(website_id or 0)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("website_id 无效") from exc
                    if website <= 0:
                        raise ValueError("website_id 不能为空")
                    project_source, project_id = "website", str(website)
                else:
                    project_source, project_id = self._favorite_key(
                        cursor, source=source, repo_id=repo_id, website_id=website_id
                    )
                cursor.execute(
                    "DELETE FROM project_favorites WHERE user_id = %s "
                    "AND project_source = %s AND project_id = %s",
                    (user_id, project_source, project_id),
                )
                return cursor.rowcount > 0

    def link_user_tool_website(
        self, *, user_id: int, website_id: int, added_via: str = "auto"
    ) -> dict[str, Any]:
        user_id, website_id = int(user_id), int(website_id)
        added_via = (added_via or "auto").strip().lower()
        if added_via not in {"auto", "manual", "existing"}:
            added_via = "auto"
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM tool_websites WHERE id = %s LIMIT 1", (website_id,))
                if not cursor.fetchone():
                    raise LookupError("工具网站不存在")
                cursor.execute(
                    """INSERT INTO user_tool_websites (user_id, website_id, added_via)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (user_id, website_id) DO UPDATE SET
                           added_via = EXCLUDED.added_via,
                           updated_at = CURRENT_TIMESTAMP
                       RETURNING created_at""",
                    (user_id, website_id, added_via),
                )
                row = cursor.fetchone() or {}
        return {
            "user_added": True,
            "user_added_at": _iso(row.get("created_at")),
            "is_favorited": False,
            "favorited_at": None,
        }

    def unlink_user_tool_website(self, *, user_id: int, website_id: int) -> bool:
        user_id, website_id = int(user_id), int(website_id)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_tool_website_overrides WHERE user_id = %s AND website_id = %s",
                    (user_id, website_id),
                )
                cursor.execute(
                    "DELETE FROM project_favorites WHERE user_id = %s "
                    "AND project_source = 'website' AND project_id = %s",
                    (user_id, str(website_id)),
                )
                deleted_favorite = cursor.rowcount > 0
                cursor.execute(
                    "DELETE FROM user_tool_websites WHERE user_id = %s AND website_id = %s",
                    (user_id, website_id),
                )
                deleted_link = cursor.rowcount > 0
        return deleted_link or deleted_favorite

    def get_tool_website_item_for_user(
        self, *, user_id: int, website_id: int
    ) -> dict[str, Any] | None:
        sql = """SELECT 'website:' || w.id::text AS id, 'website' AS source,
                   NULL::text AS repo_id, w.id AS website_id,
                   COALESCE(NULLIF(uo.title, ''), NULLIF(w.title, ''), w.domain) AS full_name,
                   COALESCE(NULLIF(uo.title, ''), w.title) AS title,
                   w.canonical_url AS url, w.domain,
                   COALESCE(NULLIF(uo.image_url, ''), NULLIF(w.image_url, ''),
                       regexp_replace(w.canonical_url, '^(([^/]+/){2}[^/]+).*$', '\\1') || '/favicon.ico') AS image_url,
                   COALESCE(NULLIF(uo.description, ''), w.description) AS description,
                   COALESCE(NULLIF(uo.description_zh, ''), e.description_zh) AS description_zh,
                   COALESCE(NULLIF(uo.description_en, ''), e.description_en) AS description_en,
                   COALESCE(NULLIF(uo.category_slug, ''), e.category_slug) AS category_slug,
                   COALESCE(NULLIF(uo.category_name_zh, ''), e.category_name_zh, NULLIF(uo.category_name, ''), e.category_name) AS category_name_zh,
                   COALESCE(NULLIF(uo.category_name_en, ''), e.category_name_en) AS category_name_en,
                   COALESCE(NULLIF(uo.subcategory_slug, ''), e.subcategory_slug) AS subcategory_slug,
                   COALESCE(NULLIF(uo.subcategory_name_zh, ''), e.subcategory_name_zh, NULLIF(uo.subcategory_name, ''), e.subcategory_name) AS subcategory_name_zh,
                   COALESCE(NULLIF(uo.subcategory_name_en, ''), e.subcategory_name_en) AS subcategory_name_en,
                   COALESCE(NULLIF(uo.tags_json::text, ''), e.tags_json::text) AS tags_json,
                   CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN NULL
                        ELSE e.tags_zh_json::text END AS tags_zh_json,
                   CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN NULL
                        ELSE e.tags_en_json::text END AS tags_en_json,
                   CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN 'user'
                        ELSE 'system' END AS tags_origin,
                   NULL::text AS language, '[]' AS topics_json, 0 AS stars, 0 AS forks,
                   0 AS watchers, 0 AS open_issues, NULL::text AS created_at,
                   NULL::text AS pushed_at, w.first_seen_at, w.last_seen_at,
                   NULL::text AS last_snapshot_at, NULL::text AS snapshot_date,
                   NULL::text AS captured_at, e.confidence,
                   (pf.id IS NOT NULL) AS is_favorited, pf.created_at AS favorited_at,
                   (utw.id IS NOT NULL) AS user_added, utw.created_at AS user_added_at
               FROM tool_websites w
               LEFT JOIN tool_website_enrichments e ON e.website_id = w.id
               LEFT JOIN user_tool_websites utw ON utw.user_id = %s AND utw.website_id = w.id
               LEFT JOIN project_favorites pf ON pf.user_id = %s
                    AND pf.project_source = 'website' AND pf.project_id = w.id::text
               LEFT JOIN user_tool_website_overrides uo ON uo.user_id = %s AND uo.website_id = w.id
               WHERE w.id = %s LIMIT 1"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (int(user_id), int(user_id), int(user_id), int(website_id)))
                row = cursor.fetchone()
        return normalize_project_row(row) if row else None

    def upsert_user_tool_website_override(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        user_id, website_id = int(data.get("user_id") or 0), int(data.get("website_id") or 0)
        if user_id <= 0 or website_id <= 0:
            raise ValueError("用户或工具网站无效")
        tags_json = data.get("tags_json") or json.dumps(data.get("tags") or [], ensure_ascii=False)
        data["category_name_zh"] = data.get("category_name_zh") or data.get("category_name") or ""
        data["category_name_en"] = data.get("category_name_en") or ENGLISH_LABEL_BY_SLUG.get(str(data.get("category_slug") or ""), "")
        data["category_name"] = data["category_name_zh"]
        data["subcategory_name_zh"] = data.get("subcategory_name_zh") or data.get("subcategory_name") or ""
        data["subcategory_name_en"] = data.get("subcategory_name_en") or ENGLISH_LABEL_BY_SLUG.get(str(data.get("subcategory_slug") or ""), "")
        data["subcategory_name"] = data["subcategory_name_zh"]
        fields = tuple(str(data.get(name) or "") for name in (
            "title", "description", "image_url", "description_zh", "description_en",
            "category_slug", "category_name", "category_name_zh", "category_name_en",
            "subcategory_slug", "subcategory_name", "subcategory_name_zh", "subcategory_name_en"
        ))
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM user_tool_websites WHERE user_id = %s AND website_id = %s LIMIT 1",
                    (user_id, website_id),
                )
                if not cursor.fetchone():
                    raise LookupError("该工具网站不在你的收藏夹中")
                cursor.execute(
                    """INSERT INTO user_tool_website_overrides
                           (user_id, website_id, title, description, image_url, description_zh, description_en,
                            category_slug, category_name, category_name_zh, category_name_en,
                            subcategory_slug, subcategory_name, subcategory_name_zh, subcategory_name_en, tags_json)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (user_id, website_id) DO UPDATE SET
                           title=EXCLUDED.title, description=EXCLUDED.description,
                           image_url=EXCLUDED.image_url, description_zh=EXCLUDED.description_zh,
                           description_en=EXCLUDED.description_en, category_slug=EXCLUDED.category_slug,
                           category_name=EXCLUDED.category_name, category_name_zh=EXCLUDED.category_name_zh,
                           category_name_en=EXCLUDED.category_name_en, subcategory_slug=EXCLUDED.subcategory_slug,
                           subcategory_name=EXCLUDED.subcategory_name,
                           subcategory_name_zh=EXCLUDED.subcategory_name_zh,
                           subcategory_name_en=EXCLUDED.subcategory_name_en, tags_json=EXCLUDED.tags_json,
                           updated_at=CURRENT_TIMESTAMP""",
                    (user_id, website_id, *fields, tags_json),
                )
        item = self.get_tool_website_item_for_user(user_id=user_id, website_id=website_id)
        if not item:
            raise LookupError("工具网站不存在")
        return item

    def list_user_project_collection(self, *, user_id: int, **kwargs: Any) -> dict[str, Any]:
        return self.list_projects(user_id=user_id, favorites_only=True, **kwargs)

    def get_user_project_categories(
        self,
        *,
        user_id: int,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> dict[str, Any]:
        return self.get_project_categories(
            source=source, min_stars=min_stars, enriched_only=enriched_only,
            user_id=user_id, favorites_only=True,
        )

    def get_user_project_tags(
        self,
        *,
        user_id: int,
        source: str = "github",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> dict[str, Any]:
        user_id = int(user_id)
        source = (source or "github").strip().lower()
        source = source if source in {"github", "website"} else "github"
        if source == "website":
            status = "AND (we.status = 'succeeded' OR uo.id IS NOT NULL)" if enriched_only else ""
            sql = f"""SELECT
                          COALESCE(NULLIF(uo.tags_json::text, ''), we.tags_json::text) AS tags_json,
                          CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN NULL ELSE we.tags_zh_json::text END AS tags_zh_json,
                          CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN NULL ELSE we.tags_en_json::text END AS tags_en_json,
                          CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN 'user' ELSE 'system' END AS tags_origin
                      FROM tool_websites w
                      JOIN user_tool_websites utw ON utw.user_id = %s AND utw.website_id = w.id
                      LEFT JOIN tool_website_enrichments we ON we.website_id = w.id
                      LEFT JOIN user_tool_website_overrides uo ON uo.user_id = %s AND uo.website_id = w.id
                      WHERE TRUE {status}"""
            params = (user_id, user_id)
        else:
            status = "AND ge.status = 'succeeded'" if enriched_only else ""
            sql = f"""SELECT ge.tags_json::text AS tags_json,
                             ge.tags_zh_json::text AS tags_zh_json,
                             ge.tags_en_json::text AS tags_en_json,
                             'system' AS tags_origin
                      FROM github_repo_candidates c
                      JOIN project_favorites pf ON pf.user_id = %s
                           AND pf.project_source = 'github' AND pf.project_id = c.repo_id
                      LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                      WHERE COALESCE(c.stars, 0) >= %s {status}"""
            params = (user_id, min_stars)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        counts: dict[str, dict[str, Any]] = {}
        for row in rows:
            stable_tags = _json_list(row.get("tags_json"))
            origin = "user" if row.get("tags_origin") == "user" else "system"
            zh_tags = stable_tags if origin == "user" else (_json_list(row.get("tags_zh_json")) or stable_tags)
            en_tags = stable_tags if origin == "user" else (_json_list(row.get("tags_en_json")) or stable_tags)
            for index, value in enumerate(stable_tags):
                if value in {"AI 工具", "网页收藏"}:
                    continue
                item = counts.setdefault(value, {
                    "label": value,
                    "value": value,
                    "label_zh": str(zh_tags[index] if index < len(zh_tags) else value).strip() or value,
                    "label_en": str(en_tags[index] if index < len(en_tags) else value).strip() or value,
                    "count": 0,
                    "tags_origin": origin,
                })
                item["count"] += 1
                if origin == "user":
                    item["label_zh"] = value
                    item["label_en"] = value
                    item["tags_origin"] = "user"
        items = sorted(counts.values(), key=lambda item: (-int(item["count"]), str(item["value"])))
        return {"items": items, "total": len(items), "source": source}
