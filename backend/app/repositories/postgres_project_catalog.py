from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.domain.project_taxonomy import (
    DEFAULT_SUBCATEGORY_BY_CATEGORY,
    PROJECT_TAXONOMY,
    WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    WEBSITE_TAXONOMY,
)
from backend.app.domain.search_semantics import (
    escape_like_literal,
    project_search_terms,
)
from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
    ProjectLexicalRetrievalPlan,
)
from backend.app.repositories.project_catalog_normalization import (
    format_project_category_counts,
    normalize_project_row,
)

GITHUB_PROJECT_TODAY_LIMIT = 50
# 公共 relevance 排序使用强字段匹配；当强命中项目不足该阈值时降级使用弱字段。
RELEVANCE_STRONG_MATCH_THRESHOLD = 5

# ── 词法检索的字段级匹配片段 ─────────────────────────────────────────────
# 每个搜索词在所有字段上做 OR 匹配；参数按字段顺序逐一绑定（[like] * len(fields)）。
_GH_TERM_MATCH_FIELDS = (
    "c.full_name",
    "c.title",
    "c.description",
    "COALESCE(ge.description_zh, '')",
    "COALESCE(c.language, '')",
    "COALESCE(c.topics_json, '')",
    "COALESCE(ge.tags_json::text, '')",
)
_GH_TERM_MATCH_FIELDS_WITH_I18N_TAGS = (
    *_GH_TERM_MATCH_FIELDS,
    "COALESCE(ge.tags_zh_json::text, '')",
    "COALESCE(ge.tags_en_json::text, '')",
)
# 公共 relevance 排序优先要求命中的字段：仓库名、标题、系统标签。
# 弱字段（描述、语言、topics）只在强命中不足时作为降级召回。
_GH_STRONG_TERM_MATCH_FIELDS = (
    "c.full_name",
    "c.title",
    "COALESCE(ge.tags_json::text, '')",
    "COALESCE(ge.tags_zh_json::text, '')",
    "COALESCE(ge.tags_en_json::text, '')",
)


def _term_match_filter(fields: tuple[str, ...]) -> str:
    """生成 (field ILIKE %s ESCAPE '=' OR ...) 形式的字段组过滤片段。"""
    return "(" + " OR ".join(f"{field} ILIKE %s ESCAPE '='" for field in fields) + ")"


# ── list_projects 统一行结构的逐列清单（表驱动单一来源）──────────────────
# github 与 website 两个 UNION ALL 分支的列按位置一一对应：每行为
# (github 表达式, website 表达式模板)，website 模板中的 {key} 占位由
# _web_effective_expressions 的映射填充。增删列只需改这张表，并同步
# project_catalog_normalization.normalize_project_row。
_LIST_PROJECT_COLUMN_PAIRS = (
    ("'github:'||c.repo_id id", "'website:'||w.id::text id"),
    ("'github' source", "'website' source"),
    ("c.repo_id", "NULL::text repo_id"),
    ("NULL::bigint website_id", "w.id website_id"),
    ("c.full_name", "{full_name} full_name"),
    ("c.title", "{title} title"),
    ("c.url", "w.canonical_url url"),
    ("NULL::text domain", "w.domain"),
    ("(SELECT '/api/projects/github/logo/' || c.repo_id FROM github_project_logos gl WHERE gl.repo_id = c.repo_id AND gl.content IS NOT NULL) image_url", "{image} image_url"),
    ("c.description", "{description} description"),
    ("ge.description_zh", "{description_zh} description_zh"),
    ("ge.description_en", "{description_en} description_en"),
    ("ge.category_slug", "{category_slug} category_slug"),
    (
        "COALESCE(NULLIF(ge.category_name_zh,''),ge.category_name) category_name",
        "{category_name} category_name",
    ),
    ("ge.category_name_zh", "{category_name} category_name_zh"),
    ("ge.category_name_en", "{category_name_en} category_name_en"),
    ("ge.subcategory_slug", "{subcategory_slug} subcategory_slug"),
    (
        "COALESCE(NULLIF(ge.subcategory_name_zh,''),ge.subcategory_name) subcategory_name",
        "{subcategory_name} subcategory_name",
    ),
    ("ge.subcategory_name_zh", "{subcategory_name} subcategory_name_zh"),
    ("ge.subcategory_name_en", "{subcategory_name_en} subcategory_name_en"),
    ("ge.tags_json::text tags_json", "{tags} tags_json"),
    ("ge.tags_zh_json::text tags_zh_json", "{tags_zh} tags_zh_json"),
    ("ge.tags_en_json::text tags_en_json", "{tags_en} tags_en_json"),
    ("'system'::text tags_origin", "{tags_origin} tags_origin"),
    ("c.language", "NULL::text language"),
    ("c.license_spdx_id", "NULL::text license_spdx_id"),
    ("c.topics_json", "'[]' topics_json"),
    (
        "CASE WHEN gm.repo_id IS NOT NULL THEN gm.stars ELSE COALESCE(c.stars,0) END stars",
        "0::bigint stars",
    ),
    (
        "CASE WHEN gm.repo_id IS NOT NULL THEN gm.forks ELSE COALESCE(c.forks,0) END forks",
        "0::bigint forks",
    ),
    (
        "CASE WHEN gm.repo_id IS NOT NULL THEN gm.watchers ELSE COALESCE(c.watchers,0) END watchers",
        "0::bigint watchers",
    ),
    (
        "CASE WHEN gm.repo_id IS NOT NULL THEN gm.open_issues ELSE 0 END open_issues",
        "0::bigint open_issues",
    ),
    ("c.created_at", "NULL::text created_at"),
    ("c.pushed_at", "NULL::text pushed_at"),
    ("c.first_seen_at", "w.first_seen_at::text first_seen_at"),
    ("c.last_seen_at", "w.last_seen_at::text last_seen_at"),
    ("c.last_snapshot_at", "NULL::text last_snapshot_at"),
    ("gm.metric_date snapshot_date", "NULL::text snapshot_date"),
    ("c.last_snapshot_at captured_at", "NULL::text captured_at"),
    ("NULL::integer rank_in_period", "NULL::integer rank_in_period"),
    ("COALESCE(gm.daily_star_growth,0) raw_score", "0::bigint raw_score"),
    ("COALESCE(gm.hot_score,0) score", "0::double precision score"),
    ("gm.metric_date daily_growth_date", "NULL::text daily_growth_date"),
    ("gm.previous_snapshot_date", "NULL::text previous_snapshot_date"),
    ("COALESCE(gm.daily_star_growth,0) daily_star_growth", "0::bigint daily_star_growth"),
    (
        "COALESCE(gm.daily_growth_available,FALSE) daily_growth_available",
        "FALSE daily_growth_available",
    ),
    (
        "COALESCE(gm.daily_growth_source,'unavailable') daily_growth_source",
        "'unavailable' daily_growth_source",
    ),
    # github 侧 gm.daily_growth_observed_at 在 schema 中是 TEXT，website 侧
    # 必须同为 text——若写 NULL::timestamptz，UNION ALL 报
    # "UNION types text and timestamp with time zone cannot be matched"，
    # source=all（公开列表默认）整表 500。
    ("gm.daily_growth_observed_at", "NULL::text daily_growth_observed_at"),
    ("COALESCE(gm.hot_score,0) hot_score", "0::double precision hot_score"),
    (
        "COALESCE(gm.scale_corrected_growth_score,0) scale_corrected_growth_score",
        "0::double precision scale_corrected_growth_score",
    ),
    (
        "COALESCE(gm.growth_acceleration_score,0) growth_acceleration_score",
        "0::double precision growth_acceleration_score",
    ),
    (
        "COALESCE(gm.absolute_growth_score,0) absolute_growth_score",
        "0::double precision absolute_growth_score",
    ),
    (
        "COALESCE(gm.maintenance_activity_score,0) maintenance_activity_score",
        "0::double precision maintenance_activity_score",
    ),
    (
        "COALESCE(gm.community_engagement_score,0) community_engagement_score",
        "0::double precision community_engagement_score",
    ),
    (
        "COALESCE(gm.growth_suspicion_score,0) growth_suspicion_score",
        "0::double precision growth_suspicion_score",
    ),
    (
        "COALESCE(gm.growth_suspicion_signals,'[]') growth_suspicion_signals",
        "'[]'::text growth_suspicion_signals",
    ),
    (
        "COALESCE(gm.growth_corroborated,FALSE) growth_corroborated",
        "FALSE growth_corroborated",
    ),
    # 下架（not_found）仓库保留在列表中，前端据此渲染置灰卡片；
    # website 分支无可用性概念，恒为 active。
    ("c.availability_status", "'active'::text availability_status"),
    ("ge.confidence", "we.confidence"),
)
_GH_SELECT_COLUMNS = tuple(github for github, _website in _LIST_PROJECT_COLUMN_PAIRS)
# 收藏列依赖 user_id（gh_favorites/web_favorites 片段），推荐列依赖 gr 关联，
# 二者按此顺序拼接在静态列之后。
_GH_SELECT_TAIL_COLUMNS = (
    "(gr.repo_id IS NOT NULL) is_recommended",
    "gr.recommended_at",
)
_WEB_SELECT_TAIL_COLUMNS = (
    "FALSE is_recommended",
    "NULL::timestamptz recommended_at",
)
# 未登录（user_id 为空）时两个分支共用的收藏列占位。
_ANONYMOUS_FAVORITE_COLUMNS = (
    "FALSE is_favorited, NULL::timestamptz favorited_at,"
    " FALSE user_added, NULL::timestamptz user_added_at,"
    " NULL::timestamptz collection_at"
)
_GH_SELECT_FROM = (
    " FROM github_repo_candidates c"
    " LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id"
    " LEFT JOIN github_repo_recommendations gr ON gr.repo_id=c.repo_id AND gr.active=TRUE"
)

