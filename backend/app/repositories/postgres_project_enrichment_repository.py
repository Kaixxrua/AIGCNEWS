from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.domain.project_taxonomy import (
    ENGLISH_LABEL_BY_SLUG,
    RAW_DESCRIPTION_ENGLISH_MIN_CHARS,
    raw_description_needs_english,
)
from backend.app.repositories.postgres_runtime_provider_repository import (
    PostgresRuntimeProviderSettingRepository,
)
from backend.app.repositories.project_catalog_normalization import normalize_project_row
from backend.app.services.dashboard import live_stats_broadcaster


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
    # README 只有成功快照才参与指纹；限流/失败/不存在时使用空 hash，
    # 避免一次临时抓取故障把已成功富化项目反复标成 changed。
    readme_sha256 = (
        str(row.get("readme_sha256") or "")
        if str(row.get("readme_status") or "") == "succeeded"
        else ""
    )
    source = "\n".join(
        (
            str(row.get("full_name") or ""),
            str(row.get("description") or ""),
            str(row.get("language") or ""),
            str(row.get("topics_json") or ""),
            readme_sha256,
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# README 只有成功且清洗后非空的快照才是富化输入；生成的 description_zh/
# description_en 不参与输入判定，避免把模型产物误当成源材料。
_GITHUB_ENRICHMENT_INPUT_SQL = """
    (
        BTRIM(COALESCE(c.description, '')) <> ''
        OR (
            ss.readme_status = 'succeeded'
            AND BTRIM(COALESCE(ss.readme_text, '')) <> ''
        )
    )
"""


def _has_github_enrichment_input(row: dict[str, Any]) -> bool:
    """Return whether a candidate has a usable description or README snapshot."""
    if str(row.get("description") or "").strip():
        return True
    return (
        str(row.get("readme_status") or "") == "succeeded"
        and bool(str(row.get("readme_text") or "").strip())
    )


# 单次爬取运行的富化范围（三重去重，绝不触碰项目库存量）：
# 单次爬取运行的富化范围（三重去重，绝不触碰项目库存量）：
# 渠道标记 + first_seen_at 锚点 + 排除已成功富化。CLI 脚本
# scripts/enrich_github_projects_run.py 与本模块共用此片段，保持单一事实源。
# 改名墓碑行同样排除（定义在下方 _ALIAS_TOMBSTONE_EXCLUSION_SQL 之后）。
# 与 _github_fingerprint 等价的 SQL 表达式（refresh_changed 过滤下推用）：
# sha256("\n".join(full_name, description, language, topics_json, readme_sha256))。
# 只有 succeeded README 快照的 hash 参与；两侧必须保持同一拼接顺序与编码。
_FINGERPRINT_SQL = (
    "encode(sha256(convert_to("
    "COALESCE(c.full_name, '') || E'\\n' || "
    "COALESCE(c.description, '') || E'\\n' || "
    "COALESCE(c.language, '') || E'\\n' || "
    "COALESCE(c.topics_json, '') || E'\\n' || "
    "CASE WHEN ss.readme_status = 'succeeded' "
    "THEN COALESCE(ss.readme_sha256, '') ELSE '' END"
    ", 'UTF8')), 'hex')"
)

# 改名墓碑行排除：repo 改名后旧名候选行保留（github_repo_aliases 记录
# 旧名→新名映射），富化写入侧经 _canonical_repo_id 归一到新名行落库，
# 旧名行永远等不到自己名下的富化记录。若不排除，旧名行会被反复圈选、
# 白烧模型调用，且待处理计数永远清不零。与目录读取侧
# postgres_project_catalog 的别名过滤语义一致。
_ALIAS_TOMBSTONE_EXCLUSION_SQL = """
    NOT EXISTS (
        SELECT 1 FROM github_repo_aliases ga
        WHERE ga.alias_repo_id = c.repo_id
          AND ga.canonical_repo_id <> c.repo_id
    )
"""

_RUN_SCOPE_WHERE = f"""
    FROM github_repo_candidates c
    LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
    WHERE c.source_channels LIKE %s
      AND c.first_seen_at >= %s
      AND COALESCE(c.stars, 0) >= %s
      AND {_GITHUB_ENRICHMENT_INPUT_SQL}
      AND {_ALIAS_TOMBSTONE_EXCLUSION_SQL}
      AND NOT EXISTS (
          SELECT 1 FROM github_repo_enrichments e
          WHERE e.repo_id = c.repo_id AND e.status = 'succeeded'
      )
"""


def _enrichment_eligibility_sql(
    *,
    force: bool,
    retry_failed: bool,
    refresh_changed: bool,
) -> str:
    """候选 eligibility 的 SQL 片段；与 Python 侧二次校验逻辑严格同构。"""
    if force:
        return "TRUE"

    # 普通补跑只消费真正没有富化记录的候选；失败记录仅在显式开启
    # retry_failed 时进入。历史 succeeded 行的双语/fingerprint 修复属于
    # refresh_changed 专用路径，不能因为一次指纹策略升级挤占新项目队列。
    clauses = ["e.repo_id IS NULL"]
    if retry_failed:
        clauses.append("e.status IS DISTINCT FROM 'succeeded'")
    if refresh_changed:
        clauses.append(
            "(e.status = 'succeeded' AND ("
            "COALESCE(BTRIM(e.description_zh), '') = '' OR "
            "COALESCE(BTRIM(e.description_en), '') = '' OR "
            f"e.source_fingerprint IS DISTINCT FROM {_FINGERPRINT_SQL} OR "
            "e.prompt_version IS DISTINCT FROM %s))"
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
        # latest_snap 必须 MATERIALIZED：内联展开时，规划器对外层行数低估会把
        # DISTINCT ON 全索引扫描塞进嵌套循环内层（每个外层行重扫整份快照索引），
        # 生产上曾因此把候选拉取打出 statement_timeout 并中断每日流水线富化阶段；
        # 物化保证快照单次扫表、代价有界（结果集语义不变）。
        params: list[Any] = [min_stars]
        if refresh_changed and not force:
            params.append(prompt_version)
        params.append(capped_limit)
        priority_order = "" if force or not retry_failed else """
                             CASE
                                 WHEN e.repo_id IS NULL THEN 0
                                 WHEN e.status IS DISTINCT FROM 'succeeded' THEN 1
                                 ELSE 2
                             END ASC,
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH latest_snap AS MATERIALIZED (
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
                           ss.readme_text, ss.readme_sha256, ss.readme_status,
                           e.status AS existing_status,
                           e.prompt_version AS existing_prompt_version,
                           e.source_fingerprint AS existing_source_fingerprint,
                           e.description_zh AS existing_description_zh,
                           e.description_en AS existing_description_en,
                           ss.readme_text, ss.readme_sha256, ss.readme_status
                    FROM github_repo_candidates c
                    LEFT JOIN latest_snap ls ON ls.repo_id = c.repo_id
                    LEFT JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
                    LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
                    WHERE (
                            COALESCE(ls.stars, c.stars, 0) >= %s
                            OR e.status = 'succeeded'
                          )
                      AND {_GITHUB_ENRICHMENT_INPUT_SQL}
                      AND {_ALIAS_TOMBSTONE_EXCLUSION_SQL}
                      AND {eligibility}
                    ORDER BY {priority_order}
                             COALESCE(ls.stars, c.stars, 0) DESC,
                             c.full_name COLLATE "C" ASC,
                             c.repo_id COLLATE "C" ASC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()

        # 二次校验：与 SQL 片段同构重算 eligibility，防御两侧口径漂移
        selected: list[dict[str, Any]] = []
        for source_row in rows:
            row = dict(source_row)
            if not _has_github_enrichment_input(row):
                continue
            fingerprint = _github_fingerprint(row)
            status = str(row.get("existing_status") or "")
            missing = row.get("existing_status") is None
            stale = force or missing
            if not stale and retry_failed:
                stale = status != "succeeded"
            if not stale and refresh_changed and status == "succeeded":
                stale = (
                    not str(row.get("existing_description_zh") or "").strip()
                    or not str(row.get("existing_description_en") or "").strip()
                    or row.get("existing_source_fingerprint") != fingerprint
                    or row.get("existing_prompt_version") != prompt_version
                )
            if not stale:
                continue
            for key in (
                "existing_status",
                "existing_prompt_version",
                "existing_source_fingerprint",
                "existing_description_zh",
                "existing_description_en",
            ):
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
                        description_zh, description_en, tags_json, tags_zh_json, tags_en_json, confidence,
                        source_fingerprint, prompt_version, model_provider, model_name,
                        status, error_msg, enriched_at, updated_at
                    ) VALUES (
                        %(repo_id)s, %(category_slug)s, %(category_name)s,
                        %(category_name_zh)s, %(category_name_en)s, %(subcategory_slug)s,
                        %(subcategory_name)s, %(subcategory_name_zh)s, %(subcategory_name_en)s, %(description_zh)s,
                        %(description_en)s,
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
                        description_en=EXCLUDED.description_en,
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
        # 富化状态落库（succeeded/failed 均走本方法）→ 首页 GitHub 计数投影
        # 变更；notify 线程安全（富化批处理在 worker 线程池执行），未装配 no-op。
        live_stats_broadcaster.notify_live_stats_changed("github-enrichment-upsert")

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

    def list_github_projects_needing_english_description(
        self, *, after_repo_id: str = "", limit: int = 200,
    ) -> list[dict[str, Any]]:
        """圈选已富化成功、尚无英文策展描述、且原生描述不足以服务英文读者的项目。

        SQL 预过滤（空/过短/含任一 CJK，含任一即捞）放宽到超集，精确口径由
        Python 侧 raw_description_needs_english 二次校验（沿用本模块
        "SQL 下推 + Python 同构复核"惯例）；为满足键集分页语义，循环扫原始页
        直到选满 limit 或原始结果耗尽，保证 len(返回值)==limit 当且仅当可能还有更多。
        """
        capped_limit = max(1, min(int(limit or 200), 500))
        # chr(13312)/chr(40959) 即 project_taxonomy.CJK_PATTERN 区间 [㐀-鿿] 的端点。
        prefilter = f"""
              AND (
                  COALESCE(NULLIF(btrim(c.description), ''), NULL) IS NULL
                  OR char_length(btrim(c.description)) < {RAW_DESCRIPTION_ENGLISH_MIN_CHARS}
                  OR c.description ~ ('[' || chr(13312) || '-' || chr(40959) || ']')
              )
        """
        selected: list[dict[str, Any]] = []
        cursor = str(after_repo_id or "")
        while len(selected) < capped_limit:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor_obj:
                    cursor_obj.execute(
                        """
                        SELECT c.repo_id, c.full_name, c.description, c.language,
                               c.topics_json, c.stars, e.source_fingerprint
                        FROM github_repo_candidates c
                        JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
                        LEFT JOIN github_repo_aliases a ON a.alias_repo_id = c.repo_id
                        WHERE c.repo_id > %s
                          AND e.status = 'succeeded'
                          AND COALESCE(e.description_en, '') = ''
                          AND a.alias_repo_id IS NULL
                        """
                        + prefilter
                        + """
                        ORDER BY c.repo_id COLLATE "C" ASC
                        LIMIT %s
                        """,
                        (cursor, capped_limit),
                    )
                    rows = cursor_obj.fetchall()
            if not rows:
                break
            cursor = str(rows[-1]["repo_id"])
            for source_row in rows:
                row = dict(source_row)
                if raw_description_needs_english(row.get("description")):
                    selected.append(row)
                    if len(selected) >= capped_limit:
                        break
            if len(rows) < capped_limit:
                break
        return selected

    def update_github_repo_description_en(
        self, *, repo_id: str, description_en: str,
        prompt_version: str, model_provider: str = "", model_name: str = "",
    ) -> None:
        """只更新英文策展描述（+版本/模型元数据），不动中文文案与分类标签。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                canonical_id = self._canonical_repo_id(cursor, str(repo_id or ""))
                cursor.execute(
                    """
                    UPDATE github_repo_enrichments
                    SET description_en=%s, prompt_version=%s, model_provider=%s, model_name=%s,
                        updated_at=%s
                    WHERE repo_id=%s AND status='succeeded'
                    """,
                    (description_en, prompt_version, model_provider, model_name,
                     _utcnow(), canonical_id),
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
        # Keep queue progress separate from historical generated content. The latter
        # intentionally has no current-star or source-input gate.
        # catalog 分类契约：succeeded 恒优先；此外凡当前无富化输入（简介为空且无
        # 有效 README 快照）一律归 unprocessable——不论仓库是否已 404 下架、是否
        # 留有 failed 行。failed/pending 只统计有输入、真正可再跑的项目。该口径
        # 纯派生、可自愈：活仓补齐简介或 README bootstrap 成功即回到 pending，
        # 被下一轮流水线自动拉起。
        # latest_snap 只取候选仓的最新快照：LATERAL 让每仓走 (repo_id, snapshot_date)
        # 唯一索引的一次组内反向扫描 + 单次回表（25k 探针），取代对 64 万行快照表
        # 全量回表读出再排序去重。MATERIALIZED 保持单次物化、代价有界（理由见
        # get_github_projects_needing_enrichment 的事故注释）；下游一律
        # LEFT JOIN latest_snap ON ls.repo_id = c.repo_id，语义与旧写法的
        # 连接结果完全一致（快照表有 (repo_id, snapshot_date) 唯一约束，无并列）。
        base = f"""
            WITH latest_snap AS MATERIALIZED (
                SELECT s.*
                FROM github_repo_candidates c
                CROSS JOIN LATERAL (
                    SELECT *
                    FROM github_repo_snapshots s
                    WHERE s.repo_id = c.repo_id
                    ORDER BY s.snapshot_date DESC
                    LIMIT 1
                ) s
            ), eligible AS (
                SELECT c.repo_id, c.full_name, c.url, c.description,
                       COALESCE(ls.stars,c.stars,0) AS stars,
                       e.status, e.category_slug, e.category_name
                FROM github_repo_candidates c
                LEFT JOIN latest_snap ls ON ls.repo_id=c.repo_id
                LEFT JOIN github_repo_enrichments e ON e.repo_id=c.repo_id
                LEFT JOIN github_project_semantic_sources ss ON ss.repo_id=c.repo_id
                WHERE (COALESCE(ls.stars,c.stars,0) >= %s OR e.status = 'succeeded')
                  AND {_GITHUB_ENRICHMENT_INPUT_SQL}
                  AND {_ALIAS_TOMBSTONE_EXCLUSION_SQL}
            ), catalog AS (
                SELECT c.repo_id, c.full_name, c.url,
                       COALESCE(ls.stars,c.stars,0) AS stars,
                       e.status, e.category_slug, e.category_name,
                       CASE
                         WHEN e.status = 'succeeded' THEN 'succeeded'
                         WHEN BTRIM(COALESCE(c.description, '')) = ''
                              AND NOT (ss.readme_status = 'succeeded'
                                       AND BTRIM(COALESCE(ss.readme_text, '')) <> '')
                           THEN 'unprocessable'
                         WHEN e.status = 'failed' THEN 'failed'
                         ELSE 'pending'
                       END AS state
                FROM github_repo_candidates c
                LEFT JOIN latest_snap ls ON ls.repo_id=c.repo_id
                LEFT JOIN github_repo_enrichments e ON e.repo_id=c.repo_id
                LEFT JOIN github_project_semantic_sources ss ON ss.repo_id=c.repo_id
                CROSS JOIN (SELECT %s::integer AS _intake_threshold) scope
                WHERE (COALESCE(ls.stars,c.stars,0) >= scope._intake_threshold
                       OR e.status = 'succeeded')
                  AND {_ALIAS_TOMBSTONE_EXCLUSION_SQL}
            ), content AS (
                SELECT repo_id, status, category_slug, category_name, state
                FROM catalog
            ), unprocessable AS (
                SELECT repo_id, full_name, url, stars,
                       'missing_description' AS reason
                FROM catalog
                WHERE state = 'unprocessable'
            ), retained AS (
                SELECT c.repo_id, c.full_name, c.url,
                       COALESCE(ls.stars,c.stars,0) AS stars,
                       CASE
                         WHEN EXISTS (SELECT 1 FROM github_repo_aliases ga
                                      WHERE ga.alias_repo_id = c.repo_id
                                        AND ga.canonical_repo_id <> c.repo_id) THEN 'tombstone'
                         WHEN c.availability_status = 'not_found' THEN 'not_found'
                         WHEN COALESCE(ls.stars,c.stars,0) < %s THEN 'snapshot_below_threshold'
                         ELSE 'lost_input'
                       END AS reason
                FROM github_repo_candidates c
                JOIN github_repo_enrichments e ON e.repo_id=c.repo_id
                    AND e.status='succeeded'
                LEFT JOIN latest_snap ls ON ls.repo_id=c.repo_id
                LEFT JOIN github_project_semantic_sources ss ON ss.repo_id=c.repo_id
                WHERE COALESCE(c.stars,0) >= %s
                  AND NOT (COALESCE(ls.stars,c.stars,0) >= %s
                           AND {_GITHUB_ENRICHMENT_INPUT_SQL}
                           AND {_ALIAS_TOMBSTONE_EXCLUSION_SQL})
            )
        """
        # base contains five independent intake-threshold placeholders:
        # eligible, catalog scope, retained snapshot classification, and the
        # retained current-star/input queue gate (three retained placeholders).
        status_params = (min_stars,) * 5
        # 单语句聚合：base 的五个 CTE 只物化一次。旧版对 base 顺序执行 6 条语句
        # （总计数/分类聚合/不可处理明细/不可处理计数/保留桶/保留明细），每条都
        # 重算 latest_snap 与下游 CTE，是首页 live-stats 6.9s 的直接原因（生产
        # 实测单语句 ~0.4s）。列表结果用 json_agg 内嵌并保持原有排序与键名，
        # psycopg 解码为 list[dict]；空集由 COALESCE 兜底为 []。
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(base + """SELECT agg.eligible, agg.succeeded, agg.failed,
                    agg.catalog_total, agg.catalog_succeeded, agg.catalog_failed,
                    agg.catalog_unprocessable, agg.catalog_pending,
                    (SELECT COUNT(*) FROM unprocessable) AS unprocessable,
                    (SELECT COALESCE(json_agg(row_to_json(cat) ORDER BY cat.count DESC,
                                          cat.name COLLATE "C" ASC), '[]'::json)
                     FROM (SELECT category_slug AS slug, category_name AS name,
                                  COUNT(*) AS count
                           FROM content WHERE state='succeeded'
                           GROUP BY category_slug, category_name) cat) AS categories,
                    (SELECT COALESCE(json_agg(row_to_json(u) ORDER BY u.stars DESC,
                                          u.full_name COLLATE "C" ASC,
                                          u.repo_id COLLATE "C" ASC), '[]'::json)
                     FROM (SELECT repo_id, full_name, url, stars, reason
                           FROM unprocessable
                           ORDER BY stars DESC, full_name COLLATE "C" ASC,
                                    repo_id COLLATE "C" ASC
                           LIMIT 100) u) AS unprocessable_projects,
                    (SELECT COALESCE(json_agg(row_to_json(b)), '[]'::json)
                     FROM (SELECT reason, COUNT(*) AS count
                           FROM retained GROUP BY reason) b) AS retained_buckets,
                    (SELECT COALESCE(json_agg(row_to_json(r) ORDER BY r.stars DESC,
                                          r.full_name COLLATE "C" ASC,
                                          r.repo_id COLLATE "C" ASC), '[]'::json)
                     FROM (SELECT repo_id, full_name, url, stars, reason
                           FROM retained
                           ORDER BY stars DESC, full_name COLLATE "C" ASC,
                                    repo_id COLLATE "C" ASC
                           LIMIT 100) r) AS retained_projects
                    FROM (SELECT COUNT(*) AS eligible,
                                 COUNT(*) FILTER (WHERE status='succeeded') AS succeeded,
                                 COUNT(*) FILTER (WHERE status='failed') AS failed,
                                 (SELECT COUNT(*) FROM content) AS catalog_total,
                                 (SELECT COUNT(*) FROM content WHERE state='succeeded') AS catalog_succeeded,
                                 (SELECT COUNT(*) FROM content WHERE state='failed') AS catalog_failed,
                                 (SELECT COUNT(*) FROM content WHERE state='unprocessable') AS catalog_unprocessable,
                                 (SELECT COUNT(*) FROM content WHERE state='pending') AS catalog_pending
                          FROM eligible) agg""", status_params)
                row = cursor.fetchone() or {}
        categories = row.get("categories") or []
        unprocessable_projects = row.get("unprocessable_projects") or []
        retained_bucket_rows = row.get("retained_buckets") or []
        retained_projects = row.get("retained_projects") or []
        eligible = int(row.get("eligible") or 0)
        succeeded = int(row.get("succeeded") or 0)
        failed = int(row.get("failed") or 0)
        catalog_total = int(row.get("catalog_total") or 0)
        catalog_succeeded = int(row.get("catalog_succeeded") or 0)
        catalog_failed = int(row.get("catalog_failed") or 0)
        retained_buckets = {reason: 0 for reason in
                            ("tombstone", "not_found", "snapshot_below_threshold", "lost_input")}
        for item in retained_bucket_rows:
            reason = str(item.get("reason") or "")
            if reason in retained_buckets:
                retained_buckets[reason] = int(item.get("count") or 0)
        catalog_unprocessable = int(row.get("catalog_unprocessable") or 0)
        catalog_pending = int(row.get("catalog_pending") or 0)
        catalog_progress_total = catalog_total
        catalog_progress_pending = catalog_pending
        queue_pending = max(eligible - succeeded - failed, 0)
        return {"eligible": eligible, "succeeded": succeeded, "failed": failed,
                "pending": queue_pending,
                "queue_pending": queue_pending,
                "queue_failed": failed,
                "content_total": catalog_succeeded, "catalog_total": catalog_total,
                "catalog_succeeded": catalog_succeeded, "catalog_failed": catalog_failed,
                "catalog_pending": catalog_pending,
                "catalog_unprocessable": catalog_unprocessable,
                "catalog_progress": {"total": catalog_progress_total,
                    "succeeded": catalog_succeeded, "failed": catalog_failed,
                    "unprocessable": catalog_unprocessable,
                    "pending": catalog_progress_pending},
                "retained_total": sum(retained_buckets.values()),
                "retained_buckets": retained_buckets,
                "retained_projects": [{"repo_id": str(item.get("repo_id") or ""),
                    "full_name": str(item.get("full_name") or ""), "url": str(item.get("url") or ""),
                    "stars": int(item.get("stars") or 0), "reason": str(item.get("reason") or "")}
                    for item in retained_projects],
                "by_category": [{"slug": item.get("slug") or "other",
                    "name": item.get("name") or "其他", "count": int(item.get("count") or 0)}
                    for item in categories],
                "unprocessable": int(row.get("unprocessable") or 0),
                "unprocessable_projects": [{"repo_id": str(item.get("repo_id") or ""),
                    "full_name": str(item.get("full_name") or ""), "url": str(item.get("url") or ""),
                    "stars": int(item.get("stars") or 0),
                    "reason": str(item.get("reason") or "missing_description")}
                    for item in unprocessable_projects]}

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
                      AND (e.status IS NULL OR e.status != 'blocked')
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

    def mark_tool_website_enrichment_blocked(
        self, website_id: int, *, source_fingerprint: str, prompt_version: str,
        reason: str, model_provider: str = "", model_name: str = "",
    ) -> None:
        self.upsert_tool_website_enrichment({
            "website_id": website_id, "category_slug": "other", "category_name": "其他",
            "subcategory_slug": "other_uncategorized", "subcategory_name": "未分类",
            "description_zh": "", "tags_json": "[]", "confidence": 0.0,
            "source_fingerprint": source_fingerprint, "prompt_version": prompt_version,
            "model_provider": model_provider, "model_name": model_name,
            "status": "blocked", "error_msg": reason[:2000],
        })
