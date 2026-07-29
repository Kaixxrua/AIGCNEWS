from __future__ import annotations

from typing import Any

from backend.app.repositories.mysql_repo import (
    MySQLRepository,
    _json_dumps,
    _json_loads_list,
    _normalize_project_row,
    _to_iso_string,
)


class MySQLUserProjectCollectionRepository:
    """MySQL adapter for a user's personal project collection."""

    def __init__(self, repository: MySQLRepository | None = None) -> None:
        self._repository = repository if repository is not None else MySQLRepository()
        self._database = getattr(self._repository, "_database", None)

    def _connect(self):
        return self._repository._connect()

    def _favorite_project_key_cur(
        self,
        cur: Any,
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
            resolved = self._repository._resolve_github_repo_id_cur(
                cur, identity, identity
            )
            cur.execute(
                """
                SELECT repo_id
                FROM github_repo_candidates
                WHERE repo_id = %s OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (resolved, identity),
            )
            row = cur.fetchone()
            if not row or not row.get("repo_id"):
                raise LookupError("GitHub 项目不存在")
            return "github", str(row["repo_id"])
        if source == "website":
            try:
                website_id_int = int(website_id or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError("website_id 无效") from exc
            if website_id_int <= 0:
                raise ValueError("website_id 不能为空")
            if require_access:
                if not user_id:
                    raise LookupError("工具网站不存在或不可收藏")
                cur.execute(
                    """
                    SELECT w.id
                    FROM tool_websites w
                    LEFT JOIN user_tool_websites utw
                      ON utw.website_id = w.id AND utw.user_id = %s
                    WHERE w.id = %s
                      AND (
                        w.added_by_user_id = %s
                        OR utw.id IS NOT NULL
                      )
                    LIMIT 1
                    """,
                    (int(user_id), website_id_int, int(user_id)),
                )
            else:
                cur.execute(
                    "SELECT id FROM tool_websites WHERE id = %s LIMIT 1",
                    (website_id_int,),
                )
            row = cur.fetchone()
            if not row or not row.get("id"):
                raise LookupError("工具网站不存在或不可收藏")
            return "website", str(row["id"])
        raise ValueError("source 只能是 github 或 website")

    def add_project_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> dict[str, Any]:
        user_id = int(user_id)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                project_source, project_id = self._favorite_project_key_cur(
                    cur,
                    source=source,
                    repo_id=repo_id,
                    website_id=website_id,
                    user_id=user_id,
                    require_access=True,
                )
                cur.execute(
                    """
                    INSERT INTO project_favorites (user_id, project_source, project_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE created_at = created_at
                    """,
                    (user_id, project_source, project_id),
                )
                cur.execute(
                    """
                    SELECT created_at
                    FROM project_favorites
                    WHERE user_id = %s AND project_source = %s AND project_id = %s
                    LIMIT 1
                    """,
                    (user_id, project_source, project_id),
                )
                row = cur.fetchone() or {}
                self._repository._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="project_favorites",
                    aggregate_key={
                        "user_id": user_id,
                        "project_source": project_source,
                        "project_id": project_id,
                    },
                    source_method="add_project_favorite",
                )
            conn.commit()
            result: dict[str, Any] = {
                "source": project_source,
                "project_id": project_id,
                "is_favorited": True,
                "favorited_at": _to_iso_string(row.get("created_at")),
            }
            if project_source == "github":
                result["repo_id"] = project_id
            else:
                result["website_id"] = int(project_id)
            return result
        finally:
            conn.close()

    def remove_project_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> bool:
        user_id = int(user_id)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if (source or "").strip().lower() == "website":
                    try:
                        website_id_int = int(website_id or 0)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("website_id 无效") from exc
                    if website_id_int <= 0:
                        raise ValueError("website_id 不能为空")
                    project_source, project_id = "website", str(website_id_int)
                else:
                    project_source, project_id = self._favorite_project_key_cur(
                        cur,
                        source=source,
                        repo_id=repo_id,
                        website_id=website_id,
                    )
                cur.execute(
                    """
                    DELETE FROM project_favorites
                    WHERE user_id = %s AND project_source = %s AND project_id = %s
                    """,
                    (user_id, project_source, project_id),
                )
                deleted_favorite = cur.rowcount > 0
                if deleted_favorite:
                    self._repository._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="project_favorites",
                        aggregate_key={
                            "user_id": user_id,
                            "project_source": project_source,
                            "project_id": project_id,
                        },
                        operation="delete",
                        source_method="remove_project_favorite",
                    )
            conn.commit()
            return deleted_favorite
        finally:
            conn.close()

    def link_user_tool_website(
        self,
        *,
        user_id: int,
        website_id: int,
        added_via: str = "auto",
    ) -> dict[str, Any]:
        user_id = int(user_id)
        website_id = int(website_id)
        added_via = (added_via or "auto").strip().lower()
        if added_via not in {"auto", "manual", "existing"}:
            added_via = "auto"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM tool_websites WHERE id = %s LIMIT 1",
                    (website_id,),
                )
                if not cur.fetchone():
                    raise LookupError("工具网站不存在")
                cur.execute(
                    """
                    INSERT INTO user_tool_websites (user_id, website_id, added_via)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE added_via = VALUES(added_via), updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, website_id, added_via),
                )
                cur.execute(
                    """
                    SELECT utw.created_at AS user_added_at
                    FROM user_tool_websites utw
                    WHERE utw.user_id = %s AND utw.website_id = %s
                    LIMIT 1
                    """,
                    (user_id, website_id),
                )
                row = cur.fetchone() or {}
                self._repository._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="user_tool_websites",
                    aggregate_key={"user_id": user_id, "website_id": website_id},
                    source_method="link_user_tool_website",
                )
            conn.commit()
            return {
                "user_added": True,
                "user_added_at": _to_iso_string(row.get("user_added_at")),
                "is_favorited": False,
                "favorited_at": None,
            }
        finally:
            conn.close()

    def unlink_user_tool_website(self, *, user_id: int, website_id: int) -> bool:
        user_id = int(user_id)
        website_id = int(website_id)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_tool_websites WHERE user_id = %s AND website_id = %s",
                    (user_id, website_id),
                )
                deleted_link = cur.rowcount > 0
                cur.execute(
                    "DELETE FROM user_tool_website_overrides WHERE user_id = %s AND website_id = %s",
                    (user_id, website_id),
                )
                deleted_override = cur.rowcount > 0
                cur.execute(
                    """
                    DELETE FROM project_favorites
                    WHERE user_id = %s AND project_source = 'website' AND project_id = %s
                    """,
                    (user_id, str(website_id)),
                )
                deleted_favorite = cur.rowcount > 0
                if deleted_override:
                    self._repository._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="user_tool_website_overrides",
                        aggregate_key={"user_id": user_id, "website_id": website_id},
                        operation="delete",
                        source_method="unlink_user_tool_website",
                    )
                if deleted_favorite:
                    self._repository._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="project_favorites",
                        aggregate_key={
                            "user_id": user_id,
                            "project_source": "website",
                            "project_id": str(website_id),
                        },
                        operation="delete",
                        source_method="unlink_user_tool_website",
                    )
                if deleted_link:
                    self._repository._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="user_tool_websites",
                        aggregate_key={"user_id": user_id, "website_id": website_id},
                        operation="delete",
                        source_method="unlink_user_tool_website",
                    )
            conn.commit()
            return deleted_link or deleted_favorite
        finally:
            conn.close()

    def get_tool_website_item_for_user(
        self, *, user_id: int, website_id: int
    ) -> dict[str, Any] | None:
        user_id = int(user_id)
        website_id = int(website_id)
        sql = """
            SELECT
                CONCAT('website:', w.id) AS id,
                'website' AS source,
                NULL AS repo_id,
                w.id AS website_id,
                COALESCE(NULLIF(uo.title, ''), NULLIF(w.title, ''), w.domain) AS full_name,
                COALESCE(NULLIF(uo.title, ''), w.title) AS title,
                w.canonical_url AS url,
                w.domain,
                COALESCE(NULLIF(uo.image_url, ''), NULLIF(w.image_url, ''), CONCAT(SUBSTRING_INDEX(w.canonical_url, '/', 3), '/favicon.ico')) AS image_url,
                COALESCE(NULLIF(uo.description, ''), w.description) AS description,
                COALESCE(NULLIF(uo.description_zh, ''), e.description_zh) AS description_zh,
                COALESCE(NULLIF(uo.category_slug, ''), e.category_slug) AS category_slug,
                COALESCE(NULLIF(uo.category_name, ''), e.category_name) AS category_name,
                COALESCE(NULLIF(uo.subcategory_slug, ''), e.subcategory_slug) AS subcategory_slug,
                COALESCE(NULLIF(uo.subcategory_name, ''), e.subcategory_name) AS subcategory_name,
                COALESCE(NULLIF(uo.tags_json, ''), e.tags_json) AS tags_json,
                NULL AS language,
                '[]' AS topics_json,
                0 AS stars,
                0 AS forks,
                0 AS watchers,
                0 AS open_issues,
                NULL AS created_at,
                NULL AS pushed_at,
                w.first_seen_at,
                w.last_seen_at,
                NULL AS last_snapshot_at,
                NULL AS snapshot_date,
                NULL AS captured_at,
                e.confidence,
                (pf.id IS NOT NULL) AS is_favorited,
                pf.created_at AS favorited_at,
                (utw.id IS NOT NULL) AS user_added,
                utw.created_at AS user_added_at
            FROM tool_websites w
            LEFT JOIN tool_website_enrichments e ON e.website_id = w.id
            LEFT JOIN user_tool_websites utw
              ON utw.user_id = %s
             AND utw.website_id = w.id
            LEFT JOIN project_favorites pf
              ON pf.user_id = %s
             AND pf.project_source = 'website'
             AND pf.project_id = CAST(w.id AS CHAR)
            LEFT JOIN user_tool_website_overrides uo
              ON uo.user_id = %s
             AND uo.website_id = w.id
            WHERE w.id = %s
            LIMIT 1
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id, user_id, user_id, website_id))
                row = cur.fetchone()
            conn.commit()
            return _normalize_project_row(row) if row else None
        finally:
            conn.close()

    def upsert_user_tool_website_override(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        data = dict(payload)
        user_id = int(data.get("user_id") or 0)
        website_id = int(data.get("website_id") or 0)
        if user_id <= 0 or website_id <= 0:
            raise ValueError("用户或工具网站无效")
        tags = data.get("tags")
        data["tags_json"] = data.get("tags_json") or _json_dumps(tags or [])
        data.setdefault("title", "")
        data.setdefault("description", "")
        data.setdefault("image_url", "")
        data.setdefault("description_zh", "")
        data.setdefault("category_slug", "")
        data.setdefault("category_name", "")
        data.setdefault("subcategory_slug", "")
        data.setdefault("subcategory_name", "")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM user_tool_websites WHERE user_id = %s AND website_id = %s LIMIT 1",
                    (user_id, website_id),
                )
                if not cur.fetchone():
                    raise LookupError("该工具网站不在你的收藏夹中")
                cur.execute(
                    """
                    INSERT INTO user_tool_website_overrides (
                        user_id, website_id, title, description, image_url, description_zh,
                        category_slug, category_name, subcategory_slug, subcategory_name, tags_json
                    ) VALUES (
                        %(user_id)s, %(website_id)s, %(title)s, %(description)s, %(image_url)s, %(description_zh)s,
                        %(category_slug)s, %(category_name)s, %(subcategory_slug)s, %(subcategory_name)s, %(tags_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        title=VALUES(title),
                        description=VALUES(description),
                        image_url=VALUES(image_url),
                        description_zh=VALUES(description_zh),
                        category_slug=VALUES(category_slug),
                        category_name=VALUES(category_name),
                        subcategory_slug=VALUES(subcategory_slug),
                        subcategory_name=VALUES(subcategory_name),
                        tags_json=VALUES(tags_json),
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    data,
                )
                self._repository._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="user_tool_website_overrides",
                    aggregate_key={"user_id": user_id, "website_id": website_id},
                    source_method="upsert_user_tool_website_override",
                )
            conn.commit()
        finally:
            conn.close()
        item = self.get_tool_website_item_for_user(
            user_id=user_id, website_id=website_id
        )
        if not item:
            raise LookupError("工具网站不存在")
        return item

    def list_user_project_collection(
        self, *, user_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self._repository.list_projects(
            user_id=user_id, favorites_only=True, **kwargs
        )

    def get_user_project_categories(
        self,
        *,
        user_id: int,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> dict[str, Any]:
        return self._repository.get_project_categories(
            source=source,
            min_stars=min_stars,
            enriched_only=enriched_only,
            user_id=user_id,
            favorites_only=True,
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
        if source not in {"github", "website"}:
            source = "github"
        status_github = "AND ge.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci" if enriched_only else ""
        status_website = (
            "AND (we.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci OR uo.id IS NOT NULL)"
            if enriched_only
            else ""
        )
        if source == "website":
            sql = f"""
                SELECT COALESCE(NULLIF(uo.tags_json, ''), we.tags_json) AS tags_json
                FROM tool_websites w
                JOIN user_tool_websites utw
                  ON utw.user_id = %s
                 AND utw.website_id = w.id
                LEFT JOIN tool_website_enrichments we ON we.website_id = w.id
                LEFT JOIN user_tool_website_overrides uo
                  ON uo.user_id = %s
                 AND uo.website_id = w.id
                WHERE 1 = 1
                  {status_website}
            """
            params: tuple[Any, ...] = (user_id, user_id)
        else:
            sql = f"""
                SELECT ge.tags_json AS tags_json
                FROM github_repo_candidates c
                JOIN project_favorites pf
                  ON pf.user_id = %s
                 AND pf.project_source = 'github'
                 AND pf.project_id = c.repo_id
                LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                WHERE COALESCE(c.stars, 0) >= %s
                  {status_github}
            """
            params = (user_id, min_stars)

        counts: dict[str, int] = {}
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
        finally:
            conn.close()

        ignored_tags = {"AI 工具", "网页收藏"}
        for row in rows:
            for tag in _json_loads_list(row.get("tags_json")):
                if tag in ignored_tags:
                    continue
                counts[tag] = counts.get(tag, 0) + 1
        items = [
            {"label": label, "count": count}
            for label, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        return {"items": items, "total": len(items), "source": source}