# alias 归并行（改名旧名）不进入公开统计/列表/搜索，避免同一项目双计。
_GH_CANONICAL_ALIAS_FILTER = (
    "NOT EXISTS (SELECT 1 FROM github_repo_aliases ga "
    "WHERE ga.alias_repo_id = c.repo_id "
    "AND ga.canonical_repo_id <> c.repo_id)"
)
# Public GitHub rows are the succeeded canonical relation.  Intake threshold is
# intentionally not part of this predicate: a project that was enriched and
# later falls below 500 stars remains searchable and countable.
_GH_PUBLIC_SUCCEEDED_FILTER = (
    "ge.status = 'succeeded' AND " + _GH_CANONICAL_ALIAS_FILTER
)
_WEB_SELECT_FROM = (
    " FROM tool_websites w"
    " LEFT JOIN tool_website_enrichments we ON we.website_id=w.id"
)


def _today() -> str:
    zone = getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(zone)).date().isoformat()


def _today_range() -> tuple[str, str]:
    zone = ZoneInfo(getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai")
    start = datetime.combine(datetime.now(zone).date(), datetime.min.time(), tzinfo=zone)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


def _web_effective_expressions(user_web: bool) -> dict[str, str]:
    """website 分支的 effective 列表达式；登录用户的内容以 uo 覆盖优先。"""
    return {
        "full_name": "COALESCE(NULLIF(uo.title, ''), NULLIF(w.title, ''), w.domain)" if user_web else "COALESCE(NULLIF(w.title, ''), w.domain)",
        "title": "COALESCE(NULLIF(uo.title, ''), w.title)" if user_web else "w.title",
        "description": "COALESCE(NULLIF(uo.description, ''), w.description)" if user_web else "w.description",
        "image": "COALESCE(NULLIF(uo.image_url, ''), NULLIF(w.image_url, ''), regexp_replace(w.canonical_url, '^(([^/]+/){2}[^/]+).*$' , '\\1') || '/favicon.ico')" if user_web else "COALESCE(NULLIF(w.image_url, ''), regexp_replace(w.canonical_url, '^(([^/]+/){2}[^/]+).*$' , '\\1') || '/favicon.ico')",
        "category_slug": "COALESCE(NULLIF(uo.category_slug, ''), we.category_slug)" if user_web else "we.category_slug",
        "category_name": "COALESCE(NULLIF(uo.category_name_zh, ''), we.category_name_zh, NULLIF(uo.category_name, ''), we.category_name)" if user_web else "COALESCE(NULLIF(we.category_name_zh, ''), we.category_name)",
        "category_name_en": "COALESCE(NULLIF(uo.category_name_en, ''), we.category_name_en)" if user_web else "we.category_name_en",
        "subcategory_slug": "COALESCE(NULLIF(uo.subcategory_slug, ''), we.subcategory_slug)" if user_web else "we.subcategory_slug",
        "subcategory_name": "COALESCE(NULLIF(uo.subcategory_name_zh, ''), we.subcategory_name_zh, NULLIF(uo.subcategory_name, ''), we.subcategory_name)" if user_web else "COALESCE(NULLIF(we.subcategory_name_zh, ''), we.subcategory_name)",
        "subcategory_name_en": "COALESCE(NULLIF(uo.subcategory_name_en, ''), we.subcategory_name_en)" if user_web else "we.subcategory_name_en",
        "description_zh": "COALESCE(NULLIF(uo.description_zh, ''), we.description_zh)" if user_web else "we.description_zh",
        "description_en": "COALESCE(NULLIF(uo.description_en, ''), we.description_en)" if user_web else "we.description_en",
        "tags": "COALESCE(NULLIF(uo.tags_json::text, ''), we.tags_json::text)" if user_web else "we.tags_json::text",
        "tags_zh": "CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN NULL ELSE we.tags_zh_json::text END" if user_web else "we.tags_zh_json::text",
        "tags_en": "CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN NULL ELSE we.tags_en_json::text END" if user_web else "we.tags_en_json::text",
        "tags_origin": "CASE WHEN NULLIF(uo.tags_json::text, '') IS NOT NULL THEN 'user' ELSE 'system' END" if user_web else "'system'",
    }


def _web_select_columns(effective: dict[str, str]) -> tuple[str, ...]:
    """按 _LIST_PROJECT_COLUMN_PAIRS 展开 website 分支列清单。"""
    return tuple(website.format_map(effective) for _github, website in _LIST_PROJECT_COLUMN_PAIRS)


def _strong_match_threshold(sort: str, q: str, candidates: list[str] | None) -> int:
    """relevance 关键词搜索启用强字段命中过滤的阈值；其余场景返回 0（关闭）。

    q 非空但提取不出有效搜索词（如 github/项目 等传输词、单字符、纯符号）
    时必须关闭：该场景走 filters=FALSE 早退路径，强命中条件为空，若仍启用
    阈值会把空条件折叠成 (())::boolean 非法 SQL，公开接口直接 500。
    """
    if sort == "relevance" and q and candidates is None and project_search_terms(q):
        return RELEVANCE_STRONG_MATCH_THRESHOLD
    return 0


def _strong_match_clause(conditions: list[str]) -> str:
    """把强字段命中条件折叠为 SELECT 列表中的 has_strong_match 布尔列。

    空条件（防御性兜底：正常路径由 _strong_match_threshold 保证阈值>0 时
    必有条件）折叠为 FALSE，避免生成 (())::boolean 非法 SQL。
    """
    if not conditions:
        return "FALSE::boolean has_strong_match"
    return f"(({' AND '.join(conditions)}))::boolean has_strong_match"


def _build_gh_branch(
    *,
    filters: list[str],
    filter_params: list[Any],
    strong_conditions: list[str],
    strong_params: list[Any],
    strong_threshold: int,
    scope: str,
    min_stars: int,
    enriched_only: bool,
    user_id: int | None,
) -> tuple[str, list[Any]]:
    """组装 github 分支 SELECT 与按 %s 占位顺序绑定的参数。"""
    date = _today()
    hot_join = (
        "LEFT JOIN github_repo_daily_metrics gm"
        " ON gm.repo_id = c.repo_id AND gm.metric_date = %s"
    )
    params: list[Any] = [date]
    if scope == "today":
        # 今日暴涨内层 Top-N 驱动表与外层同一可见性口径：enriched-only 时按
        # succeeded canonical 关系过滤（无星数门槛），否则按 intake 星数门槛。
        if enriched_only:
            top_filter = _GH_PUBLIC_SUCCEEDED_FILTER.replace(
                "c.", "c_top."
            ).replace("ge.", "ge_top.")
            top_params: list[Any] = [date]
        else:
            top_filter = "COALESCE(c_top.stars,0)>=%s"
            top_params = [date, min_stars]
        hot_join += (
            " JOIN (SELECT c_top.repo_id FROM github_repo_candidates c_top"
            " JOIN github_repo_daily_metrics gm_top ON gm_top.repo_id=c_top.repo_id"
            " AND gm_top.metric_date=%s AND gm_top.daily_growth_available=TRUE"
            " AND gm_top.daily_star_growth>0"
            " LEFT JOIN github_repo_enrichments ge_top ON ge_top.repo_id=c_top.repo_id"
            f" WHERE {top_filter}"
            " ORDER BY gm_top.hot_score DESC NULLS LAST,"
            " gm_top.daily_star_growth DESC NULLS LAST,"
            " gm_top.stars DESC NULLS LAST, c_top.full_name ASC"
            f" LIMIT {GITHUB_PROJECT_TODAY_LIMIT}) today_top"
            " ON today_top.repo_id=c.repo_id"
        )
        params.extend(top_params)
    user_join = ""
    if user_id:
        user_join = (
            "LEFT JOIN project_favorites pf"
            " ON pf.user_id=%s AND pf.project_source='github' AND pf.project_id=c.repo_id"
        )
        params.append(user_id)
    params.extend(filter_params)
    # 强字段命中表达式位于 SELECT 列表，在 SQL 文本中排在 FROM/JOIN/WHERE
    # 之前，因此它的参数必须放在 params 最前面。
    params = strong_params + params
    if user_id:
        favorites = (
            "(pf.id IS NOT NULL) is_favorited, pf.created_at favorited_at,"
            " FALSE user_added, NULL::timestamptz user_added_at,"
            " pf.created_at collection_at"
        )
    else:
        favorites = _ANONYMOUS_FAVORITE_COLUMNS
    select_columns = [*_GH_SELECT_COLUMNS, favorites, *_GH_SELECT_TAIL_COLUMNS]
    if strong_threshold:
        select_columns.insert(len(_GH_SELECT_COLUMNS), _strong_match_clause(strong_conditions))
    select = (
        f"SELECT {','.join(select_columns)}"
        f"{_GH_SELECT_FROM} {hot_join} {user_join} WHERE {' AND '.join(filters)}"
    )
    return select, params


def _build_web_branch(
    *,
    filters: list[str],
    filter_params: list[Any],
    effective: dict[str, str],
    strong_threshold: int,
    user_id: int | None,
) -> tuple[str, list[Any]]:
    """组装 website 分支 SELECT 与按 %s 占位顺序绑定的参数。"""
    user_join = ""
    if user_id:
        user_join = (
            "LEFT JOIN project_favorites pf"
            " ON pf.user_id=%s AND pf.project_source='website' AND pf.project_id=w.id::text"
            " LEFT JOIN user_tool_websites utw ON utw.user_id=%s AND utw.website_id=w.id"
            " LEFT JOIN user_tool_website_overrides uo ON uo.user_id=%s AND uo.website_id=w.id"
        )
    params: list[Any] = ([user_id, user_id, user_id] if user_id else []) + filter_params
    if user_id:
        favorites = (
            "(pf.id IS NOT NULL) is_favorited, pf.created_at favorited_at,"
            " (utw.id IS NOT NULL) user_added, utw.created_at user_added_at,"
            " COALESCE(pf.created_at,utw.created_at) collection_at"
        )
    else:
        favorites = _ANONYMOUS_FAVORITE_COLUMNS
    web_columns = _web_select_columns(effective)
    select_columns = [*web_columns, favorites, *_WEB_SELECT_TAIL_COLUMNS]
    if strong_threshold:
        select_columns.insert(len(web_columns), "TRUE::boolean has_strong_match")
    select = (
        f"SELECT {','.join(select_columns)}"
        f"{_WEB_SELECT_FROM} {user_join} WHERE {' AND '.join(filters)}"
    )
    return select, params


def _build_union_queries(
    parts: list[str], strong_threshold: int
) -> tuple[str, str, list[Any]]:
    """把分支 SELECT 组装为 UNION ALL CTE，并生成 count/rows 两条查询。

    rows 查询保留 {order} 占位，由调用方替换为 ORDER BY 片段。
    """
    base = f"WITH project_rows AS ({' UNION ALL '.join(parts)})"
    if strong_threshold:
        base += ", counts AS (SELECT COUNT(*) AS total_all, COUNT(*) FILTER (WHERE has_strong_match) AS total_strong FROM project_rows)"
        count_sql = base + " SELECT COUNT(*) AS cnt FROM project_rows WHERE has_strong_match OR (SELECT total_strong FROM counts) < %s"
        rows_sql_prefix = base + " SELECT * FROM project_rows WHERE has_strong_match OR (SELECT total_strong FROM counts) < %s ORDER BY {order} LIMIT %s OFFSET %s"
        threshold_params: list[Any] = [strong_threshold]
    else:
        count_sql = base + " SELECT COUNT(*) AS cnt FROM project_rows"
        rows_sql_prefix = base + " SELECT * FROM project_rows ORDER BY {order} LIMIT %s OFFSET %s"
        threshold_params = []
    return count_sql, rows_sql_prefix, threshold_params


def _resolve_order(
    *,
    sort: str,
    scope: str,
    q: str,
    candidates: list[str] | None,
) -> tuple[str, list[Any]]:
    """把排序参数解析为 ORDER BY 片段及其绑定参数。"""
    if scope == "today": sort = "hot"
    recent = "COALESCE(recommended_at,collection_at,NULLIF(first_seen_at,'')::timestamptz,NULLIF(last_seen_at,'')::timestamptz)" if scope == "recommended" else "COALESCE(collection_at,NULLIF(first_seen_at,'')::timestamptz,NULLIF(last_seen_at,'')::timestamptz)"
    orders = {
        "hot": "hot_score DESC NULLS LAST,daily_star_growth DESC NULLS LAST,stars DESC,full_name ASC",
        "stars": "stars DESC,forks DESC,full_name ASC",
        "updated": "COALESCE(NULLIF(pushed_at,''),last_seen_at::text,first_seen_at::text) DESC NULLS LAST,stars DESC,full_name ASC",
        "recent": f"{recent} DESC NULLS LAST,stars DESC,full_name ASC",
        "name": "full_name ASC",
    }
    order_params: list[Any] = []
    if sort == "relevance":
        if candidates is not None:
            order = "array_position(%s::text[],repo_id),full_name ASC"
            order_params.append(candidates)
        elif q:
            normalized_query = " ".join(str(q).split())
            prefix = f"{escape_like_literal(normalized_query)}%"
            # 名段层级：split_part(full_name,'/',2) 即仓库名本身。裸名搜索
            # （如 "pi"）时，仓库名恰好等于查询词的项目必须压过 owner/repo
            # 整体前缀命中的项目（pi-hole、pingcap/*）；owner/repo 全形
            # 等值仍是最高层。无 '/' 的行 split_part 返回 ''，天然不命中。
            order = (
                "CASE"
                " WHEN LOWER(full_name)=LOWER(%s) THEN 0"
                " WHEN LOWER(split_part(full_name,'/',2))=LOWER(%s) THEN 1"
                " WHEN LOWER(COALESCE(title,''))=LOWER(%s) THEN 2"
                " WHEN split_part(full_name,'/',2) ILIKE %s ESCAPE '=' THEN 3"
                " WHEN full_name ILIKE %s ESCAPE '=' THEN 4"
                " WHEN COALESCE(title,'') ILIKE %s ESCAPE '=' THEN 5"
                " ELSE 6 END,"
                "stars DESC, forks DESC, full_name ASC"
            )
            order_params.extend([
                normalized_query, normalized_query, normalized_query,
                prefix, prefix, prefix,
            ])
        else:
            order = orders["stars"]
    else:
        order = orders.get(sort, orders["hot"] if scope == "today" else orders["stars"])
    return order, order_params


class PostgresProjectCatalogRepository:
    """PostgreSQL implementation of the frozen public project catalog reads."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle = postgres_database,
        *,
        statement_timeout_ms: int | None = None,
    ) -> None:
        self._database = database
        self._statement_timeout_ms = (
            max(1, int(statement_timeout_ms))
            if statement_timeout_ms is not None
            else None
        )

    def _begin_read(self, cursor: Any) -> None:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if self._statement_timeout_ms is not None:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_ms),),
            )

    def _transaction(self) -> Any:
        if self._statement_timeout_ms is None:
            return self._database.transaction()
        return self._database.transaction(
            acquisition_timeout=self._statement_timeout_ms / 1000,
        )

    def find_lexical_candidate_repo_ids(
        self,
        *,
        q: str,
        category: str = "",
        subcategory: str = "",
        language: str = "",
        tag: str = "",
        min_stars: int = 500,
        enriched_only: bool = True,
        limit: int = 200,
    ) -> list[str]:
        terms = project_search_terms(q)
        if not terms:
            return []
        limit = max(1, min(int(limit or 200), 200))
        normalized_query = " ".join(str(q or "").split())
        # 已下架（not_found）仓库保留在搜索结果中，前端以置灰卡片展示，
        # 与列表/分类/仪表盘统计口径一致；仅 dashboard 日榜仍排除不可用仓库。
        filters = [
            _GH_PUBLIC_SUCCEEDED_FILTER if enriched_only else "COALESCE(c.stars, 0) >= %s",
            "ga.alias_repo_id IS NULL",
        ]
        params: list[Any] = [] if enriched_only else [min_stars]
        if category:
            filters.append("ge.category_slug = %s"); params.append(category)
        if subcategory:
            default = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            filters.append("(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')" if category and subcategory == default else "ge.subcategory_slug = %s")
            params.append(subcategory)
        if language:
            filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)"); params.append(language)
        if tag:
            filters.append("COALESCE(ge.tags_json::text, '') ILIKE %s"); params.append(f'%"{tag.strip()}"%')
        for term in terms:
            like = f"%{escape_like_literal(term)}%"
            filters.append(_term_match_filter(_GH_TERM_MATCH_FIELDS))
            params.extend([like] * len(_GH_TERM_MATCH_FIELDS))
        prefix = f"{escape_like_literal(normalized_query)}%"
        # 层级口径与 _resolve_order / find_lexical_candidate_lanes 一致：
        # 仓库名段等值/前缀高于 full_name 整体前缀，裸名搜索不被 owner 前缀淹没。
        sql = f"""SELECT c.repo_id FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id
            LEFT JOIN github_repo_aliases ga ON ga.alias_repo_id=c.repo_id AND ga.canonical_repo_id<>c.repo_id
            WHERE {' AND '.join(filters)}
            ORDER BY CASE WHEN LOWER(c.full_name)=LOWER(%s) THEN 0 WHEN LOWER(split_part(c.full_name,'/',2))=LOWER(%s) THEN 1 WHEN LOWER(COALESCE(c.title,''))=LOWER(%s) THEN 2 WHEN split_part(c.full_name,'/',2) ILIKE %s ESCAPE '=' THEN 3 WHEN c.full_name ILIKE %s ESCAPE '=' THEN 4 WHEN COALESCE(c.title,'') ILIKE %s ESCAPE '=' THEN 5 ELSE 6 END,
                COALESCE(c.stars,0) DESC,c.repo_id COLLATE "C" ASC LIMIT %s"""
        params.extend([
            normalized_query, normalized_query, normalized_query,
            prefix, prefix, prefix, limit,
        ])
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        return [str(row.get("repo_id") or "") for row in rows if row.get("repo_id")]

    def find_repo_ids_by_name_segment(
        self,
        *,
        name: str,
        limit: int = 2,
    ) -> list[str]:
        """按仓库名段（full_name 的 '/' 后部分）等值匹配，供裸名查询钉顶判唯一。

        只看 active 且未被别名归并的仓库；调用方以 limit=2 取回后按
        len==1 判定唯一命中。不设 min_stars——这是身份定位而非发现召回。
        """
        normalized = " ".join(str(name or "").split()).strip()
        if not normalized:
            return []
        limit = max(1, min(int(limit or 2), 10))
        sql = """SELECT c.repo_id FROM github_repo_candidates c
            WHERE LOWER(split_part(c.full_name, '/', 2)) = LOWER(%s)
              AND c.availability_status = 'active'
              AND NOT EXISTS (SELECT 1 FROM github_repo_aliases ga
                              WHERE ga.alias_repo_id = c.repo_id
                              AND ga.canonical_repo_id <> c.repo_id)
            ORDER BY COALESCE(c.stars, 0) DESC, c.repo_id COLLATE "C" ASC
            LIMIT %s"""
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(sql, (normalized, limit))
                rows = cursor.fetchall()
        return [str(row.get("repo_id") or "") for row in rows if row.get("repo_id")]

    def find_lexical_candidate_lanes(
        self,
        *,
        q: str | ProjectLexicalRetrievalPlan,
        category: str = "",
        subcategory: str = "",
        language: str = "",
        tag: str = "",
        min_stars: int = 500,
        enriched_only: bool = True,
        strict_limit: int = 150,
        relaxed_limit: int = 150,
    ) -> ProjectLexicalCandidateLanes:
        if isinstance(q, ProjectLexicalRetrievalPlan):
            normalized_query = " ".join(q.normalized_query.split())
            strict_terms = tuple(term for term in q.strict_terms if term.strip())
            concepts = tuple(
                (concept.concept_id, tuple(dict.fromkeys(
                    term.strip() for term in (*concept.primary_terms, *concept.aliases) if term.strip()
                )))
                for concept in q.concepts
            )
            concepts = tuple((concept_id, terms) for concept_id, terms in concepts if terms)
        else:
            normalized_query = " ".join(str(q or "").split())
            strict_terms = tuple(project_search_terms(q))
            concepts = ()
        required_coverage = len(strict_terms) + len(concepts)
        if not required_coverage:
            return ProjectLexicalCandidateLanes()
        strict_limit = max(1, min(int(strict_limit or 150), 150))
        relaxed_limit = max(1, min(int(relaxed_limit or 150), 150))
        prefix = f"{escape_like_literal(normalized_query)}%"
        # 与 list_projects 同一可见性口径：not_found 仓库保留（前端置灰展示）。
        filters = [
            _GH_PUBLIC_SUCCEEDED_FILTER
            if enriched_only
            else f"COALESCE(c.stars, 0) >= %s AND {_GH_CANONICAL_ALIAS_FILTER}"
        ]
        filter_params: list[Any] = [] if enriched_only else [min_stars]
        if category:
            filters.append("ge.category_slug = %s")
            filter_params.append(category)
        if subcategory:
            default = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            if category and subcategory == default:
                filters.append("(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
            else:
                filters.append("ge.subcategory_slug = %s")
            filter_params.append(subcategory)
        if language:
            filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)")
            filter_params.append(language)
        if tag:
            filters.append("COALESCE(ge.tags_json::text, '') ILIKE %s")
            filter_params.append(f'%"{tag.strip()}"%')

        candidate_document = (
            "LOWER(COALESCE(c.full_name, '') || ' ' || COALESCE(c.title, '')"
            " || ' ' || COALESCE(c.description, '') || ' ' || COALESCE(c.language, '')"
            " || ' ' || COALESCE(c.topics_json, ''))"
        )
        enrichment_document = (
            "LOWER(COALESCE(ge.description_zh, '') || ' ' || COALESCE(ge.tags_json::text, ''))"
        )
        rows: list[tuple[str, str]] = []
        for index, term in enumerate(strict_terms):
            rows.append((f"term:{index}", f"%{escape_like_literal(term)}%"))
        for concept_id, terms in concepts:
            for term in terms:
                rows.append((f"concept:{concept_id}", f"%{escape_like_literal(term)}%"))
        group_ids = tuple(dict.fromkeys(group_id for group_id, _ in rows))
        hit_parts: list[str] = []
        hit_params: list[Any] = []
        for group_id, pattern in rows:
            hit_parts.extend(
                (
                    f"""
                        SELECT c.repo_id, %s::text AS group_id
                        FROM github_repo_candidates c
                        JOIN eligible e ON e.repo_id = c.repo_id
                        WHERE {candidate_document} ILIKE %s ESCAPE '='
                    """,
                    f"""
                        SELECT ge.repo_id, %s::text AS group_id
                        FROM github_repo_enrichments ge
                        JOIN eligible e ON e.repo_id = ge.repo_id
                        WHERE {enrichment_document} ILIKE %s ESCAPE '='
                    """,
                )
            )
            hit_params.extend((group_id, pattern, group_id, pattern))
        sql = f"""
            WITH eligible AS MATERIALIZED (
                SELECT c.repo_id, c.full_name, c.title, COALESCE(c.stars, 0) AS stars
                FROM github_repo_candidates c
                LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                WHERE {' AND '.join(filters)}
            ), raw_hits AS MATERIALIZED (
                SELECT DISTINCT repo_id, group_id
                FROM ({' UNION ALL '.join(hit_parts)}) branch_hits
            ), scored AS MATERIALIZED (
                SELECT
                    e.repo_id,
                    e.full_name,
                    e.stars,
                    COUNT(*)::integer AS term_coverage,
                    CASE
                        WHEN LOWER(e.full_name) = LOWER(%s) THEN 6
                        WHEN LOWER(split_part(e.full_name, '/', 2)) = LOWER(%s) THEN 5
                        WHEN LOWER(COALESCE(e.title, '')) = LOWER(%s) THEN 4
                        WHEN split_part(e.full_name, '/', 2) ILIKE %s ESCAPE '=' THEN 3
                        WHEN e.full_name ILIKE %s ESCAPE '=' THEN 2
                        WHEN COALESCE(e.title, '') ILIKE %s ESCAPE '=' THEN 1
                        ELSE 0
                    END AS match_strength
                FROM raw_hits hit
                JOIN eligible e ON e.repo_id = hit.repo_id
                GROUP BY e.repo_id, e.full_name, e.title, e.stars
            ), bounded_lanes AS (
                (SELECT 'strict'::text AS lane, 0 AS lane_order,
                        repo_id, term_coverage, match_strength, stars, full_name
                 FROM scored
                 WHERE term_coverage = %s
                 ORDER BY match_strength DESC, stars DESC, repo_id COLLATE "C" ASC
                 LIMIT %s)
                UNION ALL
                (SELECT 'relaxed'::text AS lane, 1 AS lane_order,
                        repo_id, term_coverage, match_strength, stars, full_name
                 FROM scored
                 WHERE term_coverage > 0
                 ORDER BY term_coverage DESC, match_strength DESC, stars DESC, repo_id COLLATE "C" ASC
                 LIMIT %s)
            )
            SELECT lane, repo_id, term_coverage, match_strength
            FROM bounded_lanes
            ORDER BY lane_order,
                     CASE WHEN lane_order = 1 THEN term_coverage END DESC,
                     match_strength DESC, stars DESC, repo_id COLLATE "C" ASC
        """
        # 参数顺序契约（必须与上方 SQL 文本中 %s 的出现顺序严格一一对应）：
        #   1. filter_params —— eligible CTE 的 WHERE 条件（min_stars 及各维度过滤）
        #   2. hit_params    —— raw_hits 每个词/别名两行分支，每行 4 个参数：
        #                       (group_id, pattern) ×（候选文档分支 + 增强文档分支）
        #   3. scored 匹配强度 —— normalized_query ×3（full_name/名段/title 精确等值）
        #                       + prefix ×3（名段/full_name/title 前缀）
        #   4. 车道边界      —— len(group_ids)（strict 覆盖度）、strict_limit、relaxed_limit
        params = tuple(
            filter_params
            + hit_params
            + [
                normalized_query,
                normalized_query,
                normalized_query,
                prefix,
                prefix,
                prefix,
                len(group_ids),
                strict_limit,
                relaxed_limit,
            ]
        )

        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(sql, params)
                lane_rows = cursor.fetchall()

        def candidates(lane: str) -> tuple[ProjectLexicalCandidate, ...]:
            return tuple(
                ProjectLexicalCandidate(
                    repo_id=str(row.get("repo_id") or ""),
                    lane=lane,
                    term_coverage=int(row.get("term_coverage") or 0),
                    match_strength=int(row.get("match_strength") or 0),
                )
                for row in lane_rows
                if row.get("repo_id") and row.get("lane") == lane
            )

        return ProjectLexicalCandidateLanes(
            strict=candidates("strict"),
            relaxed=candidates("relaxed"),
        )

    def get_project_stars_map(self, repo_ids: list[str]) -> dict[str, int]:
        """采用度压舱石的星数查询；awesome/清单类仓库不参与采用度加成，防清单劫持。"""
        ids = [str(value).strip() for value in repo_ids if str(value or "").strip()][:400]
        if not ids:
            return {}
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(
                    """
                    SELECT repo_id, COALESCE(stars, 0) AS stars
                    FROM github_repo_candidates
                    WHERE repo_id = ANY(%s)
                      AND POSITION(%s IN LOWER(full_name)) = 0
                    """,
                    (ids, "awesome"),
                )
                rows = cursor.fetchall()
        return {
            str(row.get("repo_id") or ""): int(row.get("stars") or 0)
            for row in rows
            if row.get("repo_id")
        }

    def get_project_heat_map(
        self, repo_ids: list[str]
    ) -> dict[str, tuple[float, int, int]]:
        """语义搜索展示序的热度查询，口径与列表 hot 排序一致。

        返回 {repo_id: (hot_score, daily_star_growth, stars)}；hot_score 取
        当日 github_repo_daily_metrics 的 v5 算法分，无当日指标的项目三项
        按 0 兜底，由 stars 在同热度项目间维持量级感。
        """
        ids = [str(value).strip() for value in repo_ids if str(value or "").strip()][:400]
        if not ids:
            return {}
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(
                    """
                    SELECT c.repo_id,
                           COALESCE(gm.hot_score, 0) AS hot_score,
                           COALESCE(gm.daily_star_growth, 0) AS daily_star_growth,
                           COALESCE(c.stars, 0) AS stars
                    FROM github_repo_candidates c
                    LEFT JOIN github_repo_daily_metrics gm
                      ON gm.repo_id = c.repo_id AND gm.metric_date = %s
                    WHERE c.repo_id = ANY(%s)
                    """,
                    (_today(), ids),
                )
                rows = cursor.fetchall()
        return {
            str(row.get("repo_id") or ""): (
                float(row.get("hot_score") or 0),
                int(row.get("daily_star_growth") or 0),
                int(row.get("stars") or 0),
            )
            for row in rows
            if row.get("repo_id")
        }

    def list_github_hot_for_date(
        self,
        *,
        metric_date: str,
        limit: int,
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> list[dict[str, Any]]:
        """看板 GitHub 今日暴涨榜：指定指标日按 hot_score(v5) 排序的正增长仓库。

        收录口径与 list_projects(scope="today") 一致（enriched-only 时为
        succeeded canonical 关系、无星数门槛；daily_growth_available、正增长），
        但日榜额外排除 availability_status='not_found' 的已下架仓库——榜单没有置灰卡片
        形态，上榜仓库必须可访问；项目库列表则保留下架仓库并置灰展示。
        指标日期由调用方传入——看板默认视图可能回溯到窗口内最近有指标的
        日期，历史视图则显式指定；scope="today" 内部硬编码当天，无法复用。
        """
        limit = max(1, min(int(limit or 1), 500))
        conditions = [
            "gm.metric_date = %s",
            "gm.daily_growth_available = TRUE",
            "gm.daily_star_growth > 0",
            _GH_PUBLIC_SUCCEEDED_FILTER if enriched_only else "COALESCE(c.stars, 0) >= %s",
            "c.availability_status = 'active'",
        ]
        params: list[Any] = [metric_date] if enriched_only else [metric_date, min_stars]
        enrichment_join = ""
        if enriched_only:
            enrichment_join = (
                " LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id"
            )
        description_columns = (
            "ge.description_zh, ge.description_en"
            if enriched_only else "NULL AS description_zh, NULL AS description_en"
        )
        params.append(limit)
        sql = f"""
            SELECT c.repo_id, c.full_name, c.title, c.url, c.description,
                   {description_columns},
                   (SELECT '/api/projects/github/logo/' || c.repo_id
                    FROM github_project_logos gl WHERE gl.repo_id = c.repo_id
                    AND gl.content IS NOT NULL) AS image_url,
                   c.language, c.topics_json::text AS topics_json,
                   gm.stars, gm.forks, gm.watchers,
                   gm.daily_star_growth, gm.daily_growth_source,
                   gm.previous_snapshot_date, gm.hot_score, gm.metric_date,
                   gm.growth_suspicion_score, gm.growth_suspicion_signals,
                   gm.growth_corroborated
            FROM github_repo_daily_metrics gm
            JOIN github_repo_candidates c ON c.repo_id = gm.repo_id{enrichment_join}
            WHERE {' AND '.join(conditions)}
            ORDER BY gm.hot_score DESC NULLS LAST,
                     gm.daily_star_growth DESC NULLS LAST,
                     gm.stars DESC NULLS LAST,
                     c.full_name ASC
            LIMIT %s
        """
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(sql, tuple(params))
                return list(cursor.fetchall())

    def list_github_hot_dates(self, *, limit: int = 60) -> list[str]:
        """有日度热度指标（v5）的日期降序列表，供看板 github 分支做日期回溯。"""
        limit = max(1, min(int(limit or 1), 365))
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(
                    """
                    SELECT DISTINCT metric_date
                    FROM github_repo_daily_metrics
                    ORDER BY metric_date DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [
            str(row.get("metric_date") or "") for row in rows if row.get("metric_date")
        ]

    def count_github_catalog_candidates(self, *, min_stars: int = 500) -> int:
        """Count public succeeded canonical GitHub projects.

        ``min_stars`` remains in the signature for protocol compatibility, but
        does not remove successful historical projects that later lose stars.
        """
        del min_stars
        sql = f"""
            SELECT COUNT(*) AS count
            FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
            WHERE {_GH_PUBLIC_SUCCEEDED_FILTER}
        """
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(sql)
                row = cursor.fetchone() or {}
        return int(row.get("count") or 0)

    def list_projects(
        self,
        *,
        source: str = "all",
        scope: str = "all",
        category: str = "",
        subcategory: str = "",
        q: str = "",
        language: str = "",
        tag: str = "",
        page: int = 1,
        page_size: int = 24,
        sort: str = "stars",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
        candidate_repo_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 24), 100))
        source = (source or "all").strip().lower()
        source = source if source in {"all", "github", "website"} else "all"
        scope = (scope or "all").strip().lower()
        scope = scope if scope in {"all", "today", "recommended"} else "all"
        user_id = int(user_id) if user_id else None
        favorites_only = bool(favorites_only and user_id)
        candidates: list[str] | None = None
        if candidate_repo_ids is not None:
            candidates = list(dict.fromkeys(str(value).strip() for value in candidate_repo_ids if str(value).strip()))[:200]
            if not candidates or source == "website":
                return {"items": [], "total": 0, "page": page, "page_size": page_size}
            source = "github"

        # 已下架（not_found）仓库保留在项目库中：条目携带
        # availability_status 由前端渲染置灰卡片，保证列表总数与分类计数、
        # dashboard 统计卡片（github_library_total）口径一致。
        gh_filters = [
            _GH_PUBLIC_SUCCEEDED_FILTER
            if enriched_only
            else f"COALESCE(c.stars, 0) >= %s AND {_GH_CANONICAL_ALIAS_FILTER}"
        ]
        gh_filter_params: list[Any] = [] if enriched_only else [min_stars]
        web_filters = ["TRUE"]
        web_filter_params: list[Any] = []
        if not favorites_only:
            web_filters.append("w.visibility = 'public'")
        if candidates is not None:
            gh_filters.append("c.repo_id = ANY(%s)")
            gh_filter_params.append(candidates)
        if enriched_only:
            gh_filters.append("ge.status = 'succeeded'")
            web_filters.append("(we.status = 'succeeded' OR uo.id IS NOT NULL OR utw.id IS NOT NULL)" if favorites_only else "we.status = 'succeeded'")
        if scope == "today":
            gh_filters += ["COALESCE(gm.daily_growth_available, FALSE)", "COALESCE(gm.daily_star_growth, 0) > 0"]
            web_filters.append("FALSE")
        elif scope == "recommended":
            gh_filters.append("gr.repo_id IS NOT NULL")
            web_filters.append("FALSE")

        user_web = user_id is not None
        effective = _web_effective_expressions(user_web)
        if category:
            gh_filters.append("ge.category_slug = %s"); gh_filter_params.append(category)
            web_filters.append(f"{effective['category_slug']} = %s"); web_filter_params.append(category)
        if subcategory:
            gh_default = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            web_default = WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            gh_filters.append("(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')" if category and subcategory == gh_default else "ge.subcategory_slug = %s")
            web_filters.append(f"({effective['subcategory_slug']} = %s OR COALESCE({effective['subcategory_slug']}, '') = '')" if category and subcategory == web_default else f"{effective['subcategory_slug']} = %s")
            gh_filter_params.append(subcategory); web_filter_params.append(subcategory)
        if language:
            gh_filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)"); gh_filter_params.append(language)
            web_filters.append("FALSE")
        # relevance 排序的公共关键词搜索优先要求强字段命中；强命中不足时降级使用弱字段。
        strong_match_threshold = _strong_match_threshold(sort, q, candidates)
        gh_strong_conditions: list[str] = []
        gh_strong_params: list[Any] = []
        if q:
            terms = project_search_terms(q)
            if not terms:
                gh_filters.append("FALSE"); web_filters.append("FALSE")
            for term in terms:
                like = f"%{escape_like_literal(term)}%"
                gh_filters.append(_term_match_filter(_GH_TERM_MATCH_FIELDS_WITH_I18N_TAGS))
                gh_filter_params.extend([like] * len(_GH_TERM_MATCH_FIELDS_WITH_I18N_TAGS))
                if strong_match_threshold:
                    gh_strong_conditions.append(_term_match_filter(_GH_STRONG_TERM_MATCH_FIELDS))
                    gh_strong_params.extend([like] * len(_GH_STRONG_TERM_MATCH_FIELDS))
                web_filters.append(
                    _term_match_filter(
                        (
                            effective["title"],
                            "w.domain",
                            effective["description"],
                            "w.canonical_url",
                            f"COALESCE({effective['description_zh']}, '')",
                            f"COALESCE({effective['tags']}, '')",
                            f"COALESCE({effective['tags_zh']}, '')",
                            f"COALESCE({effective['tags_en']}, '')",
                        )
                    )
                )
                web_filter_params.extend([like] * 8)
        clean_tag = (tag or "").strip()
        if clean_tag:
            like = f'%"{clean_tag}"%'
            gh_filters.append("COALESCE(ge.tags_json::text, '') ILIKE %s"); gh_filter_params.append(like)
            web_filters.append(f"COALESCE({effective['tags']}, '') ILIKE %s"); web_filter_params.append(like)
        if favorites_only:
            gh_filters.append("pf.id IS NOT NULL")
            web_filters.append("(pf.id IS NOT NULL OR utw.id IS NOT NULL)")

        gh_select, gh_params = _build_gh_branch(
            filters=gh_filters,
            filter_params=gh_filter_params,
            strong_conditions=gh_strong_conditions,
            strong_params=gh_strong_params,
            strong_threshold=strong_match_threshold,
            scope=scope,
            min_stars=min_stars,
            enriched_only=enriched_only,
            user_id=user_id,
        )
        web_select, web_params = _build_web_branch(
            filters=web_filters,
            filter_params=web_filter_params,
            effective=effective,
            strong_threshold=strong_match_threshold,
            user_id=user_id,
        )
        parts: list[str] = []
        params: list[Any] = []
        if source in {"all", "github"}:
            parts.append(gh_select)
            params.extend(gh_params)
        if source in {"all", "website"}:
            parts.append(web_select)
            params.extend(web_params)
        count_sql, rows_sql_prefix, threshold_params = _build_union_queries(parts, strong_match_threshold)
        order, order_params = _resolve_order(sort=sort, scope=scope, q=q, candidates=candidates)
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(count_sql, tuple(params + threshold_params))
                count_row = cursor.fetchone()
                cursor.execute(rows_sql_prefix.replace("{order}", order, 1), tuple(params + threshold_params + order_params + [page_size, (page - 1) * page_size]))
                rows = cursor.fetchall()
        for row in rows:
            row.pop("has_strong_match", None)
        return {"items": [normalize_project_row(row) for row in rows], "total": int(count_row["cnt"] if count_row else 0), "page": page, "page_size": page_size}

    def get_project_categories(
        self,
        *,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
    ) -> dict[str, Any]:
        source = (source or "all").strip().lower()
        source = source if source in {"all", "github", "website"} else "all"
        user_id = int(user_id) if user_id else None
        favorites_only = bool(favorites_only and user_id)
        gh_join = ""
        web_join = ""
        gh_filter = ""
        web_filter = ""
        gh_user: list[Any] = []
        web_user: list[Any] = []
        if user_id:
            gh_join = (
                "LEFT JOIN project_favorites pf"
                " ON pf.user_id=%s AND pf.project_source='github' AND pf.project_id=c.repo_id"
            )
            gh_user = [user_id]
            web_join = (
                "LEFT JOIN project_favorites pf"
                " ON pf.user_id=%s AND pf.project_source='website' AND pf.project_id=w.id::text"
                " LEFT JOIN user_tool_websites utw ON utw.user_id=%s AND utw.website_id=w.id"
            )
            web_user = [user_id, user_id]
            if favorites_only:
                # 与 list_projects 收藏夹分支同一可见性口径：用户自建（utw）或
                # 有覆盖（uo）的网站即使未富化也可见，故必须关联 uo。
                web_join += (
                    " LEFT JOIN user_tool_website_overrides uo"
                    " ON uo.user_id=%s AND uo.website_id=w.id"
                )
                web_user.append(user_id)
                gh_filter = "AND pf.id IS NOT NULL"
                web_filter = "AND (pf.id IS NOT NULL OR utw.id IS NOT NULL)"
        if favorites_only:
            # 复用列表收藏夹分支的可见性谓词（LEFT JOIN + OR 条件），
            # 否则未富化的自建网站在列表可见却不计入分类计数，两者对不上。
            web_enrich_join = (
                "LEFT JOIN tool_website_enrichments we ON we.website_id=w.id"
            )
            status_web = (
                "AND (we.status='succeeded' OR uo.id IS NOT NULL OR utw.id IS NOT NULL)"
                if enriched_only
                else ""
            )
            # 分组键沿用列表的 effective 分类表达式（用户覆盖优先），
            # 保证覆盖过分类的网站与列表行落入同一分类桶。
            web_category_slug = (
                "COALESCE(NULLIF(uo.category_slug, ''), we.category_slug)"
            )
            web_category_name = (
                "COALESCE(NULLIF(uo.category_name_zh, ''), we.category_name_zh,"
                " NULLIF(uo.category_name, ''), we.category_name)"
            )
            web_subcategory_slug = (
                "COALESCE(NULLIF(uo.subcategory_slug, ''), we.subcategory_slug)"
            )
            web_subcategory_name = (
                "COALESCE(NULLIF(uo.subcategory_name_zh, ''), we.subcategory_name_zh,"
                " NULLIF(uo.subcategory_name, ''), we.subcategory_name)"
            )
        else:
            web_enrich_join = "JOIN tool_website_enrichments we ON we.website_id=w.id"
            status_web = "AND we.status='succeeded'" if enriched_only else ""
            web_category_slug = "we.category_slug"
            web_category_name = "we.category_name"
            web_subcategory_slug = "we.subcategory_slug"
            web_subcategory_name = "we.subcategory_name"
        visibility = "" if favorites_only else "AND w.visibility='public'"
        parts: list[str] = []
        params: list[Any] = []
        if source in {"all", "github"}:
            # 分类聚合计数与项目库列表/dashboard 同一口径：enriched-only 时为
            # succeeded canonical 关系（无星数门槛，历史成功项目跌破 500 仍计入）。
            gh_visibility = (
                _GH_PUBLIC_SUCCEEDED_FILTER
                if enriched_only
                else f"COALESCE(c.stars,0)>=%s AND {_GH_CANONICAL_ALIAS_FILTER}"
            )
            parts.append(
                "SELECT ge.category_slug,ge.category_name,"
                "COALESCE(NULLIF(ge.subcategory_slug,''),'') subcategory_slug,"
                "COALESCE(NULLIF(ge.subcategory_name,''),'') subcategory_name,COUNT(*) count"
                " FROM github_repo_candidates c"
                " JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id"
                f" {gh_join}"
                f" WHERE {gh_visibility}"
                f" {gh_filter}"
                " GROUP BY ge.category_slug,ge.category_name,ge.subcategory_slug,ge.subcategory_name"
            )
            params.extend(gh_user + ([] if enriched_only else [min_stars]))
        if source in {"all", "website"}:
            parts.append(
                f"SELECT {web_category_slug} category_slug,{web_category_name} category_name,"
                f"COALESCE(NULLIF({web_subcategory_slug},''),'') subcategory_slug,"
                f"COALESCE(NULLIF({web_subcategory_name},''),'') subcategory_name,COUNT(*) count"
                " FROM tool_websites w"
                f" {web_enrich_join}"
                f" {web_join}"
                " WHERE TRUE"
                f" {status_web} {visibility} {web_filter}"
                f" GROUP BY {web_category_slug},{web_category_name},"
                f"{web_subcategory_slug},{web_subcategory_name}"
            )
            params.extend(web_user)
        aggregate = (
            f"WITH category_rows AS ({' UNION ALL '.join(parts)})"
            " SELECT category_slug,category_name,subcategory_slug,subcategory_name,SUM(count) count"
            " FROM category_rows"
            " GROUP BY category_slug,category_name,subcategory_slug,subcategory_name"
        )
        date = _today()
        start, end = _today_range()
        if source in {"all", "github"}:
            today_sql = (
                "SELECT COUNT(*) count FROM (SELECT c_top.repo_id"
                " FROM github_repo_candidates c_top"
                " JOIN github_repo_enrichments ge_top ON ge_top.repo_id=c_top.repo_id"
                " JOIN github_repo_daily_metrics gm_top ON gm_top.repo_id=c_top.repo_id"
                " AND gm_top.metric_date=%s AND gm_top.daily_growth_available=TRUE"
                " AND gm_top.daily_star_growth>0"
                " WHERE "
                + (_GH_PUBLIC_SUCCEEDED_FILTER.replace("c.", "c_top.").replace("ge.", "ge_top.") if enriched_only else "COALESCE(c_top.stars,0)>=%s")
                + " ORDER BY gm_top.hot_score DESC NULLS LAST,gm_top.daily_star_growth DESC NULLS LAST,"
                + "gm_top.stars DESC NULLS LAST,c_top.full_name ASC"
                f" LIMIT {GITHUB_PROJECT_TODAY_LIMIT}) top"
                " JOIN github_repo_candidates c ON c.repo_id=top.repo_id"
                " JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id"
                f" {gh_join}"
                " WHERE TRUE"
                f" {gh_filter}"
            )
            today_params = [date] + ([] if enriched_only else [min_stars]) + gh_user
        else:
            today_sql = (
                "SELECT COUNT(*) count FROM tool_websites w"
                f" {web_enrich_join}"
                f" {web_join}"
                " WHERE w.first_seen_at>=%s AND w.first_seen_at<%s"
                f" {status_web} {visibility} {web_filter}"
            )
            today_params = web_user + [start, end]
        if source in {"all", "github"}:
            recommended_sql = (
                "SELECT COUNT(*) count FROM github_repo_candidates c"
                " JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id"
                " JOIN github_repo_recommendations gr ON gr.repo_id=c.repo_id AND gr.active=TRUE"
                f" {gh_join}"
                " WHERE "
                + (_GH_PUBLIC_SUCCEEDED_FILTER if enriched_only else "COALESCE(c.stars,0)>=%s")
                + f" {gh_filter}"
            )
            recommended_params = gh_user + ([] if enriched_only else [min_stars])
        else:
            recommended_sql = "SELECT 0 count"
            recommended_params = []
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(aggregate, tuple(params))
                rows = cursor.fetchall()
                cursor.execute(today_sql, tuple(today_params))
                today_row = cursor.fetchone()
                cursor.execute(recommended_sql, tuple(recommended_params))
                recommended_row = cursor.fetchone()
        return format_project_category_counts(
            list(rows),
            int(today_row["count"] if today_row else 0),
            taxonomy=WEBSITE_TAXONOMY if source == "website" else PROJECT_TAXONOMY,
            recommended_count=int(recommended_row["count"] if recommended_row else 0),
        )
