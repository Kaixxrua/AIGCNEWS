from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.domain.project_taxonomy import ENGLISH_LABEL_BY_SLUG
from backend.app.repositories.postgres_runtime_provider_repository import (
    PostgresRuntimeProviderSettingRepository,
)
from backend.app.repositories.project_catalog_normalization import normalize_project_row


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
    return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def _github_fingerprint(row: dict[str, Any]) -> str:
    source = "\n".join(
        (
            str(row.get("full_name") or ""),
            str(row.get("description") or ""),
            str(row.get("language") or ""),
            str(row.get("topics_json") or ""),
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# 单次爬取运行的富化范围（三重去重，绝不触碰项目库存量）：
# 渠道标记 + first_seen_at 锚点 + 排除已成功富化。CLI 脚本
# scripts/enrich_github_projects_run.py 与本模块共用此片段，保持单一事实源。
_RUN_SCOPE_WHERE = """
    FROM github_repo_candidates c
    WHERE c.source_channels LIKE %s
      AND c.first_seen_at >= %s
      AND COALESCE(c.stars, 0) >= %s
      AND NOT EXISTS (
          SELECT 1 FROM github_repo_enrichments e
          WHERE e.repo_id = c.repo_id AND e.status = 'succeeded'
      )
"""

# 与 _github_fingerprint 等价的 SQL 表达式（refresh_changed 过滤下推用）：
# sha256("\n".join(full_name, description, language, topics_json)) 的 UTF-8 hex。
# 两侧必须保持同一拼接顺序与编码，Python 侧仍保留二次校验兜底。
_FINGERPRINT_SQL = (
    "encode(sha256(convert_to("
    "COALESCE(c.full_name, '') || E'\\n' || "
    "COALESCE(c.description, '') || E'\\n' || "
    "COALESCE(c.language, '') || E'\\n' || "
    "COALESCE(c.topics_json, '')"
    ", 'UTF8')), 'hex')"
)


def _enrichment_eligibility_sql(
    *,
    force: bool,
    retry_failed: bool,
    refresh_changed: bool,
) -> str:
    """候选 eligibility 的 SQL 片段；与 Python 侧二次校验逻辑严格同构。"""
    if force:
        return "TRUE"
    clauses = ["e.repo_id IS NULL"]
    if retry_failed:
        clauses.append("e.status IS DISTINCT FROM 'succeeded'")
    if refresh_changed:
        clauses.append(
            "(e.prompt_version IS DISTINCT FROM %s"
            f" OR e.source_fingerprint IS DISTINCT FROM {_FINGERPRINT_SQL})"
        )
    return "(" + " OR ".join(clauses) + ")"


class _PostgresEnrichmentRepositoryBase:
    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database
        self._runtime_provider_settings: PostgresRuntimeProviderSettingRepository | None = None

    @property
    def runtime_provider_settings(self) -> PostgresRuntimeProviderSettingRepository:
        if self._runtime_provider_settings is None:
            self._runtime_provider_settings = PostgresRuntimeProviderSettingRepository(self._database)
        return self._runtime_provider_settings


class PostgresGitHubProjectEnrichmentRepository(_PostgresEnrichmentRepositoryBase):
    """PostgreSQL writes and worker reads for GitHub project enrichment."""

    def get_github_projects_needing_enrichment(
        self,
        *,
        limit: int = 50,
        min_stars: int = 500,
        prompt_version: str = "v1",
        force: bool = False,
        retry_failed: bool = True,
        refresh_changed: bool = False,
    ) -> list[dict[str, Any]]:
        capped_limit = max(1, min(int(limit or 50), 500))
        eligibility = _enrichment_eligibility_sql(
            force=force,
            retry_failed=retry_failed,
            refresh_changed=refresh_changed,
        )
        # eligibility 与 LIMIT 下推到 SQL：不再对快照表全量 DISTINCT ON 之后
        # 还在 Python 侧扫描全部候选截断；Python 只做二次校验与字段组装。
        params: list[Any] = [min_stars]
        if refresh_changed and not force:
            params.append(prompt_version)
        params.append(capped_limit)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH latest_snap AS (
                        SELECT DISTINCT ON (repo_id) *
                        FROM github_repo_snapshots
                        ORDER BY repo_id, snapshot_date DESC
                    )
                    SELECT c.repo_id, c.full_name, c.title, c.url, c.description,
                           c.language, c.topics_json, c.created_at, c.pushed_at,
                           c.source_channels, c.first_seen_at, c.last_seen_at,
                           c.last_snapshot_at,
                           COALESCE(ls.stars, c.stars, 0) AS stars,
                           COALESCE(ls.forks, c.forks, 0) AS forks,
                           COALESCE(ls.watchers, c.watchers, 0) AS watchers,
                           COALESCE(ls.open_issues, 0) AS open_issues,
                           ls.snapshot_date, ls.captured_at,
                           e.status AS existing_status,
                           e.prompt_version AS existing_prompt_version,
                           e.source_fingerprint AS existing_source_fingerprint
                    FROM github_repo_candidates c
                    LEFT JOIN latest_snap ls ON ls.repo_id = c.repo_id
                    LEFT JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
                    WHERE COALESCE(ls.stars, c.stars, 0) >= %s
                      AND {eligibility}
                    ORDER BY COALESCE(ls.stars, c.stars, 0) DESC,
                             c.full_name COLLATE "C" ASC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()

        # 二次校验：与 SQL 片段同构重算 eligibility，防御两侧口径漂移
        selected: list[dict[str, Any]] = []
        for source_row in rows:
            row = dict(source_row)
            fingerprint = _github_fingerprint(row)
            missing = row.get("existing_status") is None
            stale = force or missing
            if not stale and retry_failed:
                stale = row.get("existing_status") != "succeeded"
            if not stale and refresh_changed:
                stale = (
                    row.get("existing_prompt_version") != prompt_version
                    or row.get("existing_source_fingerprint") != fingerprint
                )
            if not stale:
                continue
            for key in ("existing_status", "existing_prompt_version", "existing_source_fingerprint"):
                row.pop(key, None)
            row["source_fingerprint"] = fingerprint
            selected.append(normalize_project_row(row))
            if len(selected) >= capped_limit:
                break
        return selected

    def _canonical_repo_id(self, cursor: Any, repo_id: str) -> str:
        clean_id = str(repo_id or "").strip()
        cursor.execute(
            """
            SELECT canonical_repo_id
            FROM github_repo_aliases
            WHERE alias_repo_id = %s
            LIMIT 1
            """,
            (clean_id,),
        )
        row = cursor.fetchone()
        return str(row["canonical_repo_id"]) if row else clean_id

    def upsert_github_repo_enrichment(self, payload: dict[str, Any]) -> None:
        now = _utcnow()
        data = dict(payload)
        data.setdefault("tags_json", json.dumps(data.get("tags") or [], ensure_ascii=False))
        data.setdefault("tags_zh_json", data["tags_json"])
        data.setdefault("tags_en_json", None)
        data.setdefault("description_en", "")
        data["subcategory_slug"] = data.get("subcategory_slug") or ""
        data["subcategory_name"] = data.get("subcategory_name_zh") or data.get("subcategory_name") or ""
        data["category_name_zh"] = data.get("category_name_zh") or data.get("category_name") or ""
        data["category_name_en"] = data.get("category_name_en") or ENGLISH_LABEL_BY_SLUG.get(str(data.get("category_slug") or ""), "Other")
        data["subcategory_name_zh"] = data.get("subcategory_name_zh") or data["subcategory_name"]
        data["subcategory_name_en"] = data.get("subcategory_name_en") or ENGLISH_LABEL_BY_SLUG.get(data["subcategory_slug"], "Uncategorized")
        data["category_name"] = data["category_name_zh"]
        data.setdefault("confidence", 0.0)
        data.setdefault("model_provider", "")
        data.setdefault("model_name", "")
        data.setdefault("status", "succeeded")
        data.setdefault("error_msg", None)
        data.setdefault("enriched_at", now)
        data.setdefault("updated_at", now)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                data["repo_id"] = self._canonical_repo_id(cursor, str(data.get("repo_id") or ""))
                cursor.execute(
                    """
                    INSERT INTO github_repo_enrichments (
                        repo_id, category_slug, category_name, category_name_zh, category_name_en,
                        subcategory_slug, subcategory_name, subcategory_name_zh, subcategory_name_en,
                        description_zh, tags_json, tags_zh_json, tags_en_json, confidence,
                        source_fingerprint, prompt_version, model_provider, model_name,
                        status, error_msg, enriched_at, updated_at
                    ) VALUES (
                        %(repo_id)s, %(category_slug)s, %(category_name)s,
                        %(category_name_zh)s, %(category_name_en)s, %(subcategory_slug)s,
                        %(subcategory_name)s, %(subcategory_name_zh)s, %(subcategory_name_en)s, %(description_zh)s,
                        %(tags_json)s, %(tags_zh_json)s, %(tags_en_json)s, %(confidence)s, %(source_fingerprint)s,
                        %(prompt_version)s, %(model_provider)s, %(model_name)s,
                        %(status)s, %(error_msg)s, %(enriched_at)s, %(updated_at)s
                    )
                    ON CONFLICT (repo_id) DO UPDATE SET
                        category_slug=EXCLUDED.category_slug,
                        category_name=EXCLUDED.category_name,
                        category_name_zh=EXCLUDED.category_name_zh,
                        category_name_en=EXCLUDED.category_name_en,
                        subcategory_slug=EXCLUDED.subcategory_slug,
                        subcategory_name=EXCLUDED.subcategory_name,
                        subcategory_name_zh=EXCLUDED.subcategory_name_zh,
                        subcategory_name_en=EXCLUDED.subcategory_name_en,
                        description_zh=EXCLUDED.description_zh,
                        tags_json=EXCLUDED.tags_json,
                        tags_zh_json=EXCLUDED.tags_zh_json,
                        tags_en_json=EXCLUDED.tags_en_json,
                        confidence=EXCLUDED.confidence,
                        source_fingerprint=EXCLUDED.source_fingerprint,
                        prompt_version=EXCLUDED.prompt_version,
                        model_provider=EXCLUDED.model_provider,
                        model_name=EXCLUDED.model_name,
                        status=EXCLUDED.status,
                        error_msg=EXCLUDED.error_msg,
                        enriched_at=EXCLUDED.enriched_at,
                        updated_at=EXCLUDED.updated_at
                    """,
                    data,
                )

    def list_github_projects_needing_bilingual_tags(
        self, *, after_repo_id: str = "", limit: int = 50, min_stars: int = 500,
    ) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.repo_id, c.full_name, c.description, c.language,
                           c.topics_json, c.stars, e.tags_json, e.tags_zh_json,
                           e.description_zh, e.source_fingerprint
                    FROM github_repo_candidates c
                    JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
                    LEFT JOIN github_repo_aliases a ON a.alias_repo_id = c.repo_id
                    WHERE c.repo_id > %s
                      AND COALESCE(c.stars, 0) >= %s
                      AND e.status = 'succeeded'
                      AND COALESCE(e.tags_en_json, '') = ''
                      AND a.alias_repo_id IS NULL
                    ORDER BY c.repo_id COLLATE "C" ASC
                    LIMIT %s
                    """,
                    (str(after_repo_id or ""), max(0, int(min_stars)), max(1, min(int(limit), 500))),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def update_github_repo_system_tags(
        self, *, repo_id: str, tags_zh_json: str, tags_en_json: str,
        prompt_version: str, model_provider: str = "", model_name: str = "",
    ) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                canonical_id = self._canonical_repo_id(cursor, str(repo_id or ""))
                cursor.execute(
                    """
                    UPDATE github_repo_enrichments
                    SET tags_json=%s, tags_zh_json=%s, tags_en_json=%s,
                        prompt_version=%s, model_provider=%s, model_name=%s,
                        updated_at=%s
                    WHERE repo_id=%s AND status='succeeded'
                    """,
                    (tags_zh_json, tags_zh_json, tags_en_json, prompt_version,
                     model_provider, model_name, _utcnow(), canonical_id),
                )

    def mark_github_repo_enrichment_failed(
        self, repo_id: str, *, source_fingerprint: str, prompt_version: str,
        error_msg: str, model_provider: str = "", model_name: str = "",
    ) -> None:
        self.upsert_github_repo_enrichment({
            "repo_id": repo_id, "category_slug": "other", "category_name": "其他",
            "subcategory_slug": "other_uncategorized", "subcategory_name": "未分类",
            "description_zh": "", "tags_json": "[]", "confidence": 0.0,
            "source_fingerprint": source_fingerprint, "prompt_version": prompt_version,
            "model_provider": model_provider, "model_name": model_name,
            "status": "failed", "error_msg": error_msg[:2000],
        })

    def get_github_project_enrichment_status(self, *, min_stars: int = 500) -> dict[str, Any]:
        base = """
            WITH latest_snap AS (
                SELECT DISTINCT ON (repo_id) * FROM github_repo_snapshots
                ORDER BY repo_id, snapshot_date DESC
            ), eligible AS (
                SELECT c.repo_id, e.status, e.category_slug, e.category_name
                FROM github_repo_candidates c
                LEFT JOIN latest_snap ls ON ls.repo_id=c.repo_id
                LEFT JOIN github_repo_enrichments e ON e.repo_id=c.repo_id
                WHERE COALESCE(ls.stars,c.stars,0) >= %s
            )
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(base + """SELECT COUNT(*) AS eligible,
                    COUNT(*) FILTER (WHERE status='succeeded') AS succeeded,
                    COUNT(*) FILTER (WHERE status='failed') AS failed FROM eligible""", (min_stars,))
                row = cursor.fetchone() or {}
                cursor.execute(base + """SELECT category_slug AS slug, category_name AS name,
                    COUNT(*) AS count FROM eligible WHERE status='succeeded'
                    GROUP BY category_slug, category_name
                    ORDER BY count DESC, category_name COLLATE "C" ASC""", (min_stars,))
                categories = cursor.fetchall()
        eligible = int(row.get("eligible") or 0)
        succeeded = int(row.get("succeeded") or 0)
        failed = int(row.get("failed") or 0)
        return {"eligible": eligible, "succeeded": succeeded, "failed": failed,
                "pending": max(eligible - succeeded - failed, 0),
                "by_category": [{"slug": item.get("slug") or "other",
                                 "name": item.get("name") or "其他",
                                 "count": int(item.get("count") or 0)} for item in categories]}

    def count_github_run_enrichment_candidates(
        self, *, channel: str, first_seen_after: str, min_stars: int = 500
    ) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS n" + _RUN_SCOPE_WHERE,
                    (f"%{channel}%", first_seen_after, min_stars),
                )
                row = cursor.fetchone()
                return int(row["n"] if row else 0)

    def list_github_run_enrichment_candidates(
        self,
        *,
        channel: str,
        first_seen_after: str,
        min_stars: int = 500,
        after_repo_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按 repo_id 键集分页取本次运行范围内的候选，附富化所需指纹与规范化字段。"""
        capped_limit = max(1, min(int(limit or 200), 500))
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.repo_id, c.full_name, c.title, c.url, c.description,
                           c.language, c.topics_json, c.created_at, c.pushed_at,
                           c.source_channels, c.first_seen_at, c.last_seen_at,
                           c.last_snapshot_at,
                           COALESCE(c.stars, 0) AS stars,
                           COALESCE(c.forks, 0) AS forks,
                           COALESCE(c.watchers, 0) AS watchers
                    """
                    + _RUN_SCOPE_WHERE
                    + "  AND c.repo_id > %s ORDER BY c.repo_id LIMIT %s",
                    (f"%{channel}%", first_seen_after, min_stars, after_repo_id, capped_limit),
                )
                rows = cursor.fetchall()

        selected: list[dict[str, Any]] = []
        for source_row in rows:
            row = dict(source_row)
            row["source_fingerprint"] = _github_fingerprint(row)
            selected.append(normalize_project_row(row))
        return selected

    def get_github_run_crawl_status(
        self, *, channel: str, first_seen_after: str, min_stars: int = 500
    ) -> dict[str, Any]:
        """本次运行的实时计数：分母固定、富化分子爬升，供运维页轮询进度。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS candidates_upserted,
                           COUNT(*) FILTER (WHERE COALESCE(c.stars, 0) >= %s) AS scope_total,
                           COUNT(*) FILTER (WHERE COALESCE(c.stars, 0) >= %s AND e.status = 'succeeded') AS enriched_succeeded,
                           COUNT(*) FILTER (WHERE COALESCE(c.stars, 0) >= %s AND e.status = 'failed') AS enriched_failed
                    FROM github_repo_candidates c
                    LEFT JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
                    WHERE c.source_channels LIKE %s AND c.first_seen_at >= %s
                    """,
                    (min_stars, min_stars, min_stars, f"%{channel}%", first_seen_after),
                )
                row = cursor.fetchone() or {}
        return {
            "candidates_upserted": int(row.get("candidates_upserted") or 0),
            "scope_total": int(row.get("scope_total") or 0),
            "enriched_succeeded": int(row.get("enriched_succeeded") or 0),
            "enriched_failed": int(row.get("enriched_failed") or 0),
        }


