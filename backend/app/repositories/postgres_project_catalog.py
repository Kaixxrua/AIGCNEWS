from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database
from backend.app.repositories.project_catalog_normalization import (
    format_project_category_counts,
    normalize_project_row,
)
from backend.app.services.ingestion.project_taxonomy import (
    DEFAULT_SUBCATEGORY_BY_CATEGORY,
    PROJECT_TAXONOMY,
    WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    WEBSITE_TAXONOMY,
)
from backend.app.services.search_semantics import escape_like_literal, project_search_terms

GITHUB_PROJECT_TODAY_LIMIT = 50


def _today() -> str:
    zone = getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(zone)).date().isoformat()


def _today_range() -> tuple[str, str]:
    zone = ZoneInfo(getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai")
    start = datetime.combine(datetime.now(zone).date(), datetime.min.time(), tzinfo=zone)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


class PostgresProjectCatalogRepository:
    """PostgreSQL implementation of the frozen public project catalog reads."""

    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database

    @staticmethod
    def _begin_read(cursor: Any) -> None:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

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
        filters = ["COALESCE(c.stars, 0) >= %s", "ga.alias_repo_id IS NULL"]
        params: list[Any] = [min_stars]
        if enriched_only:
            filters.append("ge.status = 'succeeded'")
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
            filters.append("(c.full_name ILIKE %s ESCAPE '=' OR c.title ILIKE %s ESCAPE '=' OR c.description ILIKE %s ESCAPE '=' OR COALESCE(ge.description_zh, '') ILIKE %s ESCAPE '=' OR COALESCE(c.language, '') ILIKE %s ESCAPE '=' OR COALESCE(c.topics_json, '') ILIKE %s ESCAPE '=' OR COALESCE(ge.tags_json::text, '') ILIKE %s ESCAPE '=')")
            params.extend([like] * 7)
        prefix = f"{escape_like_literal(normalized_query)}%"
        sql = f"""SELECT c.repo_id FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id
            LEFT JOIN github_repo_aliases ga ON ga.alias_repo_id=c.repo_id AND ga.canonical_repo_id<>c.repo_id
            WHERE {' AND '.join(filters)}
            ORDER BY CASE WHEN LOWER(c.full_name)=LOWER(%s) THEN 0 WHEN LOWER(COALESCE(c.title,''))=LOWER(%s) THEN 1 WHEN c.full_name ILIKE %s ESCAPE '=' THEN 2 WHEN COALESCE(c.title,'') ILIKE %s ESCAPE '=' THEN 3 ELSE 4 END,
                COALESCE(c.stars,0) DESC,c.full_name ASC LIMIT %s"""
        params.extend([normalized_query, normalized_query, prefix, prefix, limit])
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        return [str(row.get("repo_id") or "") for row in rows if row.get("repo_id")]

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

        gh_filters = ["COALESCE(c.stars, 0) >= %s"]
        gh_filter_params: list[Any] = [min_stars]
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
        effective = {
            "full_name": "COALESCE(NULLIF(uo.title, ''), NULLIF(w.title, ''), w.domain)" if user_web else "COALESCE(NULLIF(w.title, ''), w.domain)",
            "title": "COALESCE(NULLIF(uo.title, ''), w.title)" if user_web else "w.title",
            "description": "COALESCE(NULLIF(uo.description, ''), w.description)" if user_web else "w.description",
            "image": "COALESCE(NULLIF(uo.image_url, ''), NULLIF(w.image_url, ''), regexp_replace(w.canonical_url, '^(([^/]+/){2}[^/]+).*$' , '\\1') || '/favicon.ico')" if user_web else "COALESCE(NULLIF(w.image_url, ''), regexp_replace(w.canonical_url, '^(([^/]+/){2}[^/]+).*$' , '\\1') || '/favicon.ico')",
            "category_slug": "COALESCE(NULLIF(uo.category_slug, ''), we.category_slug)" if user_web else "we.category_slug",
            "category_name": "COALESCE(NULLIF(uo.category_name, ''), we.category_name)" if user_web else "we.category_name",
            "subcategory_slug": "COALESCE(NULLIF(uo.subcategory_slug, ''), we.subcategory_slug)" if user_web else "we.subcategory_slug",
            "subcategory_name": "COALESCE(NULLIF(uo.subcategory_name, ''), we.subcategory_name)" if user_web else "we.subcategory_name",
            "description_zh": "COALESCE(NULLIF(uo.description_zh, ''), we.description_zh)" if user_web else "we.description_zh",
            "tags": "COALESCE(NULLIF(uo.tags_json::text, ''), we.tags_json::text)" if user_web else "we.tags_json::text",
        }
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
        if q:
            terms = project_search_terms(q)
            if not terms:
                gh_filters.append("FALSE"); web_filters.append("FALSE")
            for term in terms:
                like = f"%{escape_like_literal(term)}%"
                gh_filters.append("(c.full_name ILIKE %s ESCAPE '=' OR c.title ILIKE %s ESCAPE '=' OR c.description ILIKE %s ESCAPE '=' OR COALESCE(ge.description_zh, '') ILIKE %s ESCAPE '=' OR COALESCE(c.language, '') ILIKE %s ESCAPE '=' OR COALESCE(c.topics_json, '') ILIKE %s ESCAPE '=' OR COALESCE(ge.tags_json::text, '') ILIKE %s ESCAPE '=')")
                gh_filter_params.extend([like] * 7)
                web_filters.append(f"({effective['title']} ILIKE %s ESCAPE '=' OR w.domain ILIKE %s ESCAPE '=' OR {effective['description']} ILIKE %s ESCAPE '=' OR w.canonical_url ILIKE %s ESCAPE '=' OR COALESCE({effective['description_zh']}, '') ILIKE %s ESCAPE '=' OR COALESCE({effective['tags']}, '') ILIKE %s ESCAPE '=')")
                web_filter_params.extend([like] * 6)
        clean_tag = (tag or "").strip()
        if clean_tag:
            like = f'%"{clean_tag}"%'
            gh_filters.append("COALESCE(ge.tags_json::text, '') ILIKE %s"); gh_filter_params.append(like)
            web_filters.append(f"COALESCE({effective['tags']}, '') ILIKE %s"); web_filter_params.append(like)
        if favorites_only:
            gh_filters.append("pf.id IS NOT NULL")
            web_filters.append("(pf.id IS NOT NULL OR utw.id IS NOT NULL)")

        date = _today()
        hot_join = "LEFT JOIN github_repo_daily_metrics gm ON gm.repo_id = c.repo_id AND gm.metric_date = %s"
        gh_params: list[Any] = [date]
        if scope == "today":
            status = "AND ge_top.status = 'succeeded'" if enriched_only else ""
            hot_join += f""" JOIN (SELECT c_top.repo_id FROM github_repo_candidates c_top JOIN github_repo_daily_metrics gm_top ON gm_top.repo_id=c_top.repo_id AND gm_top.metric_date=%s AND gm_top.daily_growth_available=TRUE AND gm_top.daily_star_growth>0 LEFT JOIN github_repo_enrichments ge_top ON ge_top.repo_id=c_top.repo_id WHERE COALESCE(c_top.stars,0)>=%s {status} ORDER BY gm_top.hot_score DESC NULLS LAST, gm_top.daily_star_growth DESC NULLS LAST, gm_top.stars DESC NULLS LAST, c_top.full_name ASC LIMIT {GITHUB_PROJECT_TODAY_LIMIT}) today_top ON today_top.repo_id=c.repo_id"""
            gh_params.extend([date, min_stars])
        gh_user_join = ""
        web_user_join = ""
        if user_id:
            gh_user_join = "LEFT JOIN project_favorites pf ON pf.user_id=%s AND pf.project_source='github' AND pf.project_id=c.repo_id"
            web_user_join = "LEFT JOIN project_favorites pf ON pf.user_id=%s AND pf.project_source='website' AND pf.project_id=w.id::text LEFT JOIN user_tool_websites utw ON utw.user_id=%s AND utw.website_id=w.id LEFT JOIN user_tool_website_overrides uo ON uo.user_id=%s AND uo.website_id=w.id"
            gh_params.append(user_id)
        gh_params.extend(gh_filter_params)
        web_params = ([user_id, user_id, user_id] if user_id else []) + web_filter_params
        gh_favorites = "(pf.id IS NOT NULL) is_favorited, pf.created_at favorited_at, FALSE user_added, NULL::timestamptz user_added_at, pf.created_at collection_at" if user_id else "FALSE is_favorited, NULL::timestamptz favorited_at, FALSE user_added, NULL::timestamptz user_added_at, NULL::timestamptz collection_at"
        web_favorites = "(pf.id IS NOT NULL) is_favorited, pf.created_at favorited_at, (utw.id IS NOT NULL) user_added, utw.created_at user_added_at, COALESCE(pf.created_at,utw.created_at) collection_at" if user_id else "FALSE is_favorited, NULL::timestamptz favorited_at, FALSE user_added, NULL::timestamptz user_added_at, NULL::timestamptz collection_at"
        gh_select = f"""SELECT 'github:'||c.repo_id id,'github' source,c.repo_id,NULL::bigint website_id,c.full_name,c.title,c.url,NULL::text domain,NULL::text image_url,c.description,ge.description_zh,ge.category_slug,ge.category_name,ge.subcategory_slug,ge.subcategory_name,ge.tags_json::text tags_json,c.language,c.topics_json,CASE WHEN gm.repo_id IS NOT NULL THEN gm.stars ELSE COALESCE(c.stars,0) END stars,CASE WHEN gm.repo_id IS NOT NULL THEN gm.forks ELSE COALESCE(c.forks,0) END forks,CASE WHEN gm.repo_id IS NOT NULL THEN gm.watchers ELSE COALESCE(c.watchers,0) END watchers,CASE WHEN gm.repo_id IS NOT NULL THEN gm.open_issues ELSE 0 END open_issues,c.created_at,c.pushed_at,c.first_seen_at,c.last_seen_at,c.last_snapshot_at,gm.metric_date snapshot_date,c.last_snapshot_at captured_at,NULL::integer rank_in_period,COALESCE(gm.daily_star_growth,0) raw_score,COALESCE(gm.hot_score,0) score,gm.metric_date daily_growth_date,gm.previous_snapshot_date,COALESCE(gm.daily_star_growth,0) daily_star_growth,COALESCE(gm.daily_growth_available,FALSE) daily_growth_available,COALESCE(gm.daily_growth_source,'unavailable') daily_growth_source,gm.daily_growth_observed_at,COALESCE(gm.hot_score,0) hot_score,COALESCE(gm.scale_corrected_growth_score,0) scale_corrected_growth_score,COALESCE(gm.growth_acceleration_score,0) growth_acceleration_score,COALESCE(gm.absolute_growth_score,0) absolute_growth_score,COALESCE(gm.maintenance_activity_score,0) maintenance_activity_score,COALESCE(gm.community_engagement_score,0) community_engagement_score,ge.confidence,{gh_favorites[0:]},(gr.repo_id IS NOT NULL) is_recommended,gr.recommended_at FROM github_repo_candidates c LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id LEFT JOIN github_repo_recommendations gr ON gr.repo_id=c.repo_id AND gr.active=TRUE {hot_join} {gh_user_join} WHERE {' AND '.join(gh_filters)}"""
        web_select = f"""SELECT 'website:'||w.id::text id,'website' source,NULL::text repo_id,w.id website_id,{effective['full_name']} full_name,{effective['title']} title,w.canonical_url url,w.domain,{effective['image']} image_url,{effective['description']} description,{effective['description_zh']} description_zh,{effective['category_slug']} category_slug,{effective['category_name']} category_name,{effective['subcategory_slug']} subcategory_slug,{effective['subcategory_name']} subcategory_name,{effective['tags']} tags_json,NULL::text language,'[]' topics_json,0::bigint stars,0::bigint forks,0::bigint watchers,0::bigint open_issues,NULL::text created_at,NULL::text pushed_at,w.first_seen_at::text first_seen_at,w.last_seen_at::text last_seen_at,NULL::text last_snapshot_at,NULL::text snapshot_date,NULL::text captured_at,NULL::integer rank_in_period,0::bigint raw_score,0::double precision score,NULL::text daily_growth_date,NULL::text previous_snapshot_date,0::bigint daily_star_growth,FALSE daily_growth_available,'unavailable' daily_growth_source,NULL::timestamptz daily_growth_observed_at,0::double precision hot_score,0::double precision scale_corrected_growth_score,0::double precision growth_acceleration_score,0::double precision absolute_growth_score,0::double precision maintenance_activity_score,0::double precision community_engagement_score,we.confidence,{web_favorites},FALSE is_recommended,NULL::timestamptz recommended_at FROM tool_websites w LEFT JOIN tool_website_enrichments we ON we.website_id=w.id {web_user_join} WHERE {' AND '.join(web_filters)}"""
        parts: list[str] = []; params: list[Any] = []
        if source in {"all", "github"}: parts.append(gh_select); params.extend(gh_params)
        if source in {"all", "website"}: parts.append(web_select); params.extend(web_params)
        base = f"WITH project_rows AS ({' UNION ALL '.join(parts)})"
        if scope == "today": sort = "hot"
        recent = "COALESCE(recommended_at,collection_at,NULLIF(first_seen_at,'')::timestamptz,NULLIF(last_seen_at,'')::timestamptz)" if scope == "recommended" else "COALESCE(collection_at,NULLIF(first_seen_at,'')::timestamptz,NULLIF(last_seen_at,'')::timestamptz)"
        orders = {"hot":"hot_score DESC NULLS LAST,daily_star_growth DESC NULLS LAST,stars DESC,full_name ASC","stars":"stars DESC,forks DESC,full_name ASC","updated":"COALESCE(NULLIF(pushed_at,''),last_seen_at::text,first_seen_at::text) DESC NULLS LAST,stars DESC,full_name ASC","recent":f"{recent} DESC NULLS LAST,stars DESC,full_name ASC","name":"full_name ASC"}
        order = orders.get(sort, orders["hot"] if scope == "today" else orders["stars"])
        order_params: list[Any] = []
        if sort == "relevance" and candidates is not None:
            order = "array_position(%s::text[],repo_id),full_name ASC"
            order_params.append(candidates)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(base + " SELECT COUNT(*) AS cnt FROM project_rows", tuple(params))
                count_row = cursor.fetchone()
                cursor.execute(base + f" SELECT * FROM project_rows ORDER BY {order} LIMIT %s OFFSET %s", tuple(params + order_params + [page_size, (page - 1) * page_size]))
                rows = cursor.fetchall()
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
        gh_join = ""; web_join = ""; gh_filter = ""; web_filter = ""; gh_user: list[Any] = []; web_user: list[Any] = []
        if user_id:
            gh_join = "LEFT JOIN project_favorites pf ON pf.user_id=%s AND pf.project_source='github' AND pf.project_id=c.repo_id"; gh_user=[user_id]
            web_join = "LEFT JOIN project_favorites pf ON pf.user_id=%s AND pf.project_source='website' AND pf.project_id=w.id::text LEFT JOIN user_tool_websites utw ON utw.user_id=%s AND utw.website_id=w.id"; web_user=[user_id,user_id]
            if favorites_only: gh_filter="AND pf.id IS NOT NULL"; web_filter="AND (pf.id IS NOT NULL OR utw.id IS NOT NULL)"
        status_gh = "AND ge.status='succeeded'" if enriched_only else ""
        status_web = "AND we.status='succeeded'" if enriched_only else ""
        visibility = "" if favorites_only else "AND w.visibility='public'"
        parts: list[str]=[]; params: list[Any]=[]
        if source in {"all","github"}:
            parts.append(f"SELECT ge.category_slug,ge.category_name,COALESCE(NULLIF(ge.subcategory_slug,''),'') subcategory_slug,COALESCE(NULLIF(ge.subcategory_name,''),'') subcategory_name,COUNT(*) count FROM github_repo_candidates c JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id {gh_join} WHERE COALESCE(c.stars,0)>=%s {status_gh} {gh_filter} GROUP BY ge.category_slug,ge.category_name,ge.subcategory_slug,ge.subcategory_name")
            params.extend(gh_user+[min_stars])
        if source in {"all","website"}:
            parts.append(f"SELECT we.category_slug,we.category_name,COALESCE(NULLIF(we.subcategory_slug,''),'') subcategory_slug,COALESCE(NULLIF(we.subcategory_name,''),'') subcategory_name,COUNT(*) count FROM tool_websites w JOIN tool_website_enrichments we ON we.website_id=w.id {web_join} WHERE TRUE {status_web} {visibility} {web_filter} GROUP BY we.category_slug,we.category_name,we.subcategory_slug,we.subcategory_name")
            params.extend(web_user)
        aggregate = f"WITH category_rows AS ({' UNION ALL '.join(parts)}) SELECT category_slug,category_name,subcategory_slug,subcategory_name,SUM(count) count FROM category_rows GROUP BY category_slug,category_name,subcategory_slug,subcategory_name"
        date = _today(); start,end = _today_range()
        if source in {"all","github"}:
            today_sql=f"SELECT COUNT(*) count FROM (SELECT c_top.repo_id FROM github_repo_candidates c_top JOIN github_repo_enrichments ge_top ON ge_top.repo_id=c_top.repo_id JOIN github_repo_daily_metrics gm_top ON gm_top.repo_id=c_top.repo_id AND gm_top.metric_date=%s AND gm_top.daily_growth_available=TRUE AND gm_top.daily_star_growth>0 WHERE COALESCE(c_top.stars,0)>=%s {'AND ge_top.status=\'succeeded\'' if enriched_only else ''} ORDER BY gm_top.hot_score DESC NULLS LAST,gm_top.daily_star_growth DESC NULLS LAST,gm_top.stars DESC NULLS LAST,c_top.full_name ASC LIMIT {GITHUB_PROJECT_TODAY_LIMIT}) top JOIN github_repo_candidates c ON c.repo_id=top.repo_id JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id {gh_join} WHERE TRUE {gh_filter}"
            today_params=[date,min_stars]+gh_user
        else:
            today_sql=f"SELECT COUNT(*) count FROM tool_websites w JOIN tool_website_enrichments we ON we.website_id=w.id {web_join} WHERE w.first_seen_at>=%s AND w.first_seen_at<%s {status_web} {visibility} {web_filter}"
            today_params=web_user+[start,end]
        if source in {"all","github"}:
            recommended_sql=f"SELECT COUNT(*) count FROM github_repo_candidates c JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id JOIN github_repo_recommendations gr ON gr.repo_id=c.repo_id AND gr.active=TRUE {gh_join} WHERE COALESCE(c.stars,0)>=%s {status_gh} {gh_filter}"
            recommended_params=gh_user+[min_stars]
        else:
            recommended_sql="SELECT 0 count"; recommended_params=[]
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                self._begin_read(cursor)
                cursor.execute(aggregate,tuple(params)); rows=cursor.fetchall()
                cursor.execute(today_sql,tuple(today_params)); today_row=cursor.fetchone()
                cursor.execute(recommended_sql,tuple(recommended_params)); recommended_row=cursor.fetchone()
        return format_project_category_counts(list(rows),int(today_row["count"] if today_row else 0),taxonomy=WEBSITE_TAXONOMY if source=="website" else PROJECT_TAXONOMY,recommended_count=int(recommended_row["count"] if recommended_row else 0))