class PostgresToolWebsiteEnrichmentRepository(_PostgresEnrichmentRepositoryBase):
    """PostgreSQL canonical website metadata and enrichment persistence."""

    def get_tool_website_by_hash(self, normalized_url_hash: str) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM tool_websites WHERE normalized_url_hash=%s LIMIT 1", (normalized_url_hash,))
                row = cursor.fetchone()
        return dict(row) if row else None

    def upsert_tool_website(self, payload: dict[str, Any], *, update_existing: bool = True) -> dict[str, Any]:
        now = _utcnow()
        data = dict(payload)
        for key, default in (("title", ""), ("description", ""), ("image_url", ""),
                             ("raw_metadata_json", "{}"), ("fetch_status", "succeeded")):
            data.setdefault(key, default)
        data.setdefault("fetch_error", None)
        visibility = str(data.get("visibility") or "public").strip().lower()
        data["visibility"] = visibility if visibility in {"public", "private"} else "public"
        data.setdefault("added_by_user_id", None)
        data.setdefault("first_seen_at", now)
        data.setdefault("last_seen_at", now)
        data.setdefault("updated_at", now)
        if update_existing:
            updates = """canonical_url=EXCLUDED.canonical_url, domain=EXCLUDED.domain,
                title=COALESCE(NULLIF(EXCLUDED.title,''),tool_websites.title),
                description=COALESCE(NULLIF(EXCLUDED.description,''),tool_websites.description),
                image_url=COALESCE(NULLIF(EXCLUDED.image_url,''),tool_websites.image_url),
                raw_metadata_json=EXCLUDED.raw_metadata_json, fetch_status=EXCLUDED.fetch_status,
                fetch_error=EXCLUDED.fetch_error, source_fingerprint=EXCLUDED.source_fingerprint,
                visibility=CASE WHEN tool_websites.visibility='public' OR EXCLUDED.visibility='public'
                    THEN 'public' ELSE 'private' END,
                last_seen_at=EXCLUDED.last_seen_at, updated_at=EXCLUDED.updated_at"""
        else:
            updates = "last_seen_at=EXCLUDED.last_seen_at, updated_at=EXCLUDED.updated_at"
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    INSERT INTO tool_websites (canonical_url,normalized_url_hash,domain,title,
                        description,image_url,raw_metadata_json,fetch_status,fetch_error,
                        source_fingerprint,visibility,added_by_user_id,first_seen_at,last_seen_at,updated_at)
                    VALUES (%(canonical_url)s,%(normalized_url_hash)s,%(domain)s,%(title)s,
                        %(description)s,%(image_url)s,%(raw_metadata_json)s,%(fetch_status)s,
                        %(fetch_error)s,%(source_fingerprint)s,%(visibility)s,%(added_by_user_id)s,
                        %(first_seen_at)s,%(last_seen_at)s,%(updated_at)s)
                    ON CONFLICT (normalized_url_hash) DO UPDATE SET {updates}
                    RETURNING *
                """, data)
                row = cursor.fetchone() or {}
        return dict(row)

    def list_tool_websites_needing_bilingual_enrichment(
        self, *, after_website_id: int = 0, limit: int = 50,
        prompt_version: str = "v1", retry_failed: bool = True,
    ) -> list[dict[str, Any]]:
        retry_filter = "" if retry_failed else "AND (e.status IS NULL OR e.status != 'failed')"
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT w.id AS website_id, w.canonical_url, w.domain, w.title,
                           w.description, w.image_url, w.raw_metadata_json, w.source_fingerprint
                    FROM tool_websites w
                    LEFT JOIN tool_website_enrichments e ON e.website_id = w.id
                    WHERE w.id > %s
                      AND (e.website_id IS NULL OR e.prompt_version NOT LIKE %s
                           OR COALESCE(e.description_en, '') = '')
                      {retry_filter}
                    ORDER BY w.id ASC LIMIT %s
                """, (max(0, int(after_website_id)), f"{prompt_version}%", max(1, min(int(limit), 500))))
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_tool_website_enrichment(self, website_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM tool_website_enrichments WHERE website_id=%s LIMIT 1", (website_id,))
                row = cursor.fetchone()
        return dict(row) if row else None

    def get_tool_website_item(self, website_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 'website:' || w.id AS id, 'website' AS source, NULL AS repo_id,
                        w.id AS website_id, COALESCE(NULLIF(w.title,''),w.domain) AS full_name,
                        w.title, w.canonical_url AS url, w.domain,
                        COALESCE(NULLIF(w.image_url,''), split_part(w.canonical_url,'/',1) || '//' || split_part(w.canonical_url,'/',3) || '/favicon.ico') AS image_url,
                        w.description, e.description_zh, e.description_en, e.category_slug, e.category_name,
                        e.category_name_zh, e.category_name_en, e.subcategory_slug, e.subcategory_name,
                        e.subcategory_name_zh, e.subcategory_name_en, e.tags_json,
                        e.tags_zh_json, e.tags_en_json, 'system' AS tags_origin,
                        NULL AS language, '[]' AS topics_json, 0 AS stars, 0 AS forks,
                        0 AS watchers, 0 AS open_issues, NULL AS created_at, NULL AS pushed_at,
                        w.first_seen_at, w.last_seen_at, NULL AS last_snapshot_at,
                        NULL AS snapshot_date, NULL AS captured_at, e.confidence,
                        FALSE AS is_favorited, NULL AS favorited_at, FALSE AS user_added,
                        NULL AS user_added_at
                    FROM tool_websites w LEFT JOIN tool_website_enrichments e ON e.website_id=w.id
                    WHERE w.id=%s LIMIT 1
                """, (website_id,))
                row = cursor.fetchone()
        return normalize_project_row(dict(row)) if row else None

    def upsert_tool_website_enrichment(self, payload: dict[str, Any]) -> None:
        now = _utcnow()
        data = dict(payload)
        data.setdefault("tags_json", json.dumps(data.get("tags") or [], ensure_ascii=False))
        data.setdefault("tags_zh_json", data["tags_json"])
        data.setdefault("tags_en_json", None)
        data.setdefault("description_en", "")
        data["subcategory_slug"] = data.get("subcategory_slug") or ""
        data["subcategory_name"] = data.get("subcategory_name_zh") or data.get("subcategory_name") or ""
        data["category_name_zh"] = data.get("category_name_zh") or data.get("category_name") or ""
        data["category_name_en"] = data.get("category_name_en") or ENGLISH_LABEL_BY_SLUG.get(str(data.get("category_slug") or ""), "Other")
        data["subcategory_name_zh"] = data.get("subcategory_name_zh") or data["subcategory_name"]
        data["subcategory_name_en"] = data.get("subcategory_name_en") or ENGLISH_LABEL_BY_SLUG.get(data["subcategory_slug"], "Uncategorized")
        data["category_name"] = data["category_name_zh"]
        for key, default in (("confidence", 0.0), ("model_provider", ""),
                             ("model_name", ""), ("status", "succeeded"),
                             ("error_msg", None), ("enriched_at", now), ("updated_at", now)):
            data.setdefault(key, default)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO tool_website_enrichments (website_id,category_slug,category_name,
                        category_name_zh,category_name_en,subcategory_slug,subcategory_name,
                        subcategory_name_zh,subcategory_name_en,description_zh,description_en,
                        tags_json,tags_zh_json,tags_en_json,confidence,
                        source_fingerprint,prompt_version,model_provider,model_name,status,error_msg,enriched_at,updated_at)
                    VALUES (%(website_id)s,%(category_slug)s,%(category_name)s,%(category_name_zh)s,
                        %(category_name_en)s,%(subcategory_slug)s,%(subcategory_name)s,
                        %(subcategory_name_zh)s,%(subcategory_name_en)s,%(description_zh)s,
                        %(description_en)s,%(tags_json)s,%(tags_zh_json)s,%(tags_en_json)s,%(confidence)s,
                        %(source_fingerprint)s,%(prompt_version)s,%(model_provider)s,%(model_name)s,
                        %(status)s,%(error_msg)s,%(enriched_at)s,%(updated_at)s)
                    ON CONFLICT (website_id) DO UPDATE SET category_slug=EXCLUDED.category_slug,
                        category_name=EXCLUDED.category_name,category_name_zh=EXCLUDED.category_name_zh,
                        category_name_en=EXCLUDED.category_name_en,subcategory_slug=EXCLUDED.subcategory_slug,
                        subcategory_name=EXCLUDED.subcategory_name,subcategory_name_zh=EXCLUDED.subcategory_name_zh,
                        subcategory_name_en=EXCLUDED.subcategory_name_en,description_zh=EXCLUDED.description_zh,
                        description_en=EXCLUDED.description_en,
                        tags_json=EXCLUDED.tags_json,tags_zh_json=EXCLUDED.tags_zh_json,
                        tags_en_json=EXCLUDED.tags_en_json,confidence=EXCLUDED.confidence,
                        source_fingerprint=EXCLUDED.source_fingerprint,prompt_version=EXCLUDED.prompt_version,
                        model_provider=EXCLUDED.model_provider,model_name=EXCLUDED.model_name,
                        status=EXCLUDED.status,error_msg=EXCLUDED.error_msg,
                        enriched_at=EXCLUDED.enriched_at,updated_at=EXCLUDED.updated_at
                """, data)

    def list_tool_websites_needing_bilingual_tags(
        self, *, after_website_id: int = 0, limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT w.id AS website_id, w.canonical_url, w.domain, w.title,
                           w.description, w.image_url, w.raw_metadata_json,
                           w.source_fingerprint, e.tags_json, e.tags_zh_json,
                           e.description_zh
                    FROM tool_websites w
                    JOIN tool_website_enrichments e ON e.website_id = w.id
                    WHERE w.id > %s
                      AND e.status = 'succeeded'
                      AND COALESCE(e.tags_en_json, '') = ''
                      AND e.prompt_version NOT LIKE '%%-manual'
                    ORDER BY w.id ASC
                    LIMIT %s
                    """,
                    (max(0, int(after_website_id)), max(1, min(int(limit), 500))),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def update_tool_website_system_tags(
        self, *, website_id: int, tags_zh_json: str, tags_en_json: str,
        prompt_version: str, model_provider: str = "", model_name: str = "",
    ) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tool_website_enrichments
                    SET tags_json=%s, tags_zh_json=%s, tags_en_json=%s,
                        prompt_version=%s, model_provider=%s, model_name=%s,
                        updated_at=%s
                    WHERE website_id=%s AND status='succeeded'
                      AND prompt_version NOT LIKE '%%-manual'
                    """,
                    (tags_zh_json, tags_zh_json, tags_en_json, prompt_version,
                     model_provider, model_name, _utcnow(), int(website_id)),
                )

    def mark_tool_website_enrichment_failed(
        self, website_id: int, *, source_fingerprint: str, prompt_version: str,
        error_msg: str, model_provider: str = "", model_name: str = "",
    ) -> None:
        self.upsert_tool_website_enrichment({
            "website_id": website_id, "category_slug": "other", "category_name": "其他",
            "subcategory_slug": "other_uncategorized", "subcategory_name": "未分类",
            "description_zh": "", "tags_json": "[]", "confidence": 0.0,
            "source_fingerprint": source_fingerprint, "prompt_version": prompt_version,
            "model_provider": model_provider, "model_name": model_name,
            "status": "failed", "error_msg": error_msg[:2000],
        })
