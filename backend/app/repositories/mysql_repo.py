from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

import pymysql

from backend.app.core.config import settings
from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.repositories.mysql_briefing_repository import MySQLBriefingRepository
from backend.app.repositories.mysql_briefing_subscription_repository import (
    MySQLBriefingSubscriptionRepository,
)
from backend.app.repositories.mysql_evaluation_repository import (
    MySQLEvaluationRepository,
)
from backend.app.repositories.mysql_ingestion_task_repository import (
    MySQLIngestionTaskRepository,
)
from backend.app.repositories.mysql_mcp_access_token_repository import (
    MySQLMcpAccessTokenRepository,
)
from backend.app.repositories.mysql_mcp_server_repository import (
    MySQLMcpServerConfigRepository,
)
from backend.app.repositories.mysql_user_account_repository import (
    MySQLUserAccountRepository,
)
from backend.app.services.ingestion.project_taxonomy import (
    CATEGORY_BY_SLUG,
    DEFAULT_SUBCATEGORY_BY_CATEGORY,
    PROJECT_TAXONOMY,
    SUBCATEGORY_BY_CATEGORY_SLUG,
    WEBSITE_CATEGORY_BY_SLUG,
    WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG,
    WEBSITE_TAXONOMY,
)
from backend.app.services.search_semantics import (
    TECHNICAL_TOKEN_RE,
    escape_like_literal,
    normalize_search_query,
    project_search_terms,
)


logger = logging.getLogger(__name__)

GITHUB_PROJECT_TODAY_LIMIT = 50

SNAPSHOT_PERIOD_CHANNELS: Dict[str, Dict[str, tuple[str, ...]]] = {
    "arxiv": {
        "daily": ("huggingface_daily_html",),
        "weekly": ("huggingface_weekly_html",),
        "monthly": ("huggingface_monthly_html",),
    },
    "github": {
        "daily": ("github_trending_daily", "github_hot_daily", "github_fallback"),
        "weekly": ("github_trending_weekly", "github_hot_weekly"),
        "monthly": ("github_trending_monthly", "github_hot_monthly"),
    },
    "news": {"daily": ("techmeme_daily_rss",)},
    "producthunt": {
        "daily": ("producthunt_daily_html",),
        "weekly": ("producthunt_weekly_html",),
        "monthly": ("producthunt_monthly_html",),
    },
    "hackernews": {
        "daily": ("hn_daily_html",),
        "weekly": ("hn_weekly_html",),
        "monthly": ("hn_monthly_html",),
    },
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc_range(tz_name: str | None = None) -> tuple[str, str]:
    active_tz = tz_name or getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    local_tz = ZoneInfo(active_tz)
    today = datetime.now(local_tz).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=local_tz)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def _today_local_date(tz_name: str | None = None) -> str:
    active_tz = tz_name or getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(active_tz)).date().isoformat()


def _normalize_doc_lookup_key(value: Optional[str]) -> str:
    return (value or "").strip()


_DOCUMENT_SEARCH_INTENT_PHRASES = (
    "learning resources",
    "learning materials",
    "help me find",
    "i would like to",
    "related content",
    "找一些",
    "找一点",
    "相关的内容",
    "相关内容",
    "学习资料",
    "学习材料",
    "进行学习",
    "我想要",
    "帮我找",
    "i want to",
    "find me",
)
_DOCUMENT_SEARCH_STOP_TERMS = {
    "about",
    "content",
    "find",
    "help",
    "learn",
    "learning",
    "material",
    "materials",
    "related",
    "resource",
    "resources",
    "tutorial",
    "tutorials",
    "want",
    "学习",
    "内容",
    "帮我",
    "教程",
    "资料",
}
_DOCUMENT_SEARCH_TOKEN_RE = TECHNICAL_TOKEN_RE


def _normalize_document_search_query(value: str) -> str:
    return normalize_search_query(value)


def _document_search_candidates(query: str, *, max_terms: int = 5) -> List[str]:
    normalized = _normalize_document_search_query(query)
    if not normalized:
        return []

    lowered = normalized.casefold()
    has_intent = any(phrase in lowered for phrase in _DOCUMENT_SEARCH_INTENT_PHRASES)
    if not has_intent and len(normalized) <= 48:
        return [normalized]

    cleaned = normalized
    for phrase in sorted(_DOCUMENT_SEARCH_INTENT_PHRASES, key=len, reverse=True):
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(^|[\s,，。！？!?;:：；])(?:学习|帮我)(?=[A-Za-z0-9])", r"\1", cleaned)
    cleaned = " ".join(cleaned.strip(" ，。！？,.!?;:：；").split())

    candidates = [normalized]
    residual_intent = any(term in cleaned.casefold() for term in _DOCUMENT_SEARCH_STOP_TERMS)
    if cleaned and not residual_intent and cleaned.casefold() != normalized.casefold():
        candidates.append(cleaned)

    seen = {candidate.casefold() for candidate in candidates}
    technical_terms: List[str] = []
    for token in _DOCUMENT_SEARCH_TOKEN_RE.findall(cleaned or normalized):
        key = token.casefold()
        if key in _DOCUMENT_SEARCH_STOP_TERMS or key in seen:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        seen.add(key)
        technical_terms.append(token)
        if len(technical_terms) >= max(1, min(max_terms, 5)):
            break

    if len(technical_terms) > 1 and any(term.casefold() != "ai" for term in technical_terms):
        technical_terms = [term for term in technical_terms if term.casefold() != "ai"]
    candidates.extend(technical_terms)
    return candidates


def _escape_like_literal(value: str, *, escape: str = "=") -> str:
    return escape_like_literal(value, escape=escape)


def _json_dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _json_loads_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        data = []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _normalize_github_project_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["topics"] = _json_loads_list(item.pop("topics_json", None))
    item["tags"] = _json_loads_list(item.pop("tags_json", None))
    item["stars"] = _as_int(item.get("stars"))
    item["forks"] = _as_int(item.get("forks"))
    item["watchers"] = _as_int(item.get("watchers"))
    item["open_issues"] = _as_int(item.get("open_issues"))
    item["rank_in_period"] = _as_int(item.get("rank_in_period")) or None
    item["raw_score"] = _as_float(item.get("raw_score"))
    item["score"] = _as_float(item.get("score"))
    item["confidence"] = _as_float(item.get("confidence"))
    item["daily_star_growth"] = _as_int(item.get("daily_star_growth"))
    item["daily_growth_available"] = bool(_as_int(item.get("daily_growth_available")))
    item["daily_growth_source"] = str(item.get("daily_growth_source") or "unavailable")
    item["daily_growth_observed_at"] = _to_iso_string(item.get("daily_growth_observed_at"))
    item["hot_score"] = _as_float(item.get("hot_score"))
    item["scale_corrected_growth_score"] = _as_float(item.get("scale_corrected_growth_score"))
    item["growth_acceleration_score"] = _as_float(item.get("growth_acceleration_score"))
    item["absolute_growth_score"] = _as_float(item.get("absolute_growth_score"))
    item["maintenance_activity_score"] = _as_float(item.get("maintenance_activity_score"))
    item["community_engagement_score"] = _as_float(item.get("community_engagement_score"))
    item["is_recommended"] = bool(item.get("is_recommended"))
    item["recommended_at"] = _to_iso_string(item.get("recommended_at"))
    item.setdefault("source", "github")
    item.setdefault("id", f"github:{item.get('repo_id') or item.get('full_name') or ''}")
    return item


def _to_iso_string(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _normalize_project_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["topics"] = _json_loads_list(item.pop("topics_json", None))
    item["tags"] = _json_loads_list(item.pop("tags_json", None))
    item["stars"] = _as_int(item.get("stars"))
    item["forks"] = _as_int(item.get("forks"))
    item["watchers"] = _as_int(item.get("watchers"))
    item["open_issues"] = _as_int(item.get("open_issues"))
    item["rank_in_period"] = _as_int(item.get("rank_in_period")) or None
    item["raw_score"] = _as_float(item.get("raw_score"))
    item["score"] = _as_float(item.get("score"))
    item["confidence"] = _as_float(item.get("confidence"))
    item["daily_star_growth"] = _as_int(item.get("daily_star_growth"))
    item["daily_growth_available"] = bool(_as_int(item.get("daily_growth_available")))
    item["daily_growth_source"] = str(item.get("daily_growth_source") or "unavailable")
    item["daily_growth_observed_at"] = _to_iso_string(item.get("daily_growth_observed_at"))
    item["hot_score"] = _as_float(item.get("hot_score"))
    item["scale_corrected_growth_score"] = _as_float(item.get("scale_corrected_growth_score"))
    item["growth_acceleration_score"] = _as_float(item.get("growth_acceleration_score"))
    item["absolute_growth_score"] = _as_float(item.get("absolute_growth_score"))
    item["maintenance_activity_score"] = _as_float(item.get("maintenance_activity_score"))
    item["community_engagement_score"] = _as_float(item.get("community_engagement_score"))
    item["is_favorited"] = bool(item.get("is_favorited"))
    item["favorited_at"] = _to_iso_string(item.get("favorited_at"))
    item["is_recommended"] = bool(item.get("is_recommended"))
    item["recommended_at"] = _to_iso_string(item.get("recommended_at"))
    item["user_added"] = bool(item.get("user_added"))
    item["user_added_at"] = _to_iso_string(item.get("user_added_at"))
    if item.get("source") == "website":
        category_slug = item.get("category_slug") or "other"
        subcategory_slug = item.get("subcategory_slug") or WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category_slug, "")
        item["category_slug"] = category_slug
        item["subcategory_slug"] = subcategory_slug
        item["category_name"] = WEBSITE_CATEGORY_BY_SLUG.get(category_slug, item.get("category_name") or "其他网站")
        item["subcategory_name"] = WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG.get(category_slug, {}).get(
            subcategory_slug,
            item.get("subcategory_name") or "未分类",
        )
    else:
        category_slug = item.get("category_slug") or "other"
        subcategory_slug = item.get("subcategory_slug") or DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category_slug, "")
        item["category_slug"] = category_slug
        item["subcategory_slug"] = subcategory_slug
        item["category_name"] = CATEGORY_BY_SLUG.get(category_slug, item.get("category_name") or "其他")
        item["subcategory_name"] = SUBCATEGORY_BY_CATEGORY_SLUG.get(category_slug, {}).get(
            subcategory_slug,
            item.get("subcategory_name") or "未分类",
        )
    return item


def _format_project_category_counts(
    rows: List[Dict[str, Any]],
    today_count: int = 0,
    *,
    taxonomy: List[Dict[str, Any]] | None = None,
    recommended_count: int = 0,
) -> Dict[str, Any]:
    active_taxonomy = taxonomy or PROJECT_TAXONOMY
    taxonomy_by_slug = {item["slug"]: item for item in active_taxonomy}
    default_child_by_category: Dict[str, Dict[str, str]] = {}
    for category in active_taxonomy:
        children = category.get("children", [])
        if children:
            default_child_by_category[category["slug"]] = next(
                (child for child in children if child.get("default")),
                children[-1],
            )

    category_counts: Dict[str, int] = {}
    category_names: Dict[str, str] = {}
    child_counts: Dict[tuple[str, str], int] = {}
    child_names: Dict[tuple[str, str], str] = {}
    for row in rows:
        category_slug = row.get("category_slug") or "other"
        category_name = row.get("category_name") or taxonomy_by_slug.get(category_slug, {}).get("name") or "其他"
        count = int(row.get("count") or 0)
        child_slug = row.get("subcategory_slug") or ""
        child_name = row.get("subcategory_name") or ""
        if not child_slug:
            default_child = default_child_by_category.get(category_slug) or default_child_by_category.get("other")
            if default_child:
                child_slug = default_child["slug"]
                child_name = default_child["name"]
        category_counts[category_slug] = category_counts.get(category_slug, 0) + count
        category_names[category_slug] = category_name
        if child_slug:
            key = (category_slug, child_slug)
            child_counts[key] = child_counts.get(key, 0) + count
            child_names[key] = child_name or child_slug

    items: List[Dict[str, Any]] = []
    seen_categories: Set[str] = set()
    for category in active_taxonomy:
        category_slug = category["slug"]
        seen_categories.add(category_slug)
        children = [
            {
                "slug": child["slug"],
                "name": child["name"],
                "count": child_counts.get((category_slug, child["slug"]), 0),
            }
            for child in category.get("children", [])
        ]
        items.append(
            {
                "slug": category_slug,
                "name": category["name"],
                "count": category_counts.get(category_slug, 0),
                "kind": "category",
                "children": children,
            }
        )

    for category_slug in sorted(
        (slug for slug in category_counts if slug not in seen_categories),
        key=lambda slug: (-category_counts.get(slug, 0), category_names.get(slug, slug)),
    ):
        dynamic_children = [
            {
                "slug": child_slug,
                "name": child_names.get((category_slug, child_slug), child_slug),
                "count": child_counts.get((category_slug, child_slug), 0),
            }
            for (parent_slug, child_slug) in child_counts
            if parent_slug == category_slug
        ]
        items.append(
            {
                "slug": category_slug,
                "name": category_names.get(category_slug, "其他"),
                "count": category_counts.get(category_slug, 0),
                "kind": "category",
                "children": dynamic_children,
            }
        )

    return {
        "items": items,
        "total": sum(category_counts.values()),
        "today_count": int(today_count or 0),
        "recommended_count": int(recommended_count or 0),
    }


class MySQLRepository:
    """MySQL repository for metadata, task records, briefings, eval results and GitHub hotness."""

    _schema_initialized = False
    _schema_lock = Lock()

    def __init__(self, database: DatabaseLifecycle | None = None) -> None:
        self._database = database or mysql_database
        self._ingestion_tasks: MySQLIngestionTaskRepository | None = None
        self._briefings: MySQLBriefingRepository | None = None
        self._briefing_subscriptions: MySQLBriefingSubscriptionRepository | None = None
        self._evaluations: MySQLEvaluationRepository | None = None
        self._mcp_server_configs: MySQLMcpServerConfigRepository | None = None
        self._mcp_access_tokens: MySQLMcpAccessTokenRepository | None = None
        self._user_accounts: MySQLUserAccountRepository | None = None
        if not MySQLRepository._schema_initialized:
            with MySQLRepository._schema_lock:
                if not MySQLRepository._schema_initialized:
                    self._init_schema()
                    MySQLRepository._schema_initialized = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self):
        return self._database.connect()

    @property
    def ingestion_tasks(self) -> MySQLIngestionTaskRepository:
        if self._ingestion_tasks is None:
            self._ingestion_tasks = MySQLIngestionTaskRepository(self._database)
        return self._ingestion_tasks

    @property
    def briefings(self) -> MySQLBriefingRepository:
        if self._briefings is None:
            self._briefings = MySQLBriefingRepository(self._database)
        return self._briefings

    @property
    def briefing_subscriptions(self) -> MySQLBriefingSubscriptionRepository:
        if self._briefing_subscriptions is None:
            self._briefing_subscriptions = MySQLBriefingSubscriptionRepository(
                self._database
            )
        return self._briefing_subscriptions

    @property
    def evaluations(self) -> MySQLEvaluationRepository:
        if self._evaluations is None:
            self._evaluations = MySQLEvaluationRepository(self._database)
        return self._evaluations

    @property
    def mcp_server_configs(self) -> MySQLMcpServerConfigRepository:
        if self._mcp_server_configs is None:
            defaults = (
                ("arxiv", "Arxiv MCP", getattr(settings, "arxiv_mcp_url", "") or ""),
                ("github", "GitHub MCP", getattr(settings, "github_mcp_url", "") or ""),
            )
            self._mcp_server_configs = MySQLMcpServerConfigRepository(
                self._database,
                defaults,
            )
        return self._mcp_server_configs

    @property
    def mcp_access_tokens(self) -> MySQLMcpAccessTokenRepository:
        if self._mcp_access_tokens is None:
            self._mcp_access_tokens = MySQLMcpAccessTokenRepository(self._database)
        return self._mcp_access_tokens

    @property
    def user_accounts(self) -> MySQLUserAccountRepository:
        if self._user_accounts is None:
            self._user_accounts = MySQLUserAccountRepository(self._database)
        return self._user_accounts

    def resolve_github_repo_id(self, repo_id: str = "", full_name: str = "") -> str:
        """Return the canonical repo_id for a GitHub repository identity."""
        repo_id = (repo_id or "").strip()
        full_name = (full_name or "").strip()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                resolved = self._resolve_github_repo_id_cur(cur, repo_id, full_name)
            conn.commit()
            return resolved
        finally:
            conn.close()

    def _resolve_github_repo_id_cur(self, cur, repo_id: str = "", full_name: str = "") -> str:
        repo_id = (repo_id or "").strip()
        full_name = (full_name or "").strip()
        if repo_id:
            cur.execute(
                """
                SELECT canonical_repo_id
                FROM github_repo_aliases
                WHERE alias_repo_id = %s
                LIMIT 1
                """,
                (repo_id,),
            )
            row = cur.fetchone()
            if row and row.get("canonical_repo_id"):
                return str(row["canonical_repo_id"])

        if full_name:
            cur.execute(
                """
                SELECT repo_id
                FROM github_repo_candidates
                WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                ORDER BY (repo_id = full_name) DESC,
                         COALESCE(stars, 0) DESC,
                         COALESCE(last_seen_at, '') DESC
                LIMIT 1
                """,
                (full_name,),
            )
            row = cur.fetchone()
            if row and row.get("repo_id"):
                return str(row["repo_id"])
        return full_name or repo_id

    def _upsert_github_repo_alias_cur(
        self,
        cur,
        *,
        alias_repo_id: str,
        canonical_repo_id: str,
        full_name: str,
    ) -> None:
        alias_repo_id = (alias_repo_id or "").strip()
        canonical_repo_id = (canonical_repo_id or "").strip()
        full_name = (full_name or "").strip()
        if not alias_repo_id or not canonical_repo_id or alias_repo_id == canonical_repo_id:
            return
        now = _utcnow()
        cur.execute(
            """
            INSERT INTO github_repo_aliases (
                alias_repo_id, canonical_repo_id, full_name, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                canonical_repo_id=VALUES(canonical_repo_id),
                full_name=VALUES(full_name),
                updated_at=VALUES(updated_at)
            """,
            (alias_repo_id, canonical_repo_id, full_name, now, now),
        )

    def _init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS documents (
                id VARCHAR(255) NOT NULL PRIMARY KEY,
                source VARCHAR(64),
                source_channel VARCHAR(64) DEFAULT '',
                title VARCHAR(1024),
                url VARCHAR(1024),
                summary TEXT,
                published_date VARCHAR(64),
                tags TEXT,
                score DOUBLE DEFAULT 0.0,
                raw_score DOUBLE DEFAULT 0.0,
                stars INT DEFAULT 0,
                forks INT DEFAULT 0,
                language VARCHAR(128) DEFAULT '',
                rank_in_period INT DEFAULT 9999,
                indexed TINYINT DEFAULT 0,
                in_daily TINYINT DEFAULT 0,
                in_weekly TINYINT DEFAULT 0,
                in_monthly TINYINT DEFAULT 0,
                local_pdf_path VARCHAR(512) DEFAULT NULL,
                created_at VARCHAR(64)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS ingestion_tasks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                task_name VARCHAR(255) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                started_at VARCHAR(64),
                finished_at VARCHAR(64),
                error_msg TEXT,
                item_count INT DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS briefings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                date VARCHAR(64) NOT NULL,
                content MEDIUMTEXT NOT NULL,
                created_at VARCHAR(64)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS rag_evaluations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                query TEXT NOT NULL,
                answer MEDIUMTEXT,
                sources_json MEDIUMTEXT,
                recall_score DOUBLE,
                citation_score DOUBLE,
                subjective_score DOUBLE,
                evaluated_at VARCHAR(64)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_repo_candidates (
                repo_id VARCHAR(255) NOT NULL PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                title VARCHAR(512),
                url VARCHAR(1024),
                description TEXT,
                language VARCHAR(128),
                topics_json TEXT,
                created_at VARCHAR(64),
                pushed_at VARCHAR(64),
                stars INT DEFAULT 0,
                forks INT DEFAULT 0,
                watchers INT DEFAULT 0,
                source_channels VARCHAR(512),
                first_seen_at VARCHAR(64),
                last_seen_at VARCHAR(64),
                last_snapshot_at VARCHAR(64),
                UNIQUE KEY uq_gh_repo_full_name (full_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_repo_aliases (
                alias_repo_id VARCHAR(255) NOT NULL PRIMARY KEY,
                canonical_repo_id VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                created_at VARCHAR(64),
                updated_at VARCHAR(64),
                INDEX idx_gh_repo_alias_canonical (canonical_repo_id),
                INDEX idx_gh_repo_alias_full_name (full_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_repo_snapshots (
                id INT AUTO_INCREMENT PRIMARY KEY,
                repo_id VARCHAR(255) NOT NULL,
                snapshot_date VARCHAR(16) NOT NULL,
                captured_at VARCHAR(64) NOT NULL,
                stars INT DEFAULT 0,
                forks INT DEFAULT 0,
                watchers INT DEFAULT 0,
                community_metrics_complete TINYINT(1) NULL DEFAULT NULL,
                open_issues INT DEFAULT 0,
                repo_created_at VARCHAR(64),
                repo_pushed_at VARCHAR(64),
                UNIQUE KEY uq_repo_snap (repo_id, snapshot_date),
                INDEX idx_gh_snapshots_date_repo (snapshot_date, repo_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_repo_daily_metrics (
                repo_id VARCHAR(255) NOT NULL,
                metric_date VARCHAR(16) NOT NULL,
                stars INT DEFAULT 0,
                forks INT DEFAULT 0,
                watchers INT DEFAULT 0,
                open_issues INT DEFAULT 0,
                previous_snapshot_date VARCHAR(16),
                previous_stars INT DEFAULT 0,
                daily_star_growth INT DEFAULT 0,
                daily_fork_growth INT DEFAULT 0,
                daily_watcher_growth INT DEFAULT 0,
                daily_growth_available TINYINT(1) NOT NULL DEFAULT 0,
                daily_growth_source VARCHAR(32) NOT NULL DEFAULT 'unavailable',
                daily_growth_observed_at VARCHAR(64),
                scale_corrected_growth_score DOUBLE DEFAULT 0.0,
                growth_acceleration_score DOUBLE DEFAULT 0.0,
                absolute_growth_score DOUBLE DEFAULT 0.0,
                maintenance_activity_score DOUBLE DEFAULT 0.0,
                community_engagement_score DOUBLE DEFAULT 0.0,
                hot_score DOUBLE DEFAULT 0.0,
                score_version VARCHAR(32) NOT NULL DEFAULT 'daily_hot_v4',
                updated_at VARCHAR(64),
                PRIMARY KEY (repo_id, metric_date),
                INDEX idx_gh_daily_metrics_date_hot (metric_date, hot_score),
                INDEX idx_gh_daily_metrics_date_growth (metric_date, daily_star_growth)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_trending_hits (
                id INT AUTO_INCREMENT PRIMARY KEY,
                repo_id VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                period VARCHAR(16) NOT NULL,
                language VARCHAR(128),
                `rank` INT,
                observed_date VARCHAR(16) NOT NULL,
                captured_at VARCHAR(64) NOT NULL,
                period_star_growth INT NULL,
                period_growth_observed_at VARCHAR(64) NULL,
                UNIQUE KEY uq_trend (repo_id, period, observed_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_repo_enrichments (
                repo_id VARCHAR(255) NOT NULL PRIMARY KEY,
                category_slug VARCHAR(64) NOT NULL,
                category_name VARCHAR(128) NOT NULL,
                subcategory_slug VARCHAR(64) NOT NULL DEFAULT '',
                subcategory_name VARCHAR(128) NOT NULL DEFAULT '',
                description_zh VARCHAR(512) NOT NULL,
                tags_json TEXT,
                confidence DOUBLE DEFAULT 0.0,
                source_fingerprint VARCHAR(64) NOT NULL,
                prompt_version VARCHAR(32) NOT NULL,
                model_provider VARCHAR(64) DEFAULT '',
                model_name VARCHAR(255) DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'succeeded',
                error_msg TEXT,
                enriched_at VARCHAR(64),
                updated_at VARCHAR(64),
                INDEX idx_gh_repo_enrich_category (category_slug, status),
                INDEX idx_gh_repo_enrich_subcategory (subcategory_slug, status),
                INDEX idx_gh_repo_enrich_category_subcategory (category_slug, subcategory_slug, status),
                INDEX idx_gh_repo_enrich_status (status, updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_project_semantic_sources (
                repo_id VARCHAR(255) NOT NULL PRIMARY KEY,
                readme_text MEDIUMTEXT,
                readme_sha256 CHAR(64) NOT NULL DEFAULT '',
                readme_etag VARCHAR(512) NOT NULL DEFAULT '',
                readme_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                readme_checked_at VARCHAR(64),
                readme_fetched_at VARCHAR(64),
                readme_repo_pushed_at VARCHAR(64),
                readme_error TEXT,
                readme_retry_count INT NOT NULL DEFAULT 0,
                readme_next_retry_at VARCHAR(64),
                source_fingerprint CHAR(64) NOT NULL DEFAULT '',
                indexed_fingerprint CHAR(64) NOT NULL DEFAULT '',
                index_version VARCHAR(32) NOT NULL DEFAULT '',
                embedding_provider VARCHAR(64) NOT NULL DEFAULT '',
                embedding_model VARCHAR(255) NOT NULL DEFAULT '',
                embedding_dimension INT NOT NULL DEFAULT 0,
                chunk_count INT NOT NULL DEFAULT 0,
                index_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                index_error TEXT,
                index_retry_count INT NOT NULL DEFAULT 0,
                index_next_retry_at VARCHAR(64),
                indexed_at VARCHAR(64),
                updated_at VARCHAR(64),
                INDEX idx_project_semantic_readme_status (readme_status, readme_checked_at),
                INDEX idx_project_semantic_index_status (index_status, indexed_at),
                INDEX idx_project_semantic_fingerprint (indexed_fingerprint)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS tool_websites (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                canonical_url VARCHAR(1024) NOT NULL,
                normalized_url_hash CHAR(64) NOT NULL,
                domain VARCHAR(255) NOT NULL,
                title VARCHAR(512) DEFAULT '',
                description TEXT,
                image_url VARCHAR(1024) DEFAULT '',
                raw_metadata_json MEDIUMTEXT,
                fetch_status VARCHAR(32) NOT NULL DEFAULT 'succeeded',
                fetch_error TEXT,
                source_fingerprint CHAR(64) NOT NULL,
                visibility ENUM('public', 'private') NOT NULL DEFAULT 'public',
                added_by_user_id INT NULL,
                first_seen_at VARCHAR(64),
                last_seen_at VARCHAR(64),
                updated_at VARCHAR(64),
                UNIQUE KEY uq_tool_website_url_hash (normalized_url_hash),
                INDEX idx_tool_website_domain (domain),
                INDEX idx_tool_website_visibility (visibility, first_seen_at),
                INDEX idx_tool_website_added_by_user (added_by_user_id),
                INDEX idx_tool_website_fetch_status (fetch_status, updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS tool_website_enrichments (
                website_id BIGINT NOT NULL PRIMARY KEY,
                category_slug VARCHAR(64) NOT NULL,
                category_name VARCHAR(128) NOT NULL,
                subcategory_slug VARCHAR(64) NOT NULL DEFAULT '',
                subcategory_name VARCHAR(128) NOT NULL DEFAULT '',
                description_zh VARCHAR(512) NOT NULL,
                tags_json TEXT,
                confidence DOUBLE DEFAULT 0.0,
                source_fingerprint CHAR(64) NOT NULL,
                prompt_version VARCHAR(32) NOT NULL,
                model_provider VARCHAR(64) DEFAULT '',
                model_name VARCHAR(255) DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'succeeded',
                error_msg TEXT,
                enriched_at VARCHAR(64),
                updated_at VARCHAR(64),
                INDEX idx_tool_website_enrich_category (category_slug, status),
                INDEX idx_tool_website_enrich_subcategory (subcategory_slug, status),
                INDEX idx_tool_website_enrich_category_subcategory (category_slug, subcategory_slug, status),
                INDEX idx_tool_website_enrich_status (status, updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS document_rank_snapshots (
                id INT AUTO_INCREMENT PRIMARY KEY,
                doc_id VARCHAR(255) NOT NULL,
                snapshot_date VARCHAR(16) NOT NULL,
                source_channel VARCHAR(64) NOT NULL,
                rank_in_period INT,
                raw_score DOUBLE,
                score DOUBLE,
                created_at VARCHAR(64),
                UNIQUE KEY uq_rank_snap (doc_id, snapshot_date, source_channel),
                INDEX idx_snapshots_date_channel (snapshot_date, source_channel)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                phone VARCHAR(20) NULL,
                email VARCHAR(255) NULL,
                email_verified TINYINT(1) NOT NULL DEFAULT 1,
                invite_code_used VARCHAR(64) NULL,
                username VARCHAR(64),
                hashed_password VARCHAR(256) NOT NULL,
                role ENUM('user', 'admin') DEFAULT 'user',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS github_repo_recommendations (
                repo_id VARCHAR(255) NOT NULL PRIMARY KEY,
                active TINYINT(1) NOT NULL DEFAULT 1,
                recommended_by_user_id INT NULL,
                recommended_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_gh_repo_recommendations_active (active, recommended_at),
                INDEX idx_gh_repo_recommendations_user (recommended_by_user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS project_favorites (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                project_source ENUM('github', 'website') NOT NULL,
                project_id VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_project_favorite_user_item (user_id, project_source, project_id),
                INDEX idx_project_favorites_user_created (user_id, created_at DESC),
                INDEX idx_project_favorites_item (project_source, project_id),
                CONSTRAINT fk_project_favorites_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS user_tool_websites (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                website_id BIGINT NOT NULL,
                added_via ENUM('auto', 'manual', 'existing') NOT NULL DEFAULT 'auto',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_user_tool_website (user_id, website_id),
                INDEX idx_user_tool_websites_user_created (user_id, created_at DESC),
                INDEX idx_user_tool_websites_website (website_id),
                CONSTRAINT fk_user_tool_websites_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_user_tool_websites_website FOREIGN KEY (website_id) REFERENCES tool_websites(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS user_tool_website_overrides (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                website_id BIGINT NOT NULL,
                title VARCHAR(512) DEFAULT '',
                description TEXT,
                image_url VARCHAR(1024) DEFAULT '',
                description_zh VARCHAR(512) DEFAULT '',
                category_slug VARCHAR(64) DEFAULT '',
                category_name VARCHAR(128) DEFAULT '',
                subcategory_slug VARCHAR(64) DEFAULT '',
                subcategory_name VARCHAR(128) DEFAULT '',
                tags_json TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_user_tool_website_override (user_id, website_id),
                INDEX idx_user_tool_website_override_user (user_id, updated_at),
                INDEX idx_user_tool_website_override_website (website_id),
                CONSTRAINT fk_user_tool_website_override_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_user_tool_website_override_website FOREIGN KEY (website_id) REFERENCES tool_websites(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                scope ENUM('global', 'paper') NOT NULL DEFAULT 'global',
                scope_key VARCHAR(255) NULL,
                title VARCHAR(255) NULL,
                last_message_preview VARCHAR(500) NULL,
                message_count INT NOT NULL DEFAULT 0,
                last_accessed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_conv_user_updated (user_id, updated_at DESC),
                INDEX idx_conv_user_accessed (user_id, last_accessed_at DESC),
                INDEX idx_conv_scope (user_id, scope, scope_key),
                CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                conversation_id BIGINT NOT NULL,
                role ENUM('user', 'assistant') NOT NULL,
                content MEDIUMTEXT NOT NULL,
                thinking MEDIUMTEXT NULL,
                sources_json JSON NULL,
                attachments_json JSON NULL,
                status ENUM('done', 'streaming', 'deleted', 'regenerated') NOT NULL DEFAULT 'done',
                parent_message_id BIGINT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_msg_conversation_created (conversation_id, created_at ASC),
                INDEX idx_msg_parent (parent_message_id),
                CONSTRAINT fk_chat_messages_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_attachments (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                conversation_id BIGINT NULL,
                file_name VARCHAR(255) NOT NULL,
                mime_type VARCHAR(100) NOT NULL,
                modality ENUM('image', 'pdf') NOT NULL,
                storage_path VARCHAR(512) NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                page_count INT NULL,
                parse_status ENUM('uploaded', 'processing', 'ready', 'failed') NOT NULL DEFAULT 'uploaded',
                extract_text MEDIUMTEXT NULL,
                meta_json JSON NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_attachment_user_created (user_id, created_at DESC),
                INDEX idx_attachment_conv (conversation_id),
                CONSTRAINT fk_chat_attachments_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_chat_attachments_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS runtime_provider_settings (
                provider VARCHAR(64) NOT NULL PRIMARY KEY,
                base_url VARCHAR(1024) DEFAULT '',
                api_key TEXT,
                model_name VARCHAR(255) DEFAULT '',
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS mcp_server_configs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                server_key VARCHAR(64) NOT NULL,
                display_name VARCHAR(128) NOT NULL,
                description TEXT,
                url VARCHAR(1024) NOT NULL,
                transport VARCHAR(32) NOT NULL DEFAULT 'streamable_http',
                auth_type VARCHAR(32) NOT NULL DEFAULT 'none',
                auth_token TEXT,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                last_test_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                last_test_message TEXT,
                last_test_at DATETIME NULL,
                last_tools_json TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_mcp_server_configs_key (server_key),
                INDEX idx_mcp_server_configs_enabled (enabled, updated_at),
                INDEX idx_mcp_server_configs_status (last_test_status, last_test_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS user_mcp_tokens (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                token_hash CHAR(64) NOT NULL,
                token_hint VARCHAR(32) NOT NULL,
                scopes_json TEXT NOT NULL,
                client_type VARCHAR(32) NOT NULL,
                client_label VARCHAR(128) NOT NULL DEFAULT '',
                expires_at DATETIME NULL,
                revoked_at DATETIME NULL,
                deleted_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used_at DATETIME NULL,
                UNIQUE KEY uq_user_mcp_tokens_hash (token_hash),
                INDEX idx_user_mcp_tokens_user_created (user_id, created_at DESC),
                INDEX idx_user_mcp_tokens_active (user_id, revoked_at, deleted_at, expires_at),
                CONSTRAINT fk_user_mcp_tokens_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS briefing_subscriptions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                email VARCHAR(255) NOT NULL,
                source VARCHAR(32) NOT NULL DEFAULT 'all',
                period VARCHAR(16) NOT NULL DEFAULT 'daily',
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_sub_user_source_period (user_id, source, period),
                INDEX idx_sub_active (is_active, source, period),
                CONSTRAINT fk_briefing_sub_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
                # Ensure new tables exist for long-lived databases before best-effort ALTERs.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tool_websites (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        canonical_url VARCHAR(1024) NOT NULL,
                        normalized_url_hash CHAR(64) NOT NULL,
                        domain VARCHAR(255) NOT NULL,
                        title VARCHAR(512) DEFAULT '',
                        description TEXT,
                        image_url VARCHAR(1024) DEFAULT '',
                        raw_metadata_json MEDIUMTEXT,
                        fetch_status VARCHAR(32) NOT NULL DEFAULT 'succeeded',
                        fetch_error TEXT,
                        source_fingerprint CHAR(64) NOT NULL,
                        visibility ENUM('public', 'private') NOT NULL DEFAULT 'public',
                        added_by_user_id INT NULL,
                        first_seen_at VARCHAR(64),
                        last_seen_at VARCHAR(64),
                        updated_at VARCHAR(64),
                        UNIQUE KEY uq_tool_website_url_hash (normalized_url_hash),
                        INDEX idx_tool_website_domain (domain),
                        INDEX idx_tool_website_visibility (visibility, first_seen_at),
                        INDEX idx_tool_website_added_by_user (added_by_user_id),
                        INDEX idx_tool_website_fetch_status (fetch_status, updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tool_website_enrichments (
                        website_id BIGINT NOT NULL PRIMARY KEY,
                        category_slug VARCHAR(64) NOT NULL,
                        category_name VARCHAR(128) NOT NULL,
                        subcategory_slug VARCHAR(64) NOT NULL DEFAULT '',
                        subcategory_name VARCHAR(128) NOT NULL DEFAULT '',
                        description_zh VARCHAR(512) NOT NULL,
                        tags_json TEXT,
                        confidence DOUBLE DEFAULT 0.0,
                        source_fingerprint CHAR(64) NOT NULL,
                        prompt_version VARCHAR(32) NOT NULL,
                        model_provider VARCHAR(64) DEFAULT '',
                        model_name VARCHAR(255) DEFAULT '',
                        status VARCHAR(32) NOT NULL DEFAULT 'succeeded',
                        error_msg TEXT,
                        enriched_at VARCHAR(64),
                        updated_at VARCHAR(64),
                        INDEX idx_tool_website_enrich_category (category_slug, status),
                        INDEX idx_tool_website_enrich_subcategory (subcategory_slug, status),
                        INDEX idx_tool_website_enrich_category_subcategory (category_slug, subcategory_slug, status),
                        INDEX idx_tool_website_enrich_status (status, updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS github_repo_recommendations (
                        repo_id VARCHAR(255) NOT NULL PRIMARY KEY,
                        active TINYINT(1) NOT NULL DEFAULT 1,
                        recommended_by_user_id INT NULL,
                        recommended_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_gh_repo_recommendations_active (active, recommended_at),
                        INDEX idx_gh_repo_recommendations_user (recommended_by_user_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS project_favorites (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        project_source ENUM('github', 'website') NOT NULL,
                        project_id VARCHAR(255) NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_project_favorite_user_item (user_id, project_source, project_id),
                        INDEX idx_project_favorites_user_created (user_id, created_at DESC),
                        INDEX idx_project_favorites_item (project_source, project_id),
                        CONSTRAINT fk_project_favorites_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_tool_websites (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        website_id BIGINT NOT NULL,
                        added_via ENUM('auto', 'manual', 'existing') NOT NULL DEFAULT 'auto',
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_user_tool_website (user_id, website_id),
                        INDEX idx_user_tool_websites_user_created (user_id, created_at DESC),
                        INDEX idx_user_tool_websites_website (website_id),
                        CONSTRAINT fk_user_tool_websites_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        CONSTRAINT fk_user_tool_websites_website FOREIGN KEY (website_id) REFERENCES tool_websites(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                alter_stmts = [
                    "ALTER TABLE documents ADD COLUMN in_daily TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN in_weekly TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN in_monthly TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN stars INT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN forks INT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN language VARCHAR(128) DEFAULT ''",
                    "ALTER TABLE documents ADD COLUMN local_pdf_path VARCHAR(512) DEFAULT NULL",
                    "ALTER TABLE runtime_provider_settings ADD COLUMN model_name VARCHAR(255) DEFAULT ''",
                    "ALTER TABLE mcp_server_configs ADD COLUMN description TEXT AFTER display_name",
                    "ALTER TABLE mcp_server_configs ADD COLUMN transport VARCHAR(32) NOT NULL DEFAULT 'streamable_http' AFTER url",
                    "ALTER TABLE mcp_server_configs ADD COLUMN auth_type VARCHAR(32) NOT NULL DEFAULT 'none' AFTER transport",
                    "ALTER TABLE mcp_server_configs ADD COLUMN auth_token TEXT AFTER auth_type",
                    "ALTER TABLE mcp_server_configs ADD COLUMN enabled TINYINT(1) NOT NULL DEFAULT 1 AFTER auth_token",
                    "ALTER TABLE mcp_server_configs ADD COLUMN last_test_status VARCHAR(32) NOT NULL DEFAULT 'unknown' AFTER enabled",
                    "ALTER TABLE mcp_server_configs ADD COLUMN last_test_message TEXT AFTER last_test_status",
                    "ALTER TABLE mcp_server_configs ADD COLUMN last_test_at DATETIME NULL AFTER last_test_message",
                    "ALTER TABLE mcp_server_configs ADD COLUMN last_tools_json TEXT AFTER last_test_at",
                    "ALTER TABLE mcp_server_configs ADD INDEX idx_mcp_server_configs_enabled (enabled, updated_at)",
                    "ALTER TABLE mcp_server_configs ADD INDEX idx_mcp_server_configs_status (last_test_status, last_test_at)",
                    "ALTER TABLE user_mcp_tokens CHANGE COLUMN token_prefix token_hint VARCHAR(32) NOT NULL",
                    "ALTER TABLE user_mcp_tokens CHANGE COLUMN name client_label VARCHAR(128) NOT NULL DEFAULT ''",
                    "ALTER TABLE user_mcp_tokens ADD COLUMN scopes_json TEXT NOT NULL AFTER token_hint",
                    "ALTER TABLE user_mcp_tokens ADD COLUMN client_type VARCHAR(32) NOT NULL DEFAULT 'other' AFTER scopes_json",
                    "ALTER TABLE user_mcp_tokens ADD COLUMN expires_at DATETIME NULL AFTER client_label",
                    "ALTER TABLE user_mcp_tokens ADD COLUMN revoked_at DATETIME NULL AFTER expires_at",
                    "ALTER TABLE user_mcp_tokens ADD COLUMN deleted_at DATETIME NULL AFTER revoked_at",
                    "ALTER TABLE user_mcp_tokens ADD INDEX idx_user_mcp_tokens_active (user_id, revoked_at, deleted_at, expires_at)",
                    # Phase 4: 认证鉴权改造 — users 表邮箱字段迁移
                    "ALTER TABLE users MODIFY phone VARCHAR(20) NULL",
                    "ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL UNIQUE AFTER phone",
                    "ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 1 AFTER email",
                    "ALTER TABLE users ADD COLUMN invite_code_used VARCHAR(64) NULL AFTER email_verified",
                    "ALTER TABLE github_repo_candidates ADD UNIQUE KEY uq_gh_repo_full_name (full_name)",
                    "ALTER TABLE github_repo_candidates ADD INDEX idx_gh_candidates_stars (stars, forks, full_name)",
                    "ALTER TABLE github_repo_candidates ADD INDEX idx_gh_candidates_pushed (pushed_at, stars)",
                    "ALTER TABLE github_repo_candidates ADD INDEX idx_gh_candidates_first_seen (first_seen_at, stars)",
                    "ALTER TABLE github_repo_candidates ADD INDEX idx_gh_candidates_language (language, stars)",
                    "ALTER TABLE github_repo_snapshots ADD INDEX idx_gh_snapshots_date_repo (snapshot_date, repo_id)",
                    "ALTER TABLE github_repo_snapshots ADD COLUMN community_metrics_complete TINYINT(1) NULL DEFAULT NULL AFTER watchers",
                    "ALTER TABLE github_repo_daily_metrics ADD COLUMN daily_fork_growth INT DEFAULT 0 AFTER daily_star_growth",
                    "ALTER TABLE github_repo_daily_metrics ADD COLUMN daily_watcher_growth INT DEFAULT 0 AFTER daily_fork_growth",
                    "ALTER TABLE github_repo_daily_metrics ADD COLUMN daily_growth_source VARCHAR(32) NOT NULL DEFAULT 'unavailable' AFTER daily_growth_available",
                    "ALTER TABLE github_repo_daily_metrics ADD COLUMN daily_growth_observed_at VARCHAR(64) NULL AFTER daily_growth_source",
                    "ALTER TABLE github_repo_daily_metrics MODIFY score_version VARCHAR(32) NOT NULL DEFAULT 'daily_hot_v4'",
                    "ALTER TABLE github_trending_hits ADD COLUMN period_star_growth INT NULL AFTER captured_at",
                    "ALTER TABLE github_trending_hits ADD COLUMN period_growth_observed_at VARCHAR(64) NULL AFTER period_star_growth",
                    "ALTER TABLE github_repo_daily_metrics ADD INDEX idx_gh_daily_metrics_date_hot (metric_date, hot_score)",
                    "ALTER TABLE github_repo_daily_metrics ADD INDEX idx_gh_daily_metrics_date_growth (metric_date, daily_star_growth)",
                    "ALTER TABLE github_repo_enrichments ADD INDEX idx_gh_enrich_repo_status_category (repo_id, status, category_slug)",
                    "ALTER TABLE github_repo_enrichments ADD COLUMN subcategory_slug VARCHAR(64) NOT NULL DEFAULT '' AFTER category_name",
                    "ALTER TABLE github_repo_enrichments ADD COLUMN subcategory_name VARCHAR(128) NOT NULL DEFAULT '' AFTER subcategory_slug",
                    "ALTER TABLE github_repo_enrichments ADD INDEX idx_gh_repo_enrich_subcategory (subcategory_slug, status)",
                    "ALTER TABLE github_repo_enrichments ADD INDEX idx_gh_repo_enrich_category_subcategory (category_slug, subcategory_slug, status)",
                    "ALTER TABLE tool_websites ADD COLUMN visibility ENUM('public', 'private') NOT NULL DEFAULT 'public' AFTER source_fingerprint",
                    "ALTER TABLE tool_websites ADD COLUMN added_by_user_id INT NULL AFTER visibility",
                    "ALTER TABLE tool_websites ADD INDEX idx_tool_website_visibility (visibility, first_seen_at)",
                    "ALTER TABLE tool_websites ADD INDEX idx_tool_website_added_by_user (added_by_user_id)",
                    "ALTER TABLE tool_website_enrichments ADD COLUMN subcategory_slug VARCHAR(64) NOT NULL DEFAULT '' AFTER category_name",
                    "ALTER TABLE tool_website_enrichments ADD COLUMN subcategory_name VARCHAR(128) NOT NULL DEFAULT '' AFTER subcategory_slug",
                    "ALTER TABLE tool_website_enrichments ADD INDEX idx_tool_website_enrich_subcategory (subcategory_slug, status)",
                    "ALTER TABLE tool_website_enrichments ADD INDEX idx_tool_website_enrich_category_subcategory (category_slug, subcategory_slug, status)",
                ]
                for stmt in alter_stmts:
                    try:
                        cur.execute(stmt)
                    except pymysql.err.OperationalError as exc:
                        code = exc.args[0] if exc.args else None
                        legacy_token_rename = stmt in {
                            "ALTER TABLE user_mcp_tokens CHANGE COLUMN token_prefix token_hint VARCHAR(32) NOT NULL",
                            "ALTER TABLE user_mcp_tokens CHANGE COLUMN name client_label VARCHAR(128) NOT NULL DEFAULT ''",
                        }
                        if code in {1060, 1061, 1068, 1091} or (code == 1054 and legacy_token_rename):
                            continue
                        logger.exception("[MySQLRepository] schema migration failed: %s", stmt)
                        raise
                    except pymysql.err.InternalError as exc:
                        code = exc.args[0] if exc.args else None
                        legacy_token_rename = stmt in {
                            "ALTER TABLE user_mcp_tokens CHANGE COLUMN token_prefix token_hint VARCHAR(32) NOT NULL",
                            "ALTER TABLE user_mcp_tokens CHANGE COLUMN name client_label VARCHAR(128) NOT NULL DEFAULT ''",
                        }
                        if code in {1060, 1061, 1068, 1091} or (code == 1054 and legacy_token_rename):
                            continue
                        logger.exception("[MySQLRepository] schema migration failed: %s", stmt)
                        raise
                cur.execute(
                    """
                    UPDATE github_repo_daily_metrics
                    SET daily_growth_source = 'snapshot_delta'
                    WHERE daily_growth_available = 1
                      AND COALESCE(daily_growth_source, 'unavailable') = 'unavailable'
                      AND previous_snapshot_date = DATE_FORMAT(
                          DATE_SUB(STR_TO_DATE(metric_date, '%Y-%m-%d'), INTERVAL 1 DAY),
                          '%Y-%m-%d'
                      )
                    """
                )
                # Legacy rows may predate scopes_json or contain its old empty default.
                # Backfill only missing/empty scopes so reruns are safe and explicit scopes survive.
                cur.execute(
                    """
                    UPDATE user_mcp_tokens
                    SET scopes_json = '["projects:favorites:read"]'
                    WHERE scopes_json IS NULL
                       OR TRIM(scopes_json) = ''
                       OR TRIM(scopes_json) = '[]'
                    """
                )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def upsert_document(self, doc: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO documents (id, source, source_channel, title, url, summary, published_date,
                                   tags, score, raw_score, stars, forks, language, rank_in_period, indexed,
                                   in_daily, in_weekly, in_monthly, local_pdf_path, created_at)
            VALUES (%(id)s, %(source)s, %(source_channel)s, %(title)s, %(url)s, %(summary)s, %(published_date)s,
                    %(tags)s, %(score)s, %(raw_score)s, %(stars)s, %(forks)s, %(language)s, %(rank_in_period)s, %(indexed)s,
                    %(in_daily)s, %(in_weekly)s, %(in_monthly)s, %(local_pdf_path)s, %(created_at)s)
            ON DUPLICATE KEY UPDATE
                source_channel=VALUES(source_channel),
                title=VALUES(title),
                url=VALUES(url),
                summary=VALUES(summary),
                published_date=COALESCE(NULLIF(VALUES(published_date), ''), published_date),
                tags=VALUES(tags),
                score=GREATEST(score, VALUES(score)),
                raw_score=GREATEST(raw_score, VALUES(raw_score)),
                stars=COALESCE(NULLIF(VALUES(stars), 0), stars),
                forks=COALESCE(NULLIF(VALUES(forks), 0), forks),
                language=COALESCE(NULLIF(VALUES(language), ''), language),
                rank_in_period=LEAST(rank_in_period, VALUES(rank_in_period)),
                indexed=VALUES(indexed),
                in_daily=GREATEST(in_daily, VALUES(in_daily)),
                in_weekly=GREATEST(in_weekly, VALUES(in_weekly)),
                in_monthly=GREATEST(in_monthly, VALUES(in_monthly)),
                local_pdf_path=COALESCE(VALUES(local_pdf_path), local_pdf_path)
        """
        doc.setdefault("created_at", _utcnow())
        doc.setdefault("indexed", 0)
        doc.setdefault("in_daily", 0)
        doc.setdefault("in_weekly", 0)
        doc.setdefault("in_monthly", 0)
        doc.setdefault("score", 0.0)
        doc.setdefault("raw_score", doc.get("score", 0.0))
        doc.setdefault("stars", 0)
        doc.setdefault("forks", 0)
        doc.setdefault("language", "")
        doc.setdefault("source_channel", "")
        doc.setdefault("rank_in_period", 9999)
        doc.setdefault("local_pdf_path", None)
        if isinstance(doc.get("tags"), list):
            doc["tags"] = json.dumps(doc["tags"], ensure_ascii=False)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, doc)
            conn.commit()
        finally:
            conn.close()

    def update_document_pdf_path(self, doc_id: str, local_pdf_path: str) -> None:
        sql = "UPDATE documents SET local_pdf_path = %s WHERE id = %s"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (local_pdf_path, doc_id))
            conn.commit()
        finally:
            conn.close()

    def search_document_page(
        self,
        query: str,
        *,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        candidates = _document_search_candidates(query)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        if not candidates:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        patterns = [f"%{_escape_like_literal(candidate)}%" for candidate in candidates]
        field_match = (
            "(COALESCE(title, '') LIKE %s ESCAPE '=' "
            "OR COALESCE(summary, '') LIKE %s ESCAPE '=' "
            "OR COALESCE(tags, '') LIKE %s ESCAPE '=')"
        )
        search_sql = "(" + " OR ".join([field_match] * len(patterns)) + ")"
        where_parts = [search_sql]
        where_params: List[Any] = [pattern for pattern in patterns for _ in range(3)]
        clean_source = str(source or "").strip().lower()
        if clean_source:
            where_parts.append("source = %s")
            where_params.append(clean_source)
        where_sql = " AND ".join(where_parts)

        tier_clauses: List[str] = []
        tier_params: List[Any] = []
        for index, pattern in enumerate(patterns):
            tier_clauses.append(f"WHEN COALESCE(title, '') LIKE %s ESCAPE '=' THEN {index * 2}")
            tier_params.append(pattern)
            tier_clauses.append(
                f"WHEN (COALESCE(summary, '') LIKE %s ESCAPE '=' "
                f"OR COALESCE(tags, '') LIKE %s ESCAPE '=') THEN {index * 2 + 1}"
            )
            tier_params.extend([pattern, pattern])

        count_clauses = [f"CASE WHEN {field_match} THEN 1 ELSE 0 END" for _ in patterns]
        count_params = [pattern for pattern in patterns for _ in range(3)]
        count_sql = f"SELECT COUNT(*) AS cnt FROM documents WHERE {where_sql}"
        rows_sql = f"""
            SELECT id, source, source_channel, title, url, summary,
                   published_date, tags, score, raw_score, rank_in_period,
                   local_pdf_path, created_at
            FROM documents
            WHERE {where_sql}
            ORDER BY
                CASE {' '.join(tier_clauses)} ELSE {len(patterns) * 2} END ASC,
                ({' + '.join(count_clauses)}) DESC,
                COALESCE(raw_score, score, 0) DESC,
                created_at DESC,
                id ASC
            LIMIT %s OFFSET %s
        """
        offset = (page - 1) * page_size
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(count_sql, tuple(where_params))
                total_row = cur.fetchone()
                total = int(total_row["cnt"] if total_row else 0)
                cur.execute(
                    rows_sql,
                    tuple(where_params + tier_params + count_params + [page_size, offset]),
                )
                items = [dict(row) for row in cur.fetchall()]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()

    def search_documents(
        self,
        query: str,
        limit: int = 20,
        *,
        source: str | None = None,
    ) -> List[Dict[str, Any]]:
        return self.search_document_page(
            query,
            source=source,
            page=1,
            page_size=max(1, min(int(limit), 100)),
        )["items"]

    def get_existing_document_summaries(
        self,
        *,
        ids: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        titles: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        ids = [_normalize_doc_lookup_key(item) for item in (ids or [])]
        urls = [_normalize_doc_lookup_key(item) for item in (urls or [])]
        titles = [_normalize_doc_lookup_key(item) for item in (titles or [])]
        ids = [item for item in ids if item]
        urls = [item for item in urls if item]
        titles = [item for item in titles if item]

        conditions: List[str] = []
        params: List[Any] = []

        if ids:
            placeholders = ", ".join(["%s"] * len(ids))
            conditions.append(f"id IN ({placeholders})")
            params.extend(ids)
        if urls:
            placeholders = ", ".join(["%s"] * len(urls))
            conditions.append(f"url IN ({placeholders})")
            params.extend(urls)
        if titles:
            placeholders = ", ".join(["%s"] * len(titles))
            conditions.append(f"title IN ({placeholders})")
            params.extend(titles)

        if not conditions:
            return {}

        sql = f"""
            SELECT id, url, title, summary
            FROM documents
            WHERE ({' OR '.join(conditions)})
              AND COALESCE(NULLIF(TRIM(summary), ''), '') != ''
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
        finally:
            conn.close()

        result: Dict[str, str] = {}
        for row in rows:
            summary = (row.get("summary") or "").strip()
            if not summary:
                continue
            doc_id = _normalize_doc_lookup_key(row.get("id"))
            url = _normalize_doc_lookup_key(row.get("url"))
            title = _normalize_doc_lookup_key(row.get("title"))
            if doc_id:
                result[f"id:{doc_id}"] = summary
            if url:
                result[f"url:{url}"] = summary
            if title:
                result[f"title:{title}"] = summary
        return result

    def get_top_documents(
        self, limit: int = 10, source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        select_clause = """
            SELECT
                d.id, d.source, d.source_channel, d.title, d.url, d.summary,
                d.published_date, d.tags, d.score, d.raw_score,
                COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
                COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
                COALESCE(NULLIF(d.language, ''), c.language, '') AS language,
                d.rank_in_period, d.indexed, d.in_daily, d.in_weekly,
                d.in_monthly, d.local_pdf_path, d.created_at
            FROM documents d
            LEFT JOIN github_repo_candidates c
              ON d.source = 'github'
             AND (c.full_name = d.title OR c.url = d.url)
            LEFT JOIN (
                SELECT s.repo_id, s.stars, s.forks
                FROM github_repo_snapshots s
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) latest
                  ON latest.repo_id = s.repo_id
                 AND latest.snapshot_date = s.snapshot_date
            ) gs ON gs.repo_id = c.repo_id
        """
        order_by = """
            ORDER BY
                COALESCE(d.raw_score, d.score, 0) DESC,
                d.published_date DESC
        """

        if source_type and source_type != "all":
            sql = f"""
                {select_clause}
                WHERE d.source = %s
                {order_by}
                LIMIT %s
            """
            params: tuple = (source_type, limit)
        else:
            sql = f"""
                {select_clause}
                {order_by}
                LIMIT %s
            """
            params = (limit,)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def get_latest_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        sql = """
            SELECT
                d.id, d.source, d.source_channel, d.title, d.url, d.summary,
                d.published_date, d.tags, d.score, d.raw_score,
                COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
                COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
                COALESCE(NULLIF(d.language, ''), c.language, '') AS language,
                d.rank_in_period, d.indexed, d.in_daily, d.in_weekly,
                d.in_monthly, d.local_pdf_path, d.created_at
            FROM documents d
            LEFT JOIN github_repo_candidates c
              ON d.source = 'github'
             AND (c.full_name = d.title OR c.url = d.url)
            LEFT JOIN (
                SELECT s.repo_id, s.stars, s.forks
                FROM github_repo_snapshots s
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) latest
                  ON latest.repo_id = s.repo_id
                 AND latest.snapshot_date = s.snapshot_date
            ) gs ON gs.repo_id = c.repo_id
            ORDER BY d.created_at DESC
            LIMIT %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def get_document_count(self) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM documents")
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)
        finally:
            conn.close()

    def get_source_counts(self) -> Dict[str, int]:
        sql = """
            SELECT source, COUNT(DISTINCT COALESCE(NULLIF(url, ''), title)) AS cnt
            FROM documents
            GROUP BY source
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
            conn.commit()
            return {row["source"]: row["cnt"] for row in rows}
        finally:
            conn.close()

    def get_user_count(self) -> int:
        """返回已注册用户总数。"""
        return self.user_accounts.get_user_count()

    def get_today_registered_user_count(self) -> int:
        """返回今日注册用户数（CST）。"""
        return self.user_accounts.get_today_registered_user_count()

    def get_today_document_count(self) -> int:
        """返回今日新增文档数（created_at 日期 = CST 今天）。

        documents.created_at 以 UTC ISO 字符串存储，查询时取前 10 字符与 CST 今天对比。
        """
        from datetime import datetime, timezone, timedelta

        tz_cst = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_cst).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM documents WHERE LEFT(created_at, 10) = %s",
                    (today_str,),
                )
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)
        finally:
            conn.close()

    def count_user_messages_today(self, user_id: int) -> int:
        """统计指定用户今日（CST）发送的消息数（role='user'）。

        通过 JOIN conversations 表过滤 user_id，
        chat_messages.created_at 为 DATETIME 类型，使用 CONVERT_TZ 转换到 CST 后取日期对比。
        """
        from datetime import datetime, timezone, timedelta

        tz_cst = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_cst).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM chat_messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = %s
                      AND m.role = 'user'
                      AND DATE(CONVERT_TZ(m.created_at, '+00:00', '+08:00')) = %s
                    """,
                    (user_id, today_str),
                )
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)
        finally:
            conn.close()

    def clear_all_documents(self) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM documents")
                row = cur.fetchone()
                count = int(row["cnt"] if row else 0)
                cur.execute("DELETE FROM documents")
            conn.commit()
            return count
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Document rank snapshots
    # ------------------------------------------------------------------

    def upsert_rank_snapshot(
        self,
        doc_id: str,
        snapshot_date: str,
        source_channel: str,
        rank_in_period: int,
        raw_score: float,
        score: float,
    ) -> None:
        sql = """
            INSERT INTO document_rank_snapshots
                (doc_id, snapshot_date, source_channel, rank_in_period, raw_score, score, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rank_in_period=LEAST(rank_in_period, VALUES(rank_in_period)),
                raw_score=GREATEST(raw_score, VALUES(raw_score)),
                score=GREATEST(score, VALUES(score))
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        doc_id,
                        snapshot_date,
                        source_channel,
                        rank_in_period,
                        raw_score,
                        score,
                        _utcnow(),
                    ),
                )
            sync_sql = """
                UPDATE document_rank_snapshots s
                JOIN (
                    SELECT doc_id, snapshot_date,
                           MAX(raw_score) AS max_raw, MAX(score) AS max_score
                    FROM document_rank_snapshots
                    WHERE doc_id = %s AND snapshot_date = %s
                    GROUP BY doc_id, snapshot_date
                ) agg ON s.doc_id = agg.doc_id AND s.snapshot_date = agg.snapshot_date
                SET s.raw_score = agg.max_raw, s.score = agg.max_score
                WHERE s.doc_id = %s AND s.snapshot_date = %s
                  AND (s.raw_score < agg.max_raw OR s.score < agg.max_score)
            """
            with conn.cursor() as cur:
                cur.execute(sync_sql, (doc_id, snapshot_date, doc_id, snapshot_date))
            conn.commit()
        finally:
            conn.close()

    def get_snapshot_documents(
        self,
        snapshot_date: str,
        source_channel: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        conditions = ["s.snapshot_date = %s"]
        params: List[Any] = [snapshot_date]

        if source_channel:
            conditions.append("s.source_channel = %s")
            params.append(source_channel)

        if source_type and source_type != "all":
            conditions.append("d.source = %s")
            params.append(source_type)

        params.append(limit)
        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                d.id, d.source, d.title, d.url, d.summary, d.published_date,
                d.tags, d.indexed, d.created_at,
                COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
                COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
                COALESCE(NULLIF(d.language, ''), c.language, '') AS language,
                d.in_daily, d.in_weekly, d.in_monthly,
                s.source_channel,
                s.rank_in_period,
                s.raw_score,
                s.score,
                s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            LEFT JOIN github_repo_candidates c
              ON d.source = 'github'
             AND (c.full_name = d.title OR c.url = d.url)
            LEFT JOIN (
                SELECT snap.repo_id, snap.stars, snap.forks
                FROM github_repo_snapshots snap
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) latest
                  ON latest.repo_id = snap.repo_id
                 AND latest.snapshot_date = snap.snapshot_date
            ) gs ON gs.repo_id = c.repo_id
            WHERE {where_clause}
            ORDER BY
                CASE WHEN d.source = 'github' THEN s.rank_in_period ELSE 9999 END ASC,
                CASE WHEN d.source != 'github' THEN -s.raw_score ELSE 0 END ASC,
                s.rank_in_period ASC
            LIMIT %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def get_snapshot_dates(
        self,
        limit: int = 60,
        source: Optional[str] = None,
        period: Optional[str] = None,
    ) -> List[str]:
        conditions: List[str] = []
        params: List[Any] = []

        if source:
            conditions.append("d.source = %s")
            params.append(source)

        if period:
            if source:
                channels = SNAPSHOT_PERIOD_CHANNELS.get(source, {}).get(period, ())
            else:
                channels = tuple(
                    channel
                    for period_map in SNAPSHOT_PERIOD_CHANNELS.values()
                    for channel in period_map.get(period, ())
                )
            if not channels:
                return []
            placeholders = ", ".join(["%s"] * len(channels))
            conditions.append(f"s.source_channel IN ({placeholders})")
            params.extend(channels)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT DISTINCT s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            {where_clause}
            ORDER BY s.snapshot_date DESC
            LIMIT %s
        """
        params.append(limit)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
            return [row["snapshot_date"] for row in rows]
        finally:
            conn.close()

    def get_snapshot_source_counts(self, snapshot_date: str) -> Dict[str, int]:
        sql = """
            SELECT d.source, COUNT(DISTINCT s.doc_id) AS cnt
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            WHERE s.snapshot_date = %s
            GROUP BY d.source
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (snapshot_date,))
                rows = cur.fetchall()
            conn.commit()
            return {row["source"]: row["cnt"] for row in rows}
        finally:
            conn.close()

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: Optional[str] = None,
    ) -> Set[str]:
        conditions = ["s.snapshot_date = %s"]
        params: List[Any] = [snapshot_date]

        if source_channel:
            conditions.append("s.source_channel = %s")
            params.append(source_channel)

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT DISTINCT s.doc_id
            FROM document_rank_snapshots s
            WHERE {where_clause}
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
            return {row["doc_id"] for row in rows}
        finally:
            conn.close()

    def delete_snapshots_by_channel(
        self, snapshot_date: str, source_channel: str
    ) -> int:
        sql = """
            DELETE FROM document_rank_snapshots
            WHERE snapshot_date = %s AND source_channel = %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (snapshot_date, source_channel))
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # GitHub hotness
    # ------------------------------------------------------------------

    def upsert_github_repo_candidate(self, repo: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO github_repo_candidates (
                repo_id, full_name, title, url, description, language,
                topics_json, created_at, pushed_at, stars, forks, watchers,
                source_channels, first_seen_at, last_seen_at, last_snapshot_at
            ) VALUES (
                %(repo_id)s, %(full_name)s, %(title)s, %(url)s, %(description)s, %(language)s,
                %(topics_json)s, %(created_at)s, %(pushed_at)s, %(stars)s, %(forks)s, %(watchers)s,
                %(source_channels)s, %(first_seen_at)s, %(last_seen_at)s, %(last_snapshot_at)s
            )
            ON DUPLICATE KEY UPDATE
                title=COALESCE(NULLIF(VALUES(title), ''), title),
                url=COALESCE(NULLIF(VALUES(url), ''), url),
                description=COALESCE(NULLIF(VALUES(description), ''), description),
                language=COALESCE(NULLIF(VALUES(language), ''), language),
                topics_json=COALESCE(NULLIF(VALUES(topics_json), '[]'), topics_json),
                created_at=COALESCE(NULLIF(created_at, ''), VALUES(created_at)),
                pushed_at=GREATEST(COALESCE(pushed_at, ''), COALESCE(VALUES(pushed_at), '')),
                stars=GREATEST(COALESCE(stars, 0), COALESCE(VALUES(stars), 0)),
                forks=GREATEST(COALESCE(forks, 0), COALESCE(VALUES(forks), 0)),
                watchers=GREATEST(COALESCE(watchers, 0), COALESCE(VALUES(watchers), 0)),
                source_channels=VALUES(source_channels),
                first_seen_at=LEAST(COALESCE(NULLIF(first_seen_at, ''), VALUES(first_seen_at)), VALUES(first_seen_at)),
                last_seen_at=GREATEST(COALESCE(last_seen_at, ''), COALESCE(VALUES(last_seen_at), '')),
                last_snapshot_at=GREATEST(COALESCE(last_snapshot_at, ''), COALESCE(VALUES(last_snapshot_at), ''))
        """
        payload = dict(repo)
        payload["full_name"] = str(payload.get("full_name") or payload.get("title") or payload.get("repo_id") or "").strip()
        payload["repo_id"] = str(payload.get("repo_id") or payload["full_name"]).strip()
        payload.setdefault("title", payload.get("full_name", ""))
        payload.setdefault("description", "")
        payload.setdefault("language", "")
        payload.setdefault("topics_json", "[]")
        payload.setdefault("created_at", "")
        payload.setdefault("pushed_at", "")
        payload.setdefault("stars", 0)
        payload.setdefault("forks", 0)
        payload.setdefault("watchers", 0)
        payload.setdefault("source_channels", "")
        now = _utcnow()
        payload.setdefault("first_seen_at", now)
        payload.setdefault("last_seen_at", now)
        payload.setdefault("last_snapshot_at", now)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                requested_repo_id = payload["repo_id"]
                canonical_repo_id = self._resolve_github_repo_id_cur(
                    cur,
                    requested_repo_id,
                    payload["full_name"],
                )
                self._upsert_github_repo_alias_cur(
                    cur,
                    alias_repo_id=requested_repo_id,
                    canonical_repo_id=canonical_repo_id,
                    full_name=payload["full_name"],
                )
                payload["repo_id"] = canonical_repo_id
                cur.execute(sql, payload)
            conn.commit()
        finally:
            conn.close()

    def ensure_github_repo_candidate(self, repo: Dict[str, Any]) -> str:
        """Create a minimal candidate without overwriting an existing project row."""
        sql = """
            INSERT IGNORE INTO github_repo_candidates (
                repo_id, full_name, title, url, description, language,
                topics_json, created_at, pushed_at, stars, forks, watchers,
                source_channels, first_seen_at, last_seen_at, last_snapshot_at
            ) VALUES (
                %(repo_id)s, %(full_name)s, %(title)s, %(url)s, %(description)s, %(language)s,
                %(topics_json)s, %(created_at)s, %(pushed_at)s, %(stars)s, %(forks)s, %(watchers)s,
                %(source_channels)s, %(first_seen_at)s, %(last_seen_at)s, %(last_snapshot_at)s
            )
        """
        payload = dict(repo)
        payload["full_name"] = str(
            payload.get("full_name") or payload.get("title") or payload.get("repo_id") or ""
        ).strip()
        payload["repo_id"] = str(payload.get("repo_id") or payload["full_name"]).strip()
        payload.setdefault("title", payload["full_name"])
        payload.setdefault("url", f"https://github.com/{payload['full_name']}" if payload["full_name"] else "")
        payload.setdefault("description", "")
        payload.setdefault("language", "")
        payload.setdefault("topics_json", "[]")
        payload.setdefault("created_at", "")
        payload.setdefault("pushed_at", "")
        payload.setdefault("stars", 0)
        payload.setdefault("forks", 0)
        payload.setdefault("watchers", 0)
        payload.setdefault("source_channels", "trending_daily")
        now = _utcnow()
        payload.setdefault("first_seen_at", now)
        payload.setdefault("last_seen_at", now)
        payload.setdefault("last_snapshot_at", now)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                requested_repo_id = payload["repo_id"]
                canonical_repo_id = self._resolve_github_repo_id_cur(
                    cur,
                    requested_repo_id,
                    payload["full_name"],
                )
                self._upsert_github_repo_alias_cur(
                    cur,
                    alias_repo_id=requested_repo_id,
                    canonical_repo_id=canonical_repo_id,
                    full_name=payload["full_name"],
                )
                payload["repo_id"] = canonical_repo_id
                cur.execute(sql, payload)
            conn.commit()
            return canonical_repo_id
        finally:
            conn.close()

    def insert_github_repo_snapshot(self, snapshot: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO github_repo_snapshots (
                repo_id, snapshot_date, captured_at, stars, forks, watchers,
                community_metrics_complete, open_issues, repo_created_at, repo_pushed_at
            ) VALUES (
                %(repo_id)s, %(snapshot_date)s, %(captured_at)s, %(stars)s, %(forks)s, %(watchers)s,
                %(community_metrics_complete)s, %(open_issues)s, %(repo_created_at)s, %(repo_pushed_at)s
            )
            ON DUPLICATE KEY UPDATE
                captured_at=GREATEST(COALESCE(captured_at, ''), COALESCE(VALUES(captured_at), '')),
                stars=GREATEST(COALESCE(stars, 0), COALESCE(VALUES(stars), 0)),
                forks=CASE
                    WHEN VALUES(community_metrics_complete) = 1
                     AND COALESCE(community_metrics_complete, 0) <> 1
                    THEN VALUES(forks)
                    WHEN VALUES(community_metrics_complete) = 1
                     AND community_metrics_complete = 1
                    THEN GREATEST(COALESCE(forks, 0), COALESCE(VALUES(forks), 0))
                    WHEN community_metrics_complete = 1
                    THEN forks
                    ELSE GREATEST(COALESCE(forks, 0), COALESCE(VALUES(forks), 0))
                END,
                watchers=CASE
                    WHEN VALUES(community_metrics_complete) = 1
                     AND COALESCE(community_metrics_complete, 0) <> 1
                    THEN VALUES(watchers)
                    WHEN VALUES(community_metrics_complete) = 1
                     AND community_metrics_complete = 1
                    THEN GREATEST(COALESCE(watchers, 0), COALESCE(VALUES(watchers), 0))
                    WHEN community_metrics_complete = 1
                    THEN watchers
                    ELSE GREATEST(COALESCE(watchers, 0), COALESCE(VALUES(watchers), 0))
                END,
                community_metrics_complete=CASE
                    WHEN community_metrics_complete = 1
                      OR VALUES(community_metrics_complete) = 1
                    THEN 1
                    WHEN community_metrics_complete = 0
                      OR VALUES(community_metrics_complete) = 0
                    THEN 0
                    ELSE NULL
                END,
                open_issues=GREATEST(COALESCE(open_issues, 0), COALESCE(VALUES(open_issues), 0)),
                repo_created_at=COALESCE(NULLIF(repo_created_at, ''), VALUES(repo_created_at)),
                repo_pushed_at=GREATEST(COALESCE(repo_pushed_at, ''), COALESCE(VALUES(repo_pushed_at), ''))
        """
        payload = dict(snapshot)
        payload.setdefault("captured_at", _utcnow())
        payload.setdefault("stars", 0)
        payload.setdefault("forks", 0)
        payload.setdefault("watchers", 0)
        completeness = payload.get("community_metrics_complete")
        payload["community_metrics_complete"] = (
            None if completeness is None else (1 if completeness else 0)
        )
        payload.setdefault("open_issues", 0)
        payload.setdefault("repo_created_at", "")
        payload.setdefault("repo_pushed_at", "")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                payload["repo_id"] = self._resolve_github_repo_id_cur(
                    cur,
                    str(payload.get("repo_id") or ""),
                    str(payload.get("full_name") or ""),
                )
                cur.execute(sql, payload)
            conn.commit()
        finally:
            conn.close()

    def upsert_github_trending_hit(self, hit: Dict[str, Any]) -> str:
        sql = """
            INSERT INTO github_trending_hits (
                repo_id, full_name, period, language, `rank`, observed_date, captured_at,
                period_star_growth, period_growth_observed_at
            ) VALUES (
                %(repo_id)s, %(full_name)s, %(period)s, %(language)s, %(rank)s, %(observed_date)s, %(captured_at)s,
                %(period_star_growth)s, %(period_growth_observed_at)s
            )
            ON DUPLICATE KEY UPDATE
                full_name=VALUES(full_name),
                language=COALESCE(NULLIF(VALUES(language), ''), language),
                `rank`=LEAST(COALESCE(`rank`, VALUES(`rank`)), VALUES(`rank`)),
                period_star_growth=CASE
                    WHEN VALUES(period_star_growth) IS NOT NULL
                     AND (
                         period_growth_observed_at IS NULL
                         OR VALUES(period_growth_observed_at) >= period_growth_observed_at
                     )
                    THEN VALUES(period_star_growth)
                    ELSE period_star_growth
                END,
                period_growth_observed_at=CASE
                    WHEN VALUES(period_star_growth) IS NOT NULL
                     AND (
                         period_growth_observed_at IS NULL
                         OR VALUES(period_growth_observed_at) >= period_growth_observed_at
                     )
                    THEN VALUES(period_growth_observed_at)
                    ELSE period_growth_observed_at
                END,
                captured_at=GREATEST(COALESCE(captured_at, ''), COALESCE(VALUES(captured_at), ''))
        """
        payload = dict(hit)
        payload.setdefault("full_name", "")
        payload.setdefault("language", "")
        payload.setdefault("rank", 999)
        payload.setdefault("captured_at", _utcnow())
        growth = payload.get("period_star_growth")
        payload["period_star_growth"] = int(growth) if growth is not None else None
        payload["period_growth_observed_at"] = (
            payload.get("period_growth_observed_at") or payload["captured_at"]
            if payload["period_star_growth"] is not None
            else None
        )
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                payload["repo_id"] = self._resolve_github_repo_id_cur(
                    cur,
                    str(payload.get("repo_id") or ""),
                    str(payload.get("full_name") or ""),
                )
                cur.execute(sql, payload)
            conn.commit()
            return str(payload["repo_id"])
        finally:
            conn.close()

    def get_github_hot_repos(
        self, period: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        window_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 1)
        decay_exp = {"daily": 0.5, "weekly": 0.25, "monthly": 0.12}.get(period, 0.5)
        sql = f"""
            WITH latest AS (
                SELECT s.*
                FROM github_repo_snapshots s
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) t
                  ON s.repo_id = t.repo_id AND s.snapshot_date = t.snapshot_date
            ),
            latest_with_prev AS (
                SELECT
                    l.repo_id,
                    l.snapshot_date,
                    l.captured_at,
                    l.stars,
                    l.forks,
                    l.watchers,
                    l.open_issues,
                    l.repo_created_at,
                    l.repo_pushed_at,
                    (
                        SELECT s2.stars
                        FROM github_repo_snapshots s2
                        WHERE s2.repo_id = l.repo_id
                          AND s2.snapshot_date <= DATE_SUB(l.snapshot_date, INTERVAL {window_days} DAY)
                        ORDER BY s2.snapshot_date DESC
                        LIMIT 1
                    ) AS stars_prev_window,
                    (
                        SELECT AVG(delta_stars)
                        FROM (
                            SELECT GREATEST(s_new.stars - s_old.stars, 0) AS delta_stars
                            FROM github_repo_snapshots s_new
                            JOIN github_repo_snapshots s_old
                              ON s_new.repo_id = s_old.repo_id
                             AND s_old.snapshot_date = DATE_SUB(s_new.snapshot_date, INTERVAL 1 DAY)
                            WHERE s_new.repo_id = l.repo_id
                              AND s_new.snapshot_date >= DATE_SUB(l.snapshot_date, INTERVAL 14 DAY)
                        ) baseline
                    ) AS baseline_daily,
                    (
                        SELECT MIN(`rank`)
                        FROM github_trending_hits th
                        WHERE th.repo_id = l.repo_id
                          AND th.period = %s
                          AND th.observed_date >= DATE_SUB(l.snapshot_date, INTERVAL {window_days} DAY)
                    ) AS best_trending_rank
                FROM latest l
            )
            SELECT
                c.repo_id,
                c.full_name,
                c.title,
                c.url,
                c.description,
                c.language,
                c.topics_json,
                c.created_at,
                c.pushed_at,
                l.snapshot_date,
                l.captured_at,
                l.stars,
                l.forks,
                l.watchers,
                l.open_issues,
                COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) AS growth,
                COALESCE(l.baseline_daily, 0.0) AS baseline_daily,
                COALESCE(l.best_trending_rank, 999) AS trending_rank,
                CAST(DATEDIFF(l.snapshot_date, LEFT(c.created_at, 10)) AS DOUBLE) AS repo_age_days,
                CASE
                    WHEN l.best_trending_rank IS NULL THEN 0.0
                    ELSE 1.0 / (l.best_trending_rank + 1)
                END AS trending_score,
                (
                    (
                        CASE
                            WHEN %s = 'daily' THEN
                                (COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / SQRT(COALESCE(NULLIF(l.stars, 0), 1)))
                                * (1.0 + LEAST(COALESCE(l.baseline_daily, 0.0), 200.0) / 400.0)
                            WHEN %s = 'weekly' THEN
                                (COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / GREATEST(LOG(COALESCE(l.stars, 0) + 10.0), 1.0))
                                * (1.0 + LEAST(COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / (COALESCE(l.baseline_daily, 0.0) * 7.0 + 1.0), 5.0) / 5.0)
                            ELSE
                                COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0)
                                * (1.0 + LEAST(COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / (COALESCE(l.baseline_daily, 0.0) * 30.0 + 1.0), 4.0) / 10.0)
                        END
                    )
                    * CASE
                        WHEN %s = 'daily' AND CAST(DATEDIFF(l.snapshot_date, LEFT(c.created_at, 10)) AS DOUBLE) <= 90 THEN 1.25
                        WHEN %s = 'daily' THEN 0.72
                        WHEN %s = 'weekly' AND CAST(DATEDIFF(l.snapshot_date, LEFT(c.created_at, 10)) AS DOUBLE) <= 180 THEN 1.12
                        WHEN %s = 'weekly' THEN 0.9
                        WHEN CAST(DATEDIFF(l.snapshot_date, LEFT(c.created_at, 10)) AS DOUBLE) <= 365 THEN 1.05
                        ELSE 0.96
                    END
                    * CASE
                        WHEN %s = 'daily' AND l.stars >= 5000 THEN 0.72
                        WHEN %s = 'weekly' AND l.stars >= 20000 AND COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) < 1000 THEN 0.85
                        ELSE 1.0
                    END
                    * (1.0 + CASE WHEN l.best_trending_rank IS NULL THEN 0.0 ELSE 1.2 / (l.best_trending_rank + 2) END)
                    * (1.0 / POWER(1.0 + GREATEST(DATEDIFF(NOW(), l.captured_at) * 24.0, 0.0), %s))
                ) AS rank_score,
                CASE
                    WHEN COALESCE(l.baseline_daily, 0.0) <= 0 THEN 0.0
                    ELSE COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / (l.baseline_daily * %s + 1.0)
                END AS spike_ratio
            FROM latest_with_prev l
            JOIN github_repo_candidates c ON c.repo_id = l.repo_id
            WHERE (
                %s != 'daily'
                OR CAST(DATEDIFF(l.snapshot_date, LEFT(c.created_at, 10)) AS DOUBLE) <= 90
                OR COALESCE(GREATEST(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) >= 300
                OR COALESCE(l.best_trending_rank, 999) <= 10
            )
            ORDER BY rank_score DESC, growth DESC, l.stars DESC
            LIMIT %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        period,
                        period,
                        period,
                        period,
                        period,
                        period,
                        period,
                        period,
                        period,
                        decay_exp,
                        float(window_days),
                        period,
                        limit,
                    ),
                )
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def get_github_snapshot_count(self) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM github_repo_snapshots")
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)
        finally:
            conn.close()

    def list_github_project_metric_targets(
        self,
        *,
        min_stars: int = 500,
        limit: int = 0,
    ) -> List[Dict[str, Any]]:
        filters = ["COALESCE(stars, 0) >= %s", "COALESCE(full_name, '') != ''"]
        params: List[Any] = [min_stars]
        limit_sql = ""
        if limit and int(limit) > 0:
            limit_sql = " LIMIT %s"
            params.append(max(1, min(int(limit), 20000)))
        sql = f"""
            SELECT
                repo_id,
                full_name,
                title,
                url,
                description,
                language,
                topics_json,
                created_at,
                pushed_at,
                COALESCE(stars, 0) AS stars,
                COALESCE(forks, 0) AS forks,
                COALESCE(watchers, 0) AS watchers,
                source_channels,
                first_seen_at,
                last_seen_at,
                last_snapshot_at
            FROM github_repo_candidates
            WHERE {' AND '.join(filters)}
            ORDER BY COALESCE(stars, 0) DESC, full_name ASC
            {limit_sql}
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def get_github_metric_refresh_status(
        self,
        *,
        metric_date: str,
        min_stars: int = 500,
        limit: int = 0,
    ) -> Dict[str, Any]:
        """Return current-day snapshot/metric coverage for eligible projects."""
        targets = self.list_github_project_metric_targets(
            min_stars=min_stars,
            limit=limit,
        )
        repo_ids = [
            str(item.get("repo_id") or "").strip()
            for item in targets
            if str(item.get("repo_id") or "").strip()
        ]
        if not repo_ids:
            return {
                "metric_date": metric_date,
                "target_count": 0,
                "snapshot_count": 0,
                "metric_count": 0,
                "oldest_captured_at": None,
            }

        placeholders = ", ".join(["%s"] * len(repo_ids))
        sql = f"""
            SELECT
                COUNT(DISTINCT s.repo_id) AS snapshot_count,
                COUNT(DISTINCT m.repo_id) AS metric_count,
                MIN(s.captured_at) AS oldest_captured_at
            FROM github_repo_candidates c
            LEFT JOIN github_repo_snapshots s
              ON s.repo_id = c.repo_id
             AND s.snapshot_date = %s
            LEFT JOIN github_repo_daily_metrics m
              ON m.repo_id = c.repo_id
             AND m.metric_date = %s
            WHERE c.repo_id IN ({placeholders})
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple([metric_date, metric_date] + repo_ids))
                row = cur.fetchone() or {}
            conn.commit()
            return {
                "metric_date": metric_date,
                "target_count": len(repo_ids),
                "snapshot_count": int(row.get("snapshot_count") or 0),
                "metric_count": int(row.get("metric_count") or 0),
                "oldest_captured_at": row.get("oldest_captured_at"),
            }
        finally:
            conn.close()

    def get_github_daily_metric_inputs(
        self,
        *,
        metric_date: str,
        previous_date: str,
        baseline_start_date: str,
        min_stars: int = 500,
        repo_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_repo_ids = [str(repo_id).strip() for repo_id in (repo_ids or []) if str(repo_id).strip()]
        repo_filter = ""
        repo_filter_params: List[Any] = []
        if normalized_repo_ids:
            placeholders = ", ".join(["%s"] * len(normalized_repo_ids))
            repo_filter = f" AND s.repo_id IN ({placeholders})"
            repo_filter_params.extend(normalized_repo_ids)
        sql = f"""
            SELECT
                s.repo_id,
                c.full_name,
                s.snapshot_date AS metric_date,
                COALESCE(s.stars, 0) AS stars,
                COALESCE(s.forks, 0) AS forks,
                COALESCE(s.watchers, 0) AS watchers,
                s.community_metrics_complete AS community_metrics_complete,
                COALESCE(s.open_issues, 0) AS open_issues,
                s.repo_created_at,
                COALESCE(NULLIF(s.repo_pushed_at, ''), NULLIF(c.pushed_at, '')) AS repo_pushed_at,
                prev.snapshot_date AS previous_snapshot_date,
                COALESCE(prev.stars, 0) AS previous_stars,
                COALESCE(prev.forks, 0) AS previous_forks,
                COALESCE(prev.watchers, 0) AS previous_watchers,
                prev.community_metrics_complete AS previous_community_metrics_complete,
                daily_hit.period_star_growth AS trending_daily_star_growth,
                daily_hit.period_growth_observed_at AS trending_daily_observed_at,
                COALESCE((
                    SELECT AVG(m.daily_star_growth)
                    FROM github_repo_daily_metrics m
                    WHERE m.repo_id = s.repo_id
                      AND m.metric_date >= %s
                      AND m.metric_date < %s
                      AND m.daily_growth_source IN ('snapshot_delta', 'github_trending_daily')
                ), 0.0) AS baseline_7d,
                (
                    SELECT COUNT(*)
                    FROM github_repo_daily_metrics m
                    WHERE m.repo_id = s.repo_id
                      AND m.metric_date >= %s
                      AND m.metric_date < %s
                      AND m.daily_growth_source IN ('snapshot_delta', 'github_trending_daily')
                ) AS baseline_sample_count
            FROM github_repo_snapshots s
            LEFT JOIN github_repo_snapshots prev
              ON prev.repo_id = s.repo_id
             AND prev.snapshot_date = %s
            LEFT JOIN github_repo_candidates c ON c.repo_id = s.repo_id
            LEFT JOIN github_trending_hits daily_hit
              ON daily_hit.repo_id = s.repo_id
             AND daily_hit.period = 'daily'
             AND daily_hit.observed_date = %s
             AND daily_hit.period_star_growth IS NOT NULL
            WHERE s.snapshot_date = %s
              AND COALESCE(s.stars, c.stars, 0) >= %s
              {repo_filter}
            ORDER BY COALESCE(s.stars, 0) DESC, COALESCE(c.full_name, s.repo_id) ASC
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    tuple(
                        [
                            baseline_start_date,
                            metric_date,
                            baseline_start_date,
                            metric_date,
                            previous_date,
                            metric_date,
                            metric_date,
                            min_stars,
                        ]
                        + repo_filter_params
                    ),
                )
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def upsert_github_daily_metrics(self, metrics: List[Dict[str, Any]]) -> int:
        if not metrics:
            return 0
        sql = """
            INSERT INTO github_repo_daily_metrics (
                repo_id,
                metric_date,
                stars,
                forks,
                watchers,
                open_issues,
                previous_snapshot_date,
                previous_stars,
                daily_star_growth,
                daily_fork_growth,
                daily_watcher_growth,
                daily_growth_available,
                daily_growth_source,
                daily_growth_observed_at,
                scale_corrected_growth_score,
                growth_acceleration_score,
                absolute_growth_score,
                maintenance_activity_score,
                community_engagement_score,
                hot_score,
                score_version,
                updated_at
            ) VALUES (
                %(repo_id)s,
                %(metric_date)s,
                %(stars)s,
                %(forks)s,
                %(watchers)s,
                %(open_issues)s,
                %(previous_snapshot_date)s,
                %(previous_stars)s,
                %(daily_star_growth)s,
                %(daily_fork_growth)s,
                %(daily_watcher_growth)s,
                %(daily_growth_available)s,
                %(daily_growth_source)s,
                %(daily_growth_observed_at)s,
                %(scale_corrected_growth_score)s,
                %(growth_acceleration_score)s,
                %(absolute_growth_score)s,
                %(maintenance_activity_score)s,
                %(community_engagement_score)s,
                %(hot_score)s,
                %(score_version)s,
                %(updated_at)s
            )
            ON DUPLICATE KEY UPDATE
                stars=VALUES(stars),
                forks=VALUES(forks),
                watchers=VALUES(watchers),
                open_issues=VALUES(open_issues),
                previous_snapshot_date=VALUES(previous_snapshot_date),
                previous_stars=VALUES(previous_stars),
                daily_star_growth=VALUES(daily_star_growth),
                daily_fork_growth=VALUES(daily_fork_growth),
                daily_watcher_growth=VALUES(daily_watcher_growth),
                daily_growth_available=VALUES(daily_growth_available),
                daily_growth_source=VALUES(daily_growth_source),
                daily_growth_observed_at=VALUES(daily_growth_observed_at),
                scale_corrected_growth_score=VALUES(scale_corrected_growth_score),
                growth_acceleration_score=VALUES(growth_acceleration_score),
                absolute_growth_score=VALUES(absolute_growth_score),
                maintenance_activity_score=VALUES(maintenance_activity_score),
                community_engagement_score=VALUES(community_engagement_score),
                hot_score=VALUES(hot_score),
                score_version=VALUES(score_version),
                updated_at=VALUES(updated_at)
        """
        normalized: List[Dict[str, Any]] = []
        for metric in metrics:
            payload = dict(metric)
            payload.setdefault("stars", 0)
            payload.setdefault("forks", 0)
            payload.setdefault("watchers", 0)
            payload.setdefault("open_issues", 0)
            payload.setdefault("previous_snapshot_date", None)
            payload.setdefault("previous_stars", 0)
            payload.setdefault("daily_star_growth", 0)
            payload.setdefault("daily_fork_growth", 0)
            payload.setdefault("daily_watcher_growth", 0)
            payload["daily_growth_available"] = 1 if payload.get("daily_growth_available") else 0
            payload.setdefault("daily_growth_source", "unavailable")
            payload.setdefault("daily_growth_observed_at", None)
            payload.setdefault("scale_corrected_growth_score", 0.0)
            payload.setdefault("growth_acceleration_score", 0.0)
            payload.setdefault("absolute_growth_score", 0.0)
            payload.setdefault("maintenance_activity_score", 0.0)
            payload.setdefault("community_engagement_score", 0.0)
            payload.setdefault("hot_score", 0.0)
            payload.setdefault("score_version", "daily_hot_v4")
            payload.setdefault("updated_at", _utcnow())
            normalized.append(payload)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, normalized)
                affected = cur.rowcount
            conn.commit()
            return int(affected or 0)
        finally:
            conn.close()

    def list_github_projects(
        self,
        *,
        category: str = "",
        subcategory: str = "",
        q: str = "",
        language: str = "",
        page: int = 1,
        page_size: int = 24,
        sort: str = "stars",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> Dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 24), 100))
        offset = (page - 1) * page_size
        filters = ["COALESCE(c.stars, 0) >= %s"]
        params: List[Any] = [min_stars]

        if enriched_only:
            filters.append("e.status = 'succeeded'")
        if category:
            filters.append("e.category_slug = %s")
            params.append(category)
        if subcategory:
            default_subcategory = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            if category and subcategory == default_subcategory:
                filters.append("(e.subcategory_slug = %s OR COALESCE(e.subcategory_slug, '') = '')")
            else:
                filters.append("e.subcategory_slug = %s")
            params.append(subcategory)
        if language:
            filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)")
            params.append(language)
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                "("
                "c.full_name LIKE %s OR c.title LIKE %s OR c.description LIKE %s OR "
                "COALESCE(e.description_zh, '') LIKE %s OR COALESCE(c.language, '') LIKE %s OR "
                "COALESCE(c.topics_json, '') LIKE %s OR COALESCE(e.tags_json, '') LIKE %s"
                ")"
            )
            params.extend([like, like, like, like, like, like, like])

        metric_date = _today_local_date()
        order_by = {
            "hot": "hot_score DESC, daily_star_growth DESC, stars DESC, c.full_name ASC",
            "stars": "stars DESC, forks DESC, c.full_name ASC",
            "updated": "COALESCE(NULLIF(c.pushed_at, ''), NULLIF(c.last_seen_at, ''), c.first_seen_at, '') DESC, stars DESC",
            "recent": "COALESCE(NULLIF(c.first_seen_at, ''), c.last_seen_at, '') DESC, stars DESC",
            "name": "c.full_name ASC",
        }.get(sort, "stars DESC, forks DESC, c.full_name ASC")

        where_clause = " AND ".join(filters)
        from_sql = f"""
            FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
            LEFT JOIN github_repo_daily_metrics gm
              ON gm.repo_id = c.repo_id
             AND gm.metric_date = %s
            LEFT JOIN github_repo_recommendations gr
              ON gr.repo_id = c.repo_id
             AND gr.active = 1
            WHERE {where_clause}
        """
        count_sql = f"SELECT COUNT(*) AS cnt {from_sql}"
        rows_sql = f"""
            SELECT
                c.repo_id,
                c.full_name,
                c.title,
                c.url,
                c.description,
                c.language,
                c.topics_json,
                c.created_at,
                c.pushed_at,
                c.source_channels,
                c.first_seen_at,
                c.last_seen_at,
                c.last_snapshot_at,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.stars ELSE COALESCE(c.stars, 0) END AS stars,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.forks ELSE COALESCE(c.forks, 0) END AS forks,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.watchers ELSE COALESCE(c.watchers, 0) END AS watchers,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.open_issues ELSE 0 END AS open_issues,
                gm.metric_date AS snapshot_date,
                c.last_snapshot_at AS captured_at,
                gm.metric_date AS daily_growth_date,
                gm.previous_snapshot_date,
                COALESCE(gm.daily_star_growth, 0) AS daily_star_growth,
                COALESCE(gm.daily_growth_available, 0) AS daily_growth_available,
                COALESCE(gm.daily_growth_source, 'unavailable') AS daily_growth_source,
                gm.daily_growth_observed_at,
                COALESCE(gm.hot_score, 0) AS hot_score,
                COALESCE(gm.scale_corrected_growth_score, 0) AS scale_corrected_growth_score,
                COALESCE(gm.growth_acceleration_score, 0) AS growth_acceleration_score,
                COALESCE(gm.absolute_growth_score, 0) AS absolute_growth_score,
                COALESCE(gm.maintenance_activity_score, 0) AS maintenance_activity_score,
                COALESCE(gm.community_engagement_score, 0) AS community_engagement_score,
                COALESCE(gm.daily_star_growth, 0) AS raw_score,
                COALESCE(gm.hot_score, 0) AS score,
                e.category_slug,
                e.category_name,
                e.subcategory_slug,
                e.subcategory_name,
                e.description_zh,
                e.tags_json,
                e.confidence,
                e.status AS enrichment_status,
                e.enriched_at,
                (gr.repo_id IS NOT NULL) AS is_recommended,
                gr.recommended_at AS recommended_at
            {from_sql}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        """

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                metric_params = [metric_date] + params
                cur.execute(count_sql, tuple(metric_params))
                total_row = cur.fetchone()
                total = int(total_row["cnt"] if total_row else 0)
                cur.execute(rows_sql, tuple(metric_params + [page_size, offset]))
                rows = cur.fetchall()
            conn.commit()
            return {
                "items": [_normalize_github_project_row(row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    def get_github_project_categories(
        self,
        *,
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_project_categories(
            source="github",
            min_stars=min_stars,
            enriched_only=enriched_only,
        ).get("items", [])

    def get_tool_website_by_hash(self, normalized_url_hash: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM tool_websites WHERE normalized_url_hash = %s LIMIT 1",
                    (normalized_url_hash,),
                )
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_tool_website(self, payload: Dict[str, Any], *, update_existing: bool = True) -> Dict[str, Any]:
        now = _utcnow()
        data = dict(payload)
        data.setdefault("title", "")
        data.setdefault("description", "")
        data.setdefault("image_url", "")
        data.setdefault("raw_metadata_json", "{}")
        data.setdefault("fetch_status", "succeeded")
        data.setdefault("fetch_error", None)
        data["visibility"] = str(data.get("visibility") or "public").strip().lower()
        if data["visibility"] not in {"public", "private"}:
            data["visibility"] = "public"
        data.setdefault("added_by_user_id", None)
        data.setdefault("first_seen_at", now)
        data.setdefault("last_seen_at", now)
        data.setdefault("updated_at", now)
        update_clause = """
                canonical_url=VALUES(canonical_url),
                domain=VALUES(domain),
                title=COALESCE(NULLIF(VALUES(title), ''), title),
                description=COALESCE(NULLIF(VALUES(description), ''), description),
                image_url=COALESCE(NULLIF(VALUES(image_url), ''), image_url),
                raw_metadata_json=VALUES(raw_metadata_json),
                fetch_status=VALUES(fetch_status),
                fetch_error=VALUES(fetch_error),
                source_fingerprint=VALUES(source_fingerprint),
                visibility=IF(visibility = 'public' OR VALUES(visibility) = 'public', 'public', 'private'),
                last_seen_at=VALUES(last_seen_at),
                updated_at=VALUES(updated_at)
        """
        if not update_existing:
            update_clause = """
                last_seen_at=VALUES(last_seen_at),
                updated_at=VALUES(updated_at)
            """
        sql = f"""
            INSERT INTO tool_websites (
                canonical_url, normalized_url_hash, domain, title, description,
                image_url, raw_metadata_json, fetch_status, fetch_error,
                source_fingerprint, visibility, added_by_user_id, first_seen_at, last_seen_at, updated_at
            ) VALUES (
                %(canonical_url)s, %(normalized_url_hash)s, %(domain)s, %(title)s, %(description)s,
                %(image_url)s, %(raw_metadata_json)s, %(fetch_status)s, %(fetch_error)s,
                %(source_fingerprint)s, %(visibility)s, %(added_by_user_id)s, %(first_seen_at)s, %(last_seen_at)s, %(updated_at)s
            )
            ON DUPLICATE KEY UPDATE
                {update_clause}
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, data)
                cur.execute(
                    "SELECT * FROM tool_websites WHERE normalized_url_hash = %s LIMIT 1",
                    (data["normalized_url_hash"],),
                )
                row = cur.fetchone() or {}
            conn.commit()
            return dict(row)
        finally:
            conn.close()

    def get_tool_website_enrichment(self, website_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM tool_website_enrichments WHERE website_id = %s LIMIT 1",
                    (website_id,),
                )
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_tool_website(self, website_id: int) -> bool:
        website_id = int(website_id)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM project_favorites WHERE project_source = 'website' AND project_id = %s",
                    (str(website_id),),
                )
                cur.execute(
                    "DELETE FROM user_tool_websites WHERE website_id = %s",
                    (website_id,),
                )
                cur.execute(
                    "DELETE FROM tool_website_enrichments WHERE website_id = %s",
                    (website_id,),
                )
                cur.execute(
                    "DELETE FROM tool_websites WHERE id = %s",
                    (website_id,),
                )
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            conn.close()

    def upsert_tool_website_enrichment(self, payload: Dict[str, Any]) -> None:
        now = _utcnow()
        data = dict(payload)
        data.setdefault("tags_json", _json_dumps(data.get("tags") or []))
        data["subcategory_slug"] = data.get("subcategory_slug") or ""
        data["subcategory_name"] = data.get("subcategory_name") or ""
        data.setdefault("confidence", 0.0)
        data.setdefault("model_provider", "")
        data.setdefault("model_name", "")
        data.setdefault("status", "succeeded")
        data.setdefault("error_msg", None)
        data.setdefault("enriched_at", now)
        data.setdefault("updated_at", now)
        sql = """
            INSERT INTO tool_website_enrichments (
                website_id, category_slug, category_name, subcategory_slug, subcategory_name, description_zh, tags_json,
                confidence, source_fingerprint, prompt_version, model_provider, model_name,
                status, error_msg, enriched_at, updated_at
            ) VALUES (
                %(website_id)s, %(category_slug)s, %(category_name)s, %(subcategory_slug)s, %(subcategory_name)s, %(description_zh)s, %(tags_json)s,
                %(confidence)s, %(source_fingerprint)s, %(prompt_version)s, %(model_provider)s, %(model_name)s,
                %(status)s, %(error_msg)s, %(enriched_at)s, %(updated_at)s
            )
            ON DUPLICATE KEY UPDATE
                category_slug=VALUES(category_slug),
                category_name=VALUES(category_name),
                subcategory_slug=VALUES(subcategory_slug),
                subcategory_name=VALUES(subcategory_name),
                description_zh=VALUES(description_zh),
                tags_json=VALUES(tags_json),
                confidence=VALUES(confidence),
                source_fingerprint=VALUES(source_fingerprint),
                prompt_version=VALUES(prompt_version),
                model_provider=VALUES(model_provider),
                model_name=VALUES(model_name),
                status=VALUES(status),
                error_msg=VALUES(error_msg),
                enriched_at=VALUES(enriched_at),
                updated_at=VALUES(updated_at)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, data)
            conn.commit()
        finally:
            conn.close()

    def mark_tool_website_enrichment_failed(
        self,
        website_id: int,
        *,
        source_fingerprint: str,
        prompt_version: str,
        error_msg: str,
        model_provider: str = "",
        model_name: str = "",
    ) -> None:
        self.upsert_tool_website_enrichment(
            {
                "website_id": website_id,
                "category_slug": "other",
                "category_name": "其他",
                "subcategory_slug": "other_uncategorized",
                "subcategory_name": "未分类",
                "description_zh": "",
                "tags_json": "[]",
                "confidence": 0.0,
                "source_fingerprint": source_fingerprint,
                "prompt_version": prompt_version,
                "model_provider": model_provider,
                "model_name": model_name,
                "status": "failed",
                "error_msg": error_msg[:2000],
            }
        )

    def recommend_github_project(
        self,
        *,
        repo_id: Any = None,
        full_name: str = "",
        recommended_by_user_id: int | None = None,
    ) -> Dict[str, Any]:
        identity = str(repo_id or "").strip()
        clean_full_name = (full_name or "").strip()
        if not identity and not clean_full_name:
            raise ValueError("repo_id 或 full_name 不能为空")
        user_id = int(recommended_by_user_id) if recommended_by_user_id else None
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                resolved = self._resolve_github_repo_id_cur(cur, identity, clean_full_name or identity)
                cur.execute(
                    """
                    SELECT repo_id, full_name
                    FROM github_repo_candidates
                    WHERE repo_id = %s
                       OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                       OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                    ORDER BY (repo_id = %s) DESC,
                             COALESCE(stars, 0) DESC,
                             COALESCE(last_seen_at, '') DESC
                    LIMIT 1
                    """,
                    (resolved, identity, clean_full_name, resolved),
                )
                row = cur.fetchone()
                if not row or not row.get("repo_id"):
                    raise LookupError("GitHub 项目不存在")
                canonical_repo_id = str(row["repo_id"])
                cur.execute(
                    """
                    INSERT INTO github_repo_recommendations (repo_id, active, recommended_by_user_id)
                    VALUES (%s, 1, %s)
                    ON DUPLICATE KEY UPDATE
                        active = 1,
                        recommended_by_user_id = VALUES(recommended_by_user_id),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (canonical_repo_id, user_id),
                )
                cur.execute(
                    """
                    SELECT recommended_at
                    FROM github_repo_recommendations
                    WHERE repo_id = %s AND active = 1
                    LIMIT 1
                    """,
                    (canonical_repo_id,),
                )
                recommendation = cur.fetchone() or {}
            conn.commit()
            return {
                "repo_id": canonical_repo_id,
                "full_name": row.get("full_name") or clean_full_name or identity,
                "is_recommended": True,
                "recommended_at": _to_iso_string(recommendation.get("recommended_at")),
            }
        finally:
            conn.close()

    def unrecommend_github_project(
        self,
        *,
        repo_id: Any = None,
        full_name: str = "",
    ) -> Dict[str, Any]:
        identity = str(repo_id or "").strip()
        clean_full_name = (full_name or "").strip()
        if not identity and not clean_full_name:
            raise ValueError("repo_id 或 full_name 不能为空")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                resolved = self._resolve_github_repo_id_cur(cur, identity, clean_full_name or identity)
                cur.execute(
                    """
                    SELECT repo_id, full_name
                    FROM github_repo_candidates
                    WHERE repo_id = %s
                       OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                       OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                    ORDER BY (repo_id = %s) DESC,
                             COALESCE(stars, 0) DESC,
                             COALESCE(last_seen_at, '') DESC
                    LIMIT 1
                    """,
                    (resolved, identity, clean_full_name, resolved),
                )
                row = cur.fetchone()
                if not row or not row.get("repo_id"):
                    raise LookupError("GitHub 项目不存在")
                canonical_repo_id = str(row["repo_id"])
                cur.execute(
                    """
                    UPDATE github_repo_recommendations
                    SET active = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE repo_id = %s AND active = 1
                    """,
                    (canonical_repo_id,),
                )
                removed = cur.rowcount > 0
            conn.commit()
            return {
                "repo_id": canonical_repo_id,
                "full_name": row.get("full_name") or clean_full_name or identity,
                "is_recommended": False,
                "recommended_at": None,
                "removed": removed,
            }
        finally:
            conn.close()

    def _favorite_project_key_cur(
        self,
        cur,
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
            resolved = self._resolve_github_repo_id_cur(cur, identity, identity)
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
    ) -> Dict[str, Any]:
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
            conn.commit()
            result: Dict[str, Any] = {
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
    ) -> Dict[str, Any]:
        user_id = int(user_id)
        website_id = int(website_id)
        added_via = (added_via or "auto").strip().lower()
        if added_via not in {"auto", "manual", "existing"}:
            added_via = "auto"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM tool_websites WHERE id = %s LIMIT 1", (website_id,))
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
                cur.execute(
                    """
                    DELETE FROM project_favorites
                    WHERE user_id = %s AND project_source = 'website' AND project_id = %s
                    """,
                    (user_id, str(website_id)),
                )
                deleted_favorite = cur.rowcount > 0
            conn.commit()
            return deleted_link or deleted_favorite
        finally:
            conn.close()

    def get_tool_website_item(self, website_id: int) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT
                CONCAT('website:', w.id) AS id,
                'website' AS source,
                NULL AS repo_id,
                w.id AS website_id,
                COALESCE(NULLIF(w.title, ''), w.domain) AS full_name,
                w.title,
                w.canonical_url AS url,
                w.domain,
                COALESCE(NULLIF(w.image_url, ''), CONCAT(SUBSTRING_INDEX(w.canonical_url, '/', 3), '/favicon.ico')) AS image_url,
                w.description,
                e.description_zh,
                e.category_slug,
                e.category_name,
                e.subcategory_slug,
                e.subcategory_name,
                e.tags_json,
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
                0 AS is_favorited,
                NULL AS favorited_at,
                0 AS user_added,
                NULL AS user_added_at
            FROM tool_websites w
            LEFT JOIN tool_website_enrichments e ON e.website_id = w.id
            WHERE w.id = %s
            LIMIT 1
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (website_id,))
                row = cur.fetchone()
            conn.commit()
            return _normalize_project_row(row) if row else None
        finally:
            conn.close()

    def get_tool_website_item_for_user(self, *, user_id: int, website_id: int) -> Optional[Dict[str, Any]]:
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

    def upsert_user_tool_website_override(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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
            conn.commit()
        finally:
            conn.close()
        item = self.get_tool_website_item_for_user(user_id=user_id, website_id=website_id)
        if not item:
            raise LookupError("工具网站不存在")
        return item

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
    ) -> List[str]:
        terms = project_search_terms(q)
        if not terms:
            return []
        limit = max(1, min(int(limit or 200), 200))
        normalized_query = normalize_search_query(q)
        filters = ["COALESCE(c.stars, 0) >= %s", "ga.alias_repo_id IS NULL"]
        params: List[Any] = [min_stars]
        if enriched_only:
            filters.append("ge.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci")
        if category:
            filters.append("ge.category_slug = %s")
            params.append(category)
        if subcategory:
            default_subcategory = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            if category and subcategory == default_subcategory:
                filters.append("(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
            else:
                filters.append("ge.subcategory_slug = %s")
            params.append(subcategory)
        if language:
            filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)")
            params.append(language)
        if tag:
            filters.append("COALESCE(ge.tags_json, '') LIKE %s")
            params.append(f'%"{tag.strip()}"%')

        term_filter = (
            "(c.full_name LIKE %s ESCAPE '=' OR c.title LIKE %s ESCAPE '=' OR "
            "c.description LIKE %s ESCAPE '=' OR COALESCE(ge.description_zh, '') LIKE %s ESCAPE '=' OR "
            "COALESCE(c.language, '') LIKE %s ESCAPE '=' OR COALESCE(c.topics_json, '') LIKE %s ESCAPE '=' OR "
            "COALESCE(ge.tags_json, '') LIKE %s ESCAPE '=')"
        )
        for term in terms:
            filters.append(term_filter)
            params.extend([f"%{_escape_like_literal(term)}%"] * 7)

        prefix = f"{_escape_like_literal(normalized_query)}%"
        sql = f"""
            SELECT c.repo_id
            FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
            LEFT JOIN github_repo_aliases ga
              ON ga.alias_repo_id = c.repo_id
             AND ga.canonical_repo_id <> c.repo_id
            WHERE {' AND '.join(filters)}
            ORDER BY
                CASE
                    WHEN LOWER(c.full_name) = LOWER(%s) THEN 0
                    WHEN LOWER(COALESCE(c.title, '')) = LOWER(%s) THEN 1
                    WHEN c.full_name LIKE %s ESCAPE '=' THEN 2
                    WHEN COALESCE(c.title, '') LIKE %s ESCAPE '=' THEN 3
                    ELSE 4
                END,
                COALESCE(c.stars, 0) DESC,
                c.full_name ASC
            LIMIT %s
        """
        query_params = params + [normalized_query, normalized_query, prefix, prefix, limit]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(query_params))
                rows = cur.fetchall()
            conn.commit()
            return [str(row.get("repo_id") or "") for row in rows if row.get("repo_id")]
        finally:
            conn.close()

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
        candidate_repo_ids: List[str] | None = None,
    ) -> Dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 24), 100))
        offset = (page - 1) * page_size
        source = (source or "all").strip().lower()
        if source not in {"all", "github", "website"}:
            source = "all"
        scope = (scope or "all").strip().lower()
        if scope not in {"all", "today", "recommended"}:
            scope = "all"
        user_id = int(user_id) if user_id else None
        favorites_only = bool(favorites_only and user_id)
        clean_candidate_repo_ids = None
        if candidate_repo_ids is not None:
            clean_candidate_repo_ids = list(
                dict.fromkeys(str(repo_id).strip() for repo_id in candidate_repo_ids if str(repo_id).strip())
            )[:200]
            if not clean_candidate_repo_ids or source == "website":
                return {"items": [], "total": 0, "page": page, "page_size": page_size}
            source = "github"
        clean_tag = (tag or "").strip()
        website_effective_full_name = "COALESCE(NULLIF(uo.title, ''), NULLIF(w.title, ''), w.domain)" if user_id else "COALESCE(NULLIF(w.title, ''), w.domain)"
        website_effective_title = "COALESCE(NULLIF(uo.title, ''), w.title)" if user_id else "w.title"
        website_effective_description = "COALESCE(NULLIF(uo.description, ''), w.description)" if user_id else "w.description"
        website_effective_image_url = "COALESCE(NULLIF(uo.image_url, ''), NULLIF(w.image_url, ''), CONCAT(SUBSTRING_INDEX(w.canonical_url, '/', 3), '/favicon.ico'))" if user_id else "COALESCE(NULLIF(w.image_url, ''), CONCAT(SUBSTRING_INDEX(w.canonical_url, '/', 3), '/favicon.ico'))"
        website_effective_category_slug = "COALESCE(NULLIF(uo.category_slug, ''), we.category_slug)" if user_id else "we.category_slug"
        website_effective_category_name = "COALESCE(NULLIF(uo.category_name, ''), we.category_name)" if user_id else "we.category_name"
        website_effective_subcategory_slug = "COALESCE(NULLIF(uo.subcategory_slug, ''), we.subcategory_slug)" if user_id else "we.subcategory_slug"
        website_effective_subcategory_name = "COALESCE(NULLIF(uo.subcategory_name, ''), we.subcategory_name)" if user_id else "we.subcategory_name"
        website_effective_description_zh = "COALESCE(NULLIF(uo.description_zh, ''), we.description_zh)" if user_id else "we.description_zh"
        website_effective_tags_json = "COALESCE(NULLIF(uo.tags_json, ''), we.tags_json)" if user_id else "we.tags_json"

        github_filters = ["COALESCE(c.stars, 0) >= %s"]
        website_filters = ["1 = 1"]
        github_params: List[Any] = [min_stars]
        website_params: List[Any] = []
        if not favorites_only:
            website_filters.append("w.visibility COLLATE utf8mb4_unicode_ci = _utf8mb4'public' COLLATE utf8mb4_unicode_ci")
        if clean_candidate_repo_ids is not None:
            placeholders = ", ".join(["%s"] * len(clean_candidate_repo_ids))
            github_filters.append(f"c.repo_id IN ({placeholders})")
            github_params.extend(clean_candidate_repo_ids)
        if enriched_only:
            github_filters.append("ge.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci")
            if favorites_only:
                website_filters.append(
                    "(we.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci OR uo.id IS NOT NULL OR utw.id IS NOT NULL)"
                )
            else:
                website_filters.append("we.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci")
        metric_date = _today_local_date()
        today_top_status = (
            "AND ge_top.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci"
            if enriched_only
            else ""
        )
        github_hot_join = """
            LEFT JOIN github_repo_daily_metrics gm
              ON gm.repo_id = c.repo_id
             AND gm.metric_date = %s
        """
        github_hot_columns = """
                gm.metric_date AS snapshot_date,
                c.last_snapshot_at AS captured_at,
                NULL AS rank_in_period,
                COALESCE(gm.daily_star_growth, 0) AS raw_score,
                COALESCE(gm.hot_score, 0) AS score,
                gm.metric_date AS daily_growth_date,
                gm.previous_snapshot_date,
                COALESCE(gm.daily_star_growth, 0) AS daily_star_growth,
                COALESCE(gm.daily_growth_available, 0) AS daily_growth_available,
                COALESCE(gm.daily_growth_source, 'unavailable') AS daily_growth_source,
                gm.daily_growth_observed_at,
                COALESCE(gm.hot_score, 0) AS hot_score,
                COALESCE(gm.scale_corrected_growth_score, 0) AS scale_corrected_growth_score,
                COALESCE(gm.growth_acceleration_score, 0) AS growth_acceleration_score,
                COALESCE(gm.absolute_growth_score, 0) AS absolute_growth_score,
                COALESCE(gm.maintenance_activity_score, 0) AS maintenance_activity_score,
                COALESCE(gm.community_engagement_score, 0) AS community_engagement_score,
        """
        github_hot_params: List[Any] = [metric_date]
        if scope == "today":
            github_hot_join += f"""
            JOIN (
                SELECT c_top.repo_id
                FROM github_repo_candidates c_top
                JOIN github_repo_daily_metrics gm_top
                  ON gm_top.repo_id = c_top.repo_id
                 AND gm_top.metric_date = %s
                 AND gm_top.daily_growth_available = 1
                 AND gm_top.daily_star_growth > 0
                LEFT JOIN github_repo_enrichments ge_top ON ge_top.repo_id = c_top.repo_id
                WHERE COALESCE(c_top.stars, 0) >= %s
                  {today_top_status}
                ORDER BY gm_top.hot_score DESC,
                         gm_top.daily_star_growth DESC,
                         gm_top.stars DESC,
                         c_top.full_name ASC
                LIMIT {GITHUB_PROJECT_TODAY_LIMIT}
            ) today_top ON today_top.repo_id = c.repo_id
            """
            github_hot_params.extend([metric_date, min_stars])
            github_filters.append("COALESCE(gm.daily_growth_available, 0) = 1")
            github_filters.append("COALESCE(gm.daily_star_growth, 0) > 0")
            website_filters.append("1 = 0")
        elif scope == "recommended":
            github_filters.append("gr.repo_id IS NOT NULL")
            website_filters.append("1 = 0")
        if category:
            github_filters.append("ge.category_slug = %s")
            website_filters.append(f"{website_effective_category_slug} = %s")
            github_params.append(category)
            website_params.append(category)
        if subcategory:
            default_subcategory = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            website_default_subcategory = WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            if category and subcategory == default_subcategory:
                github_filters.append("(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
            else:
                github_filters.append("ge.subcategory_slug = %s")
            if category and subcategory == website_default_subcategory:
                website_filters.append(f"({website_effective_subcategory_slug} = %s OR COALESCE({website_effective_subcategory_slug}, '') = '')")
            else:
                website_filters.append(f"{website_effective_subcategory_slug} = %s")
            github_params.append(subcategory)
            website_params.append(subcategory)
        if language:
            github_filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)")
            github_params.append(language)
            website_filters.append("1 = 0")
        if q:
            terms = project_search_terms(q)
            if terms:
                github_term_filter = (
                    "(c.full_name LIKE %s ESCAPE '=' OR c.title LIKE %s ESCAPE '=' OR "
                    "c.description LIKE %s ESCAPE '=' OR COALESCE(ge.description_zh, '') LIKE %s ESCAPE '=' OR "
                    "COALESCE(c.language, '') LIKE %s ESCAPE '=' OR COALESCE(c.topics_json, '') LIKE %s ESCAPE '=' OR "
                    "COALESCE(ge.tags_json, '') LIKE %s ESCAPE '=')"
                )
                website_term_filter = (
                    f"({website_effective_title} LIKE %s ESCAPE '=' OR w.domain LIKE %s ESCAPE '=' OR "
                    f"{website_effective_description} LIKE %s ESCAPE '=' OR w.canonical_url LIKE %s ESCAPE '=' OR "
                    f"COALESCE({website_effective_description_zh}, '') LIKE %s ESCAPE '=' OR "
                    f"COALESCE({website_effective_tags_json}, '') LIKE %s ESCAPE '=')"
                )
                github_filters.extend([github_term_filter] * len(terms))
                website_filters.extend([website_term_filter] * len(terms))
                for term in terms:
                    like = f"%{_escape_like_literal(term)}%"
                    github_params.extend([like] * 7)
                    website_params.extend([like] * 6)
            else:
                github_filters.append("1 = 0")
                website_filters.append("1 = 0")
        if clean_tag:
            tag_like = f'%"{clean_tag}"%'
            github_filters.append("COALESCE(ge.tags_json, '') LIKE %s")
            website_filters.append(f"COALESCE({website_effective_tags_json}, '') LIKE %s")
            github_params.append(tag_like)
            website_params.append(tag_like)
        if favorites_only:
            github_filters.append("pf.id IS NOT NULL")
            website_filters.append("(pf.id IS NOT NULL OR utw.id IS NOT NULL)")

        recent_order = (
            "COALESCE(CAST(recommended_at AS CHAR), CAST(collection_at AS CHAR), NULLIF(first_seen_at, ''), last_seen_at, '') DESC, stars DESC"
            if scope == "recommended"
            else "COALESCE(CAST(collection_at AS CHAR), NULLIF(first_seen_at, ''), last_seen_at, '') DESC, stars DESC"
        )
        if scope == "today":
            sort = "hot"
        order_by = {
            "hot": "hot_score DESC, daily_star_growth DESC, stars DESC, full_name ASC",
            "stars": "stars DESC, forks DESC, full_name ASC",
            "updated": "COALESCE(NULLIF(pushed_at, ''), NULLIF(last_seen_at, ''), first_seen_at, '') DESC, stars DESC, full_name ASC",
            "recent": f"{recent_order}, full_name ASC",
            "name": "full_name ASC",
        }.get(sort, "hot_score DESC, daily_star_growth DESC, stars DESC, full_name ASC" if scope == "today" else "stars DESC, forks DESC, full_name ASC")

        order_params: List[Any] = []
        if sort == "relevance" and clean_candidate_repo_ids is not None:
            relevance_placeholders = ", ".join(["%s"] * len(clean_candidate_repo_ids))
            order_by = f"FIELD(repo_id, {relevance_placeholders}), full_name ASC"
            order_params.extend(clean_candidate_repo_ids)

        github_favorite_join = ""
        website_favorite_join = ""
        github_favorite_columns = """
                0 AS is_favorited,
                NULL AS favorited_at,
                0 AS user_added,
                NULL AS user_added_at,
                NULL AS collection_at
        """
        website_favorite_columns = github_favorite_columns
        if user_id:
            github_favorite_join = """
            LEFT JOIN project_favorites pf
              ON pf.user_id = %s
             AND pf.project_source = 'github'
             AND pf.project_id = c.repo_id
            """
            website_favorite_join = """
            LEFT JOIN project_favorites pf
              ON pf.user_id = %s
             AND pf.project_source = 'website'
             AND pf.project_id = CAST(w.id AS CHAR)
            LEFT JOIN user_tool_websites utw
              ON utw.user_id = %s
             AND utw.website_id = w.id
            LEFT JOIN user_tool_website_overrides uo
              ON uo.user_id = %s
             AND uo.website_id = w.id
            """
            github_favorite_columns = """
                (pf.id IS NOT NULL) AS is_favorited,
                pf.created_at AS favorited_at,
                0 AS user_added,
                NULL AS user_added_at,
                pf.created_at AS collection_at
            """
            website_favorite_columns = """
                (pf.id IS NOT NULL) AS is_favorited,
                pf.created_at AS favorited_at,
                (utw.id IS NOT NULL) AS user_added,
                utw.created_at AS user_added_at,
                COALESCE(pf.created_at, utw.created_at) AS collection_at
            """

        github_select = f"""
            SELECT
                CONCAT('github:', c.repo_id) AS id,
                'github' AS source,
                c.repo_id,
                NULL AS website_id,
                c.full_name,
                c.title,
                c.url,
                NULL AS domain,
                NULL AS image_url,
                c.description,
                ge.description_zh,
                ge.category_slug,
                ge.category_name,
                ge.subcategory_slug,
                ge.subcategory_name,
                ge.tags_json,
                c.language,
                c.topics_json,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.stars ELSE COALESCE(c.stars, 0) END AS stars,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.forks ELSE COALESCE(c.forks, 0) END AS forks,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.watchers ELSE COALESCE(c.watchers, 0) END AS watchers,
                CASE WHEN gm.repo_id IS NOT NULL THEN gm.open_issues ELSE 0 END AS open_issues,
                c.created_at,
                c.pushed_at,
                c.first_seen_at,
                c.last_seen_at,
                c.last_snapshot_at,
                {github_hot_columns}
                ge.confidence,
                {github_favorite_columns},
                (gr.repo_id IS NOT NULL) AS is_recommended,
                gr.recommended_at AS recommended_at
            FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
            LEFT JOIN github_repo_recommendations gr ON gr.repo_id = c.repo_id AND gr.active = 1
            {github_hot_join}
            {github_favorite_join}
            WHERE {' AND '.join(github_filters)}
        """
        website_select = f"""
            SELECT
                CONCAT('website:', w.id) AS id,
                'website' AS source,
                NULL AS repo_id,
                w.id AS website_id,
                {website_effective_full_name} AS full_name,
                {website_effective_title} AS title,
                w.canonical_url AS url,
                w.domain,
                {website_effective_image_url} AS image_url,
                {website_effective_description} AS description,
                {website_effective_description_zh} AS description_zh,
                {website_effective_category_slug} AS category_slug,
                {website_effective_category_name} AS category_name,
                {website_effective_subcategory_slug} AS subcategory_slug,
                {website_effective_subcategory_name} AS subcategory_name,
                {website_effective_tags_json} AS tags_json,
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
                NULL AS rank_in_period,
                0 AS raw_score,
                0 AS score,
                NULL AS daily_growth_date,
                NULL AS previous_snapshot_date,
                0 AS daily_star_growth,
                0 AS daily_growth_available,
                'unavailable' AS daily_growth_source,
                NULL AS daily_growth_observed_at,
                0 AS hot_score,
                0 AS scale_corrected_growth_score,
                0 AS growth_acceleration_score,
                0 AS absolute_growth_score,
                0 AS maintenance_activity_score,
                0 AS community_engagement_score,
                we.confidence,
                {website_favorite_columns},
                0 AS is_recommended,
                NULL AS recommended_at
            FROM tool_websites w
            LEFT JOIN tool_website_enrichments we ON we.website_id = w.id
            {website_favorite_join}
            WHERE {' AND '.join(website_filters)}
        """
        union_parts: List[str] = []
        params: List[Any] = []
        if source in {"all", "github"}:
            union_parts.append(github_select)
            params.extend(github_hot_params)
            if user_id:
                params.append(user_id)
            params.extend(github_params)
        if source in {"all", "website"}:
            union_parts.append(website_select)
            if user_id:
                params.extend([user_id, user_id, user_id])
            params.extend(website_params)

        base_sql = f"""
            WITH project_rows AS (
                {' UNION ALL '.join(union_parts)}
            )
        """
        count_sql = f"{base_sql} SELECT COUNT(*) AS cnt FROM project_rows"
        rows_sql = f"""
            {base_sql}
            SELECT * FROM project_rows
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(count_sql, tuple(params))
                total_row = cur.fetchone()
                total = int(total_row["cnt"] if total_row else 0)
                cur.execute(rows_sql, tuple(params + order_params + [page_size, offset]))
                rows = cur.fetchall()
            conn.commit()
            return {
                "items": [_normalize_project_row(row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    def get_project_categories(
        self,
        *,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
    ) -> Dict[str, Any]:
        source = (source or "all").strip().lower()
        if source not in {"all", "github", "website"}:
            source = "all"
        user_id = int(user_id) if user_id else None
        favorites_only = bool(favorites_only and user_id)
        status_github = "AND ge.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci" if enriched_only else ""
        status_website = "AND we.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci" if enriched_only else ""
        website_visibility_filter = "" if favorites_only else "AND w.visibility COLLATE utf8mb4_unicode_ci = _utf8mb4'public' COLLATE utf8mb4_unicode_ci"
        github_user_join = ""
        website_user_join = ""
        github_user_filter = ""
        website_user_filter = ""
        if user_id:
            github_user_join = """
                LEFT JOIN project_favorites pf
                  ON pf.user_id = %s
                 AND pf.project_source = 'github'
                 AND pf.project_id = c.repo_id
            """
            website_user_join = """
                LEFT JOIN project_favorites pf
                  ON pf.user_id = %s
                 AND pf.project_source = 'website'
                 AND pf.project_id = CAST(w.id AS CHAR)
                LEFT JOIN user_tool_websites utw
                  ON utw.user_id = %s
                 AND utw.website_id = w.id
            """
            if favorites_only:
                github_user_filter = "AND pf.id IS NOT NULL"
                website_user_filter = "AND (pf.id IS NOT NULL OR utw.id IS NOT NULL)"
        parts: List[str] = []
        params: List[Any] = []
        if source in {"all", "github"}:
            parts.append(
                f"""
                SELECT
                    ge.category_slug AS category_slug,
                    ge.category_name AS category_name,
                    COALESCE(NULLIF(ge.subcategory_slug, ''), '') AS subcategory_slug,
                    COALESCE(NULLIF(ge.subcategory_name, ''), '') AS subcategory_name,
                    COUNT(*) AS count
                FROM github_repo_candidates c
                JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                {github_user_join}
                WHERE COALESCE(c.stars, 0) >= %s
                  {status_github}
                  {github_user_filter}
                GROUP BY ge.category_slug, ge.category_name, ge.subcategory_slug, ge.subcategory_name
                """
            )
            if user_id:
                params.append(user_id)
            params.append(min_stars)
        if source in {"all", "website"}:
            parts.append(
                f"""
                SELECT
                    we.category_slug AS category_slug,
                    we.category_name AS category_name,
                    COALESCE(NULLIF(we.subcategory_slug, ''), '') AS subcategory_slug,
                    COALESCE(NULLIF(we.subcategory_name, ''), '') AS subcategory_name,
                    COUNT(*) AS count
                FROM tool_websites w
                JOIN tool_website_enrichments we ON we.website_id = w.id
                {website_user_join}
                WHERE 1 = 1
                  {status_website}
                  {website_visibility_filter}
                  {website_user_filter}
                GROUP BY we.category_slug, we.category_name, we.subcategory_slug, we.subcategory_name
                """
            )
            if user_id:
                params.extend([user_id, user_id])
        sql = f"""
            WITH category_rows AS (
                {' UNION ALL '.join(parts)}
            )
            SELECT category_slug, category_name, subcategory_slug, subcategory_name, SUM(count) AS count
            FROM category_rows
            GROUP BY category_slug, category_name, subcategory_slug, subcategory_name
        """

        today_start, tomorrow_start = _today_utc_range()
        snapshot_date = _today_local_date()
        today_parts: List[str] = []
        today_params: List[Any] = []
        if source in {"all", "github"}:
            today_parts.append(
                f"""
                SELECT COUNT(*) AS count
                FROM (
                    SELECT c_top.repo_id
                    FROM github_repo_candidates c_top
                    JOIN github_repo_enrichments ge_top ON ge_top.repo_id = c_top.repo_id
                    JOIN github_repo_daily_metrics gm_top
                      ON gm_top.repo_id = c_top.repo_id
                     AND gm_top.metric_date = %s
                     AND gm_top.daily_growth_available = 1
                     AND gm_top.daily_star_growth > 0
                    WHERE COALESCE(c_top.stars, 0) >= %s
                      {status_github.replace('ge.', 'ge_top.')}
                    ORDER BY gm_top.hot_score DESC,
                             gm_top.daily_star_growth DESC,
                             gm_top.stars DESC,
                             c_top.full_name ASC
                    LIMIT {GITHUB_PROJECT_TODAY_LIMIT}
                ) today_top
                JOIN github_repo_candidates c ON c.repo_id = today_top.repo_id
                JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                {github_user_join}
                WHERE 1 = 1
                  {github_user_filter}
                """
            )
            today_params.extend([snapshot_date, min_stars])
            if user_id:
                today_params.append(user_id)
        elif source == "website":
            today_parts.append(
                f"""
                SELECT COUNT(*) AS count
                FROM tool_websites w
                JOIN tool_website_enrichments we ON we.website_id = w.id
                {website_user_join}
                WHERE w.first_seen_at >= %s
                  AND w.first_seen_at < %s
                  {status_website}
                  {website_visibility_filter}
                  {website_user_filter}
                """
            )
            if user_id:
                today_params.extend([user_id, user_id])
            today_params.extend([today_start, tomorrow_start])
        today_sql = f"""
            WITH today_rows AS (
                {' UNION ALL '.join(today_parts) if today_parts else 'SELECT 0 AS count'}
            )
            SELECT COALESCE(SUM(count), 0) AS count FROM today_rows
        """

        recommended_sql = "SELECT 0 AS count"
        recommended_params: List[Any] = []
        if source in {"all", "github"}:
            recommended_sql = f"""
                SELECT COUNT(*) AS count
                FROM github_repo_candidates c
                JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                JOIN github_repo_recommendations gr
                  ON gr.repo_id = c.repo_id
                 AND gr.active = 1
                {github_user_join}
                WHERE COALESCE(c.stars, 0) >= %s
                  {status_github}
                  {github_user_filter}
            """
            if user_id:
                recommended_params.append(user_id)
            recommended_params.append(min_stars)

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                cur.execute(today_sql, tuple(today_params))
                today_row = cur.fetchone()
                cur.execute(recommended_sql, tuple(recommended_params))
                recommended_row = cur.fetchone()
            conn.commit()
        finally:
            conn.close()

        return _format_project_category_counts(
            list(rows),
            int(today_row.get("count") if today_row else 0),
            taxonomy=WEBSITE_TAXONOMY if source == "website" else PROJECT_TAXONOMY,
            recommended_count=int(recommended_row.get("count") if recommended_row else 0),
        )

    def list_user_project_collection(self, *, user_id: int, **kwargs: Any) -> Dict[str, Any]:
        return self.list_projects(user_id=user_id, favorites_only=True, **kwargs)

    def get_user_project_categories(
        self,
        *,
        user_id: int,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> Dict[str, Any]:
        return self.get_project_categories(
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
    ) -> Dict[str, Any]:
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

        counts: Dict[str, int] = {}
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
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {"items": items, "total": len(items), "source": source}

    def list_github_projects_for_semantic_sync(
        self,
        *,
        limit: int = 100,
        min_stars: int = 500,
        after_repo_id: str = "",
        retry_failed: bool = True,
    ) -> List[Dict[str, Any]]:
        stale_statuses = ("pending", "failed") if retry_failed else ("pending",)
        status_placeholders = ", ".join(["%s"] * len(stale_statuses))
        sql = f"""
            SELECT
                c.repo_id, c.full_name, c.title, c.url, c.description, c.language,
                c.topics_json, c.pushed_at, c.stars, c.forks,
                ge.description_zh, ge.category_slug, ge.category_name,
                ge.subcategory_slug, ge.subcategory_name, ge.tags_json,
                ss.readme_text, ss.readme_sha256, ss.readme_etag,
                ss.readme_status, ss.readme_checked_at, ss.readme_fetched_at,
                ss.readme_repo_pushed_at,
                ss.source_fingerprint, ss.indexed_fingerprint, ss.index_status,
                ss.index_retry_count
            FROM github_repo_candidates c
            JOIN github_repo_enrichments ge
              ON ge.repo_id = c.repo_id AND ge.status = 'succeeded'
            LEFT JOIN github_repo_aliases ga
              ON ga.alias_repo_id = c.repo_id AND ga.canonical_repo_id <> c.repo_id
            LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
            WHERE ga.alias_repo_id IS NULL
              AND COALESCE(c.stars, 0) >= %s
              AND c.repo_id > %s
              AND (
                    ss.repo_id IS NULL
                 OR ss.index_status IN ({status_placeholders})
                 OR COALESCE(ss.source_fingerprint, '') != COALESCE(ss.indexed_fingerprint, '')
                 OR COALESCE(ss.index_version, '') != %s
                 OR COALESCE(ss.readme_repo_pushed_at, '') < COALESCE(c.pushed_at, '')
              )
            ORDER BY c.repo_id ASC
            LIMIT %s
        """
        params: List[Any] = [
            min_stars,
            after_repo_id,
            *stale_statuses,
            settings.project_semantic_index_version,
            max(1, min(int(limit or 100), 1000)),
        ]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
            return [_normalize_github_project_row(row) for row in rows]
        finally:
            conn.close()

    def upsert_github_project_semantic_source(self, payload: Dict[str, Any]) -> None:
        now = _utcnow()
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
            "updated_at": now,
        }
        for key, value in defaults.items():
            data.setdefault(key, value)
        sql = """
            INSERT INTO github_project_semantic_sources (
                repo_id, readme_text, readme_sha256, readme_etag, readme_status,
                readme_checked_at, readme_fetched_at, readme_repo_pushed_at,
                readme_error, readme_retry_count, readme_next_retry_at,
                source_fingerprint, indexed_fingerprint, index_version,
                embedding_provider, embedding_model, embedding_dimension,
                chunk_count, index_status, index_error, index_retry_count,
                index_next_retry_at, indexed_at, updated_at
            ) VALUES (
                %(repo_id)s, %(readme_text)s, %(readme_sha256)s, %(readme_etag)s, %(readme_status)s,
                %(readme_checked_at)s, %(readme_fetched_at)s, %(readme_repo_pushed_at)s,
                %(readme_error)s, %(readme_retry_count)s, %(readme_next_retry_at)s,
                %(source_fingerprint)s, %(indexed_fingerprint)s, %(index_version)s,
                %(embedding_provider)s, %(embedding_model)s, %(embedding_dimension)s,
                %(chunk_count)s, %(index_status)s, %(index_error)s, %(index_retry_count)s,
                %(index_next_retry_at)s, %(indexed_at)s, %(updated_at)s
            )
            ON DUPLICATE KEY UPDATE
                readme_text=VALUES(readme_text),
                readme_sha256=VALUES(readme_sha256),
                readme_etag=VALUES(readme_etag),
                readme_status=VALUES(readme_status),
                readme_checked_at=VALUES(readme_checked_at),
                readme_fetched_at=VALUES(readme_fetched_at),
                readme_repo_pushed_at=VALUES(readme_repo_pushed_at),
                readme_error=VALUES(readme_error),
                readme_retry_count=VALUES(readme_retry_count),
                readme_next_retry_at=VALUES(readme_next_retry_at),
                source_fingerprint=VALUES(source_fingerprint),
                indexed_fingerprint=VALUES(indexed_fingerprint),
                index_version=VALUES(index_version),
                embedding_provider=VALUES(embedding_provider),
                embedding_model=VALUES(embedding_model),
                embedding_dimension=VALUES(embedding_dimension),
                chunk_count=VALUES(chunk_count),
                index_status=VALUES(index_status),
                index_error=VALUES(index_error),
                index_retry_count=VALUES(index_retry_count),
                index_next_retry_at=VALUES(index_next_retry_at),
                indexed_at=VALUES(indexed_at),
                updated_at=VALUES(updated_at)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                canonical_repo_id = self._resolve_github_repo_id_cur(cur, str(data.get("repo_id") or ""))
                data["repo_id"] = canonical_repo_id
                cur.execute(sql, data)
            conn.commit()
        finally:
            conn.close()

    def get_github_project_semantic_status(self, *, min_stars: int = 500) -> Dict[str, Any]:
        sql = """
            SELECT
                COUNT(*) AS eligible,
                SUM(CASE WHEN ss.index_status = 'succeeded' THEN 1 ELSE 0 END) AS indexed,
                SUM(CASE WHEN ss.index_status = 'failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN ss.readme_status = 'succeeded' THEN 1 ELSE 0 END) AS readme_succeeded,
                COALESCE(SUM(ss.chunk_count), 0) AS chunk_count,
                MAX(ss.indexed_at) AS last_indexed_at
            FROM github_repo_candidates c
            JOIN github_repo_enrichments ge
              ON ge.repo_id = c.repo_id AND ge.status = 'succeeded'
            LEFT JOIN github_repo_aliases ga
              ON ga.alias_repo_id = c.repo_id AND ga.canonical_repo_id <> c.repo_id
            LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id
            WHERE ga.alias_repo_id IS NULL
              AND COALESCE(c.stars, 0) >= %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (min_stars,))
                row = cur.fetchone() or {}
            conn.commit()
        finally:
            conn.close()
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

    def get_github_projects_needing_enrichment(
        self,
        *,
        limit: int = 50,
        min_stars: int = 500,
        prompt_version: str = "v1",
        force: bool = False,
        retry_failed: bool = True,
        refresh_changed: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return projects that should be AI-enriched.

        Daily enrichment is intentionally new-only by default: existing successful
        enrichments remain stable while normal ingestion only updates metrics such
        as stars/forks/snapshots. Use ``force`` or ``refresh_changed`` for manual
        re-curation when the taxonomy/prompt or repo metadata should be refreshed.
        """
        if force:
            stale_clause = "1 = 1"
            params: List[Any] = [min_stars]
        else:
            stale_parts = ["e.repo_id IS NULL"]
            params = [min_stars]
            if retry_failed:
                stale_parts.append("e.status != 'succeeded'")
            if refresh_changed:
                stale_parts.append("e.prompt_version != %s")
                params.append(prompt_version)
                stale_parts.append(
                    "e.source_fingerprint != SHA2(CONCAT_WS('\\n', c.full_name, COALESCE(c.description, ''), COALESCE(c.language, ''), COALESCE(c.topics_json, '')), 256)"
                )
            stale_clause = "(" + " OR ".join(stale_parts) + ")"
        params.append(max(1, min(int(limit or 50), 500)))

        sql = f"""
            WITH latest_snap AS (
                SELECT s.*
                FROM github_repo_snapshots s
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) t
                  ON s.repo_id = t.repo_id AND s.snapshot_date = t.snapshot_date
            )
            SELECT
                c.repo_id,
                c.full_name,
                c.title,
                c.url,
                c.description,
                c.language,
                c.topics_json,
                c.created_at,
                c.pushed_at,
                c.source_channels,
                c.first_seen_at,
                c.last_seen_at,
                c.last_snapshot_at,
                COALESCE(ls.stars, c.stars, 0) AS stars,
                COALESCE(ls.forks, c.forks, 0) AS forks,
                COALESCE(ls.watchers, c.watchers, 0) AS watchers,
                COALESCE(ls.open_issues, 0) AS open_issues,
                ls.snapshot_date,
                ls.captured_at,
                SHA2(CONCAT_WS('\n', c.full_name, COALESCE(c.description, ''), COALESCE(c.language, ''), COALESCE(c.topics_json, '')), 256) AS source_fingerprint
            FROM github_repo_candidates c
            LEFT JOIN latest_snap ls ON ls.repo_id = c.repo_id
            LEFT JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
            WHERE COALESCE(ls.stars, c.stars, 0) >= %s
              AND {stale_clause}
            ORDER BY COALESCE(ls.stars, c.stars, 0) DESC, c.full_name ASC
            LIMIT %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()
            return [_normalize_github_project_row(row) for row in rows]
        finally:
            conn.close()

    def upsert_github_repo_enrichment(self, payload: Dict[str, Any]) -> None:
        now = _utcnow()
        data = dict(payload)
        data.setdefault("tags_json", _json_dumps(data.get("tags") or []))
        data["subcategory_slug"] = data.get("subcategory_slug") or ""
        data["subcategory_name"] = data.get("subcategory_name") or ""
        data.setdefault("confidence", 0.0)
        data.setdefault("model_provider", "")
        data.setdefault("model_name", "")
        data.setdefault("status", "succeeded")
        data.setdefault("error_msg", None)
        data.setdefault("enriched_at", now)
        data.setdefault("updated_at", now)
        sql = """
            INSERT INTO github_repo_enrichments (
                repo_id, category_slug, category_name, subcategory_slug, subcategory_name, description_zh, tags_json,
                confidence, source_fingerprint, prompt_version, model_provider, model_name,
                status, error_msg, enriched_at, updated_at
            ) VALUES (
                %(repo_id)s, %(category_slug)s, %(category_name)s, %(subcategory_slug)s, %(subcategory_name)s, %(description_zh)s, %(tags_json)s,
                %(confidence)s, %(source_fingerprint)s, %(prompt_version)s, %(model_provider)s, %(model_name)s,
                %(status)s, %(error_msg)s, %(enriched_at)s, %(updated_at)s
            )
            ON DUPLICATE KEY UPDATE
                category_slug=VALUES(category_slug),
                category_name=VALUES(category_name),
                subcategory_slug=VALUES(subcategory_slug),
                subcategory_name=VALUES(subcategory_name),
                description_zh=VALUES(description_zh),
                tags_json=VALUES(tags_json),
                confidence=VALUES(confidence),
                source_fingerprint=VALUES(source_fingerprint),
                prompt_version=VALUES(prompt_version),
                model_provider=VALUES(model_provider),
                model_name=VALUES(model_name),
                status=VALUES(status),
                error_msg=VALUES(error_msg),
                enriched_at=VALUES(enriched_at),
                updated_at=VALUES(updated_at)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, data)
            conn.commit()
        finally:
            conn.close()

    def mark_github_repo_enrichment_failed(
        self,
        repo_id: str,
        *,
        source_fingerprint: str,
        prompt_version: str,
        error_msg: str,
        model_provider: str = "",
        model_name: str = "",
    ) -> None:
        self.upsert_github_repo_enrichment(
            {
                "repo_id": repo_id,
                "category_slug": "other",
                "category_name": "其他",
                "subcategory_slug": "other_uncategorized",
                "subcategory_name": "未分类",
                "description_zh": "",
                "tags_json": "[]",
                "confidence": 0.0,
                "source_fingerprint": source_fingerprint,
                "prompt_version": prompt_version,
                "model_provider": model_provider,
                "model_name": model_name,
                "status": "failed",
                "error_msg": error_msg[:2000],
            }
        )

    def get_github_project_enrichment_status(self, *, min_stars: int = 500) -> Dict[str, Any]:
        base_sql = """
            WITH latest_snap AS (
                SELECT s.*
                FROM github_repo_snapshots s
                JOIN (
                    SELECT repo_id, MAX(snapshot_date) AS snapshot_date
                    FROM github_repo_snapshots
                    GROUP BY repo_id
                ) t
                  ON s.repo_id = t.repo_id AND s.snapshot_date = t.snapshot_date
            ), eligible AS (
                SELECT c.repo_id, e.status, e.category_slug, e.category_name
                FROM github_repo_candidates c
                LEFT JOIN latest_snap ls ON ls.repo_id = c.repo_id
                LEFT JOIN github_repo_enrichments e ON e.repo_id = c.repo_id
                WHERE COALESCE(ls.stars, c.stars, 0) >= %s
            )
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    {base_sql}
                    SELECT
                        COUNT(*) AS eligible,
                        SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                    FROM eligible
                    """,
                    (min_stars,),
                )
                row = cur.fetchone() or {}
                cur.execute(
                    f"""
                    {base_sql}
                    SELECT category_slug AS slug, category_name AS name, COUNT(*) AS count
                    FROM eligible
                    WHERE status = 'succeeded'
                    GROUP BY category_slug, category_name
                    ORDER BY count DESC, category_name ASC
                    """,
                    (min_stars,),
                )
                categories = cur.fetchall()
            conn.commit()
        finally:
            conn.close()

        eligible = int(row.get("eligible") or 0)
        succeeded = int(row.get("succeeded") or 0)
        failed = int(row.get("failed") or 0)
        return {
            "eligible": eligible,
            "succeeded": succeeded,
            "failed": failed,
            "pending": max(eligible - succeeded - failed, 0),
            "by_category": [
                {
                    "slug": item.get("slug") or "other",
                    "name": item.get("name") or "其他",
                    "count": int(item.get("count") or 0),
                }
                for item in categories
            ],
        }

    # ------------------------------------------------------------------
    # Ingestion tasks
    # ------------------------------------------------------------------

    def create_task(self, task_name: str) -> int:
        return self.ingestion_tasks.create_task(task_name)

    def finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: Optional[str] = None,
        item_count: int = 0,
    ) -> None:
        self.ingestion_tasks.finish_task(
            task_id,
            status=status,
            error_msg=error_msg,
            item_count=item_count,
        )

    def get_latest_task(self) -> Optional[Dict[str, Any]]:
        return self.ingestion_tasks.get_latest_task()

    def get_recent_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.ingestion_tasks.get_recent_tasks(limit)

    def list_tasks(self, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        return self.ingestion_tasks.list_tasks(page, page_size)

    def clear_all_tasks(self) -> int:
        return self.ingestion_tasks.clear_all_tasks()

    # ------------------------------------------------------------------
    # Briefings
    # ------------------------------------------------------------------

    def save_briefing(self, date_str: str, content: str) -> int:
        return self.briefings.save_briefing(date_str, content)

    def get_latest_briefing(self) -> Optional[Dict[str, Any]]:
        return self.briefings.get_latest_briefing()

    def get_briefing_by_date(self, date_str: str) -> Optional[Dict[str, Any]]:
        return self.briefings.get_briefing_by_date(date_str)

    def list_briefings(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self.briefings.list_briefings(limit)

    # ------------------------------------------------------------------
    # Runtime Provider Settings
    # ------------------------------------------------------------------

    def get_runtime_provider_setting(self, provider: str = "") -> Optional[Dict[str, Any]]:
        provider_key = (provider or "").strip().lower()
        where_clause = "WHERE provider = %s" if provider_key else ""
        params = (provider_key,) if provider_key else ()

        sql = f"""
            SELECT provider, base_url, api_key, model_name, updated_at
            FROM runtime_provider_settings
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT 1
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_runtime_provider_setting(
        self,
        provider: str,
        base_url: str = "",
        api_key: Optional[str] = None,
        clear_api_key: bool = False,
        model_name: str = "",
    ) -> Dict[str, Any]:
        provider_key = (provider or "").strip().lower()
        clean_base_url = (base_url or "").strip()
        clean_api_key = api_key.strip() if isinstance(api_key, str) else None
        clean_model_name = (model_name or "").strip()

        existing = self.get_runtime_provider_setting()
        if clear_api_key:
            effective_api_key: Optional[str] = None
        elif clean_api_key:
            effective_api_key = clean_api_key
        else:
            effective_api_key = existing.get("api_key") if existing else None

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM runtime_provider_settings")
                cur.execute(
                    """
                    INSERT INTO runtime_provider_settings
                        (provider, base_url, api_key, model_name, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    """,
                    (provider_key, clean_base_url, effective_api_key, clean_model_name),
                )
            conn.commit()
        finally:
            conn.close()

        return self.get_runtime_provider_setting() or {
            "provider": provider_key,
            "base_url": clean_base_url,
            "api_key": effective_api_key,
            "model_name": clean_model_name,
        }

    # ------------------------------------------------------------------
    # MCP Server Settings
    # ------------------------------------------------------------------

    def _seed_default_mcp_server_configs(self) -> None:
        self.mcp_server_configs._seed_default_mcp_server_configs()

    def list_mcp_server_configs(self) -> List[Dict[str, Any]]:
        return self.mcp_server_configs.list_mcp_server_configs()

    def get_mcp_server_config(self, server_id: int) -> Optional[Dict[str, Any]]:
        return self.mcp_server_configs.get_mcp_server_config(server_id)

    def create_mcp_server_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.mcp_server_configs.create_mcp_server_config(payload)

    def update_mcp_server_config(
        self,
        server_id: int,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self.mcp_server_configs.update_mcp_server_config(server_id, payload)

    def delete_mcp_server_config(self, server_id: int) -> bool:
        return self.mcp_server_configs.delete_mcp_server_config(server_id)

    def update_mcp_server_test_result(
        self,
        server_id: int,
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self.mcp_server_configs.update_mcp_server_test_result(
            server_id,
            result,
        )

    # ------------------------------------------------------------------
    # Briefing Subscriptions
    # ------------------------------------------------------------------

    def upsert_briefing_subscription(
        self, user_id: int, email: str, source: str = "all", period: str = "daily"
    ) -> Dict[str, Any]:
        return self.briefing_subscriptions.upsert_briefing_subscription(
            user_id,
            email,
            source,
            period,
        )

    def cancel_briefing_subscription(
        self, user_id: int, source: str = "all", period: str = "daily"
    ) -> bool:
        return self.briefing_subscriptions.cancel_briefing_subscription(
            user_id,
            source,
            period,
        )

    def get_user_briefing_subscriptions(self, user_id: int) -> List[Dict[str, Any]]:
        return self.briefing_subscriptions.get_user_briefing_subscriptions(user_id)

    def get_active_subscribers(
        self, source: str = "all", period: str = "daily"
    ) -> List[Dict[str, Any]]:
        return self.briefing_subscriptions.get_active_subscribers(source, period)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def save_evaluation(
        self,
        *,
        query: str,
        answer: str,
        sources: List[Dict[str, Any]],
        recall_score: float,
        citation_score: float,
        subjective_score: float,
    ) -> int:
        return self.evaluations.save_evaluation(
            query=query,
            answer=answer,
            sources=sources,
            recall_score=recall_score,
            citation_score=citation_score,
            subjective_score=subjective_score,
        )

    def get_eval_summary(self) -> Dict[str, Any]:
        return self.evaluations.get_eval_summary()

    def list_evaluations(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.evaluations.list_evaluations(limit)

    # ------------------------------------------------------------------
    # Inbound MCP access tokens
    # ------------------------------------------------------------------

    def create_user_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        scopes: List[str],
        client_type: str,
        client_label: str = "",
        expires_at: Any = None,
    ) -> Dict[str, Any]:
        return self.mcp_access_tokens.create_user_mcp_token(
            user_id=user_id,
            token_hash=token_hash,
            token_hint=token_hint,
            scopes=scopes,
            client_type=client_type,
            client_label=client_label,
            expires_at=expires_at,
        )

    def list_user_mcp_tokens(self, *, user_id: int) -> List[Dict[str, Any]]:
        return self.mcp_access_tokens.list_user_mcp_tokens(user_id=user_id)

    def get_user_by_mcp_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        return self.mcp_access_tokens.get_user_by_mcp_token_hash(token_hash)

    def delete_user_mcp_token(self, *, user_id: int, token_id: int) -> bool:
        return self.mcp_access_tokens.delete_user_mcp_token(
            user_id=user_id,
            token_id=token_id,
        )

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        return self.user_accounts.get_user_by_phone(phone)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """按邮箱查询用户（邮箱不区分大小写）。"""
        return self.user_accounts.get_user_by_email(email)

    def create_user(
        self,
        phone: str,
        username: str,
        hashed_password: str,
        role: str = "user",
    ) -> int:
        return self.user_accounts.create_user(
            phone,
            username,
            hashed_password,
            role,
        )

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int:
        """更新精确匹配用户的密码哈希，返回受影响行数。"""
        return self.user_accounts.update_user_password(
            user_id=user_id,
            email=email,
            hashed_password=hashed_password,
        )

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        invite_code_used: str = "",
        role: str = "user",
        username: str = "",
    ) -> int:
        """使用邮箱创建新用户（Phase 4 邮箱注册流程）。"""
        return self.user_accounts.create_user_with_email(
            email,
            hashed_password,
            invite_code_used,
            role,
            username,
        )

    # ------------------------------------------------------------------
    # Conversation / Chat history
    # ------------------------------------------------------------------

    def get_or_create_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if scope_key:
                    cur.execute(
                        """
                        SELECT * FROM conversations
                        WHERE user_id = %s AND scope = %s AND scope_key = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (user_id, scope, scope_key),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM conversations
                        WHERE user_id = %s AND scope = %s AND scope_key IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (user_id, scope),
                    )
                row = cur.fetchone()
                if row:
                    conversation = dict(row)
                else:
                    cur.execute(
                        """
                        INSERT INTO conversations (
                            user_id, scope, scope_key, title, last_message_preview,
                            message_count, last_accessed_at, updated_at, created_at
                        ) VALUES (%s, %s, %s, %s, '', 0, NOW(), NOW(), NOW())
                        """,
                        (user_id, scope, scope_key, title or "新对话"),
                    )
                    conversation_id = cur.lastrowid
                    cur.execute(
                        "SELECT * FROM conversations WHERE id = %s", (conversation_id,)
                    )
                    conversation = dict(cur.fetchone())
            conn.commit()
            return conversation
        finally:
            conn.close()

    def create_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """强制创建新会话（不复用已有会话）。"""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (
                        user_id, scope, scope_key, title, last_message_preview,
                        message_count, last_accessed_at, updated_at, created_at
                    ) VALUES (%s, %s, %s, %s, '', 0, NOW(), NOW(), NOW())
                    """,
                    (user_id, scope, scope_key, title or "新对话"),
                )
                conversation_id = cur.lastrowid
                cur.execute(
                    "SELECT * FROM conversations WHERE id = %s", (conversation_id,)
                )
                conversation = dict(cur.fetchone())
            conn.commit()
            return conversation
        finally:
            conn.close()

    def delete_conversation_by_id(
        self,
        conversation_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除指定会话及其所有消息（CASCADE 由外键自动处理，
        但为保险起见先手动删消息）。"""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # 权限校验
                if user_id is not None:
                    cur.execute(
                        "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
                        (conversation_id, user_id),
                    )
                    if cur.fetchone() is None:
                        return False
                # 先删消息
                cur.execute(
                    "DELETE FROM chat_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                # 再删会话
                cur.execute(
                    "DELETE FROM conversations WHERE id = %s", (conversation_id,)
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_conversation_by_id(
        self,
        conversation_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if user_id is None:
                    cur.execute(
                        "SELECT * FROM conversations WHERE id = %s", (conversation_id,)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM conversations WHERE id = %s AND user_id = %s",
                        (conversation_id, user_id),
                    )
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_conversations(
        self,
        *,
        user_id: int,
        scope: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        where = ["user_id = %s"]
        params: List[Any] = [user_id]
        if scope:
            where.append("scope = %s")
            params.append(scope)
        where_clause = " AND ".join(where)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS cnt FROM conversations WHERE {where_clause}",
                    tuple(params),
                )
                total_row = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT * FROM conversations
                    WHERE {where_clause}
                    ORDER BY last_accessed_at DESC, updated_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params + [page_size, offset]),
                )
                rows = cur.fetchall()
            conn.commit()
            return {
                "items": list(rows),
                "total": int(total_row["cnt"] if total_row else 0),
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    def touch_conversation(self, conversation_id: int) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET last_accessed_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )
            conn.commit()
        finally:
            conn.close()

    def refresh_conversation_stats(
        self,
        conversation_id: int,
        *,
        title: Optional[str] = None,
        last_message_preview: Optional[str] = None,
    ) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM chat_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                count_row = cur.fetchone()
                message_count = int(count_row["cnt"] if count_row else 0)
                if last_message_preview is None:
                    cur.execute(
                        """
                        SELECT content FROM chat_messages
                        WHERE conversation_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """,
                        (conversation_id,),
                    )
                    latest = cur.fetchone()
                    last_message_preview = (
                        (latest.get("content") or "")[:200] if latest else ""
                    )
                if title is None:
                    cur.execute(
                        """
                        SELECT content FROM chat_messages
                        WHERE conversation_id = %s AND role = 'user'
                        ORDER BY created_at ASC, id ASC
                        LIMIT 1
                        """,
                        (conversation_id,),
                    )
                    first_user = cur.fetchone()
                    if first_user:
                        title = (first_user.get("content") or "新对话")[:60]
                cur.execute(
                    """
                    UPDATE conversations
                    SET title = COALESCE(%s, title),
                        last_message_preview = %s,
                        message_count = %s,
                        last_accessed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (title, last_message_preview or "", message_count, conversation_id),
                )
            conn.commit()
        finally:
            conn.close()

    def create_chat_message(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        thinking: str = "",
        sources: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        status: str = "done",
        parent_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (
                        conversation_id, role, content, thinking, sources_json,
                        attachments_json, status, parent_message_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (
                        conversation_id,
                        role,
                        content,
                        thinking,
                        _json_dumps(sources),
                        _json_dumps(attachments),
                        status,
                        parent_message_id,
                    ),
                )
                message_id = cur.lastrowid
                cur.execute("SELECT * FROM chat_messages WHERE id = %s", (message_id,))
                row = cur.fetchone()
            conn.commit()
            return self._deserialize_message(dict(row))
        finally:
            conn.close()

    def list_chat_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM chat_messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (conversation_id,),
                )
                rows = cur.fetchall()
            conn.commit()
            return [self._deserialize_message(dict(row)) for row in rows]
        finally:
            conn.close()

    def get_chat_message(
        self,
        message_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if user_id is None:
                    cur.execute(
                        "SELECT * FROM chat_messages WHERE id = %s", (message_id,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT m.*
                        FROM chat_messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE m.id = %s AND c.user_id = %s
                        """,
                        (message_id, user_id),
                    )
                row = cur.fetchone()
            conn.commit()
            return self._deserialize_message(dict(row)) if row else None
        finally:
            conn.close()

    def delete_message_branch(self, message_id: int) -> List[int]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, conversation_id FROM chat_messages WHERE id = %s",
                    (message_id,),
                )
                row = cur.fetchone()
                if not row:
                    return []
                conversation_id = int(row["conversation_id"])
                cur.execute(
                    "SELECT id, role FROM chat_messages WHERE conversation_id = %s ORDER BY created_at ASC, id ASC",
                    (conversation_id,),
                )
                rows = cur.fetchall()
                ids = [int(item["id"]) for item in rows]
                try:
                    start_idx = ids.index(int(message_id))
                except ValueError:
                    return []
                delete_ids = ids[start_idx:]
                placeholders = ", ".join(["%s"] * len(delete_ids))
                cur.execute(
                    f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
                    tuple(delete_ids),
                )
            conn.commit()
            return delete_ids
        finally:
            conn.close()

    def delete_messages_after(self, message_id: int) -> List[int]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, conversation_id, created_at FROM chat_messages WHERE id = %s",
                    (message_id,),
                )
                row = cur.fetchone()
                if not row:
                    return []
                conversation_id = int(row["conversation_id"])
                created_at = row["created_at"]
                cur.execute(
                    """
                    SELECT id FROM chat_messages
                    WHERE conversation_id = %s
                      AND (created_at > %s OR (created_at = %s AND id >= %s))
                    ORDER BY created_at ASC, id ASC
                    """,
                    (conversation_id, created_at, created_at, message_id),
                )
                rows = cur.fetchall()
                delete_ids = [int(item["id"]) for item in rows]
                if delete_ids:
                    placeholders = ", ".join(["%s"] * len(delete_ids))
                    cur.execute(
                        f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
                        tuple(delete_ids),
                    )
            conn.commit()
            return delete_ids
        finally:
            conn.close()

    def trim_conversation_messages(
        self, *, conversation_id: int, keep_latest: int = 10
    ) -> int:
        if keep_latest <= 0:
            return 0
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM chat_messages WHERE conversation_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
                    (conversation_id, keep_latest),
                )
                keep_rows = cur.fetchall()
                keep_ids = [int(row["id"]) for row in keep_rows]
                if keep_ids:
                    placeholders = ", ".join(["%s"] * len(keep_ids))
                    cur.execute(
                        f"DELETE FROM chat_messages WHERE conversation_id = %s AND id NOT IN ({placeholders})",
                        tuple([conversation_id] + keep_ids),
                    )
                else:
                    cur.execute(
                        "DELETE FROM chat_messages WHERE conversation_id = %s",
                        (conversation_id,),
                    )
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def trim_user_conversations(self, *, user_id: int, keep_latest: int = 10) -> int:
        if keep_latest <= 0:
            return 0
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM conversations WHERE user_id = %s ORDER BY last_accessed_at DESC, updated_at DESC, id DESC LIMIT %s",
                    (user_id, keep_latest),
                )
                keep_rows = cur.fetchall()
                keep_ids = [int(row["id"]) for row in keep_rows]
                if keep_ids:
                    placeholders = ", ".join(["%s"] * len(keep_ids))
                    cur.execute(
                        f"DELETE FROM conversations WHERE user_id = %s AND id NOT IN ({placeholders})",
                        tuple([user_id] + keep_ids),
                    )
                else:
                    cur.execute(
                        "DELETE FROM conversations WHERE user_id = %s", (user_id,)
                    )
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def cleanup_stale_conversations(
        self, *, stale_days: int = 7, limit: int = 5
    ) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM conversations
                    WHERE last_accessed_at < DATE_SUB(NOW(), INTERVAL %s DAY)
                    ORDER BY last_accessed_at ASC, updated_at ASC, id ASC
                    LIMIT %s
                    """,
                    (stale_days, limit),
                )
                rows = cur.fetchall()
                delete_ids = [int(row["id"]) for row in rows]
                if not delete_ids:
                    conn.commit()
                    return 0
                placeholders = ", ".join(["%s"] * len(delete_ids))
                cur.execute(
                    f"DELETE FROM conversations WHERE id IN ({placeholders})",
                    tuple(delete_ids),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def create_chat_attachment(
        self,
        *,
        user_id: int,
        conversation_id: Optional[int],
        file_name: str,
        mime_type: str,
        modality: str,
        storage_path: Optional[str] = None,
        file_size: int = 0,
        page_count: Optional[int] = None,
        parse_status: str = "uploaded",
        extract_text: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_attachments (
                        user_id, conversation_id, file_name, mime_type, modality,
                        storage_path, file_size, page_count, parse_status,
                        extract_text, meta_json, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (
                        user_id,
                        conversation_id,
                        file_name,
                        mime_type,
                        modality,
                        storage_path,
                        file_size,
                        page_count,
                        parse_status,
                        extract_text,
                        _json_dumps(meta or {}),
                    ),
                )
                attachment_id = cur.lastrowid
                cur.execute(
                    "SELECT * FROM chat_attachments WHERE id = %s", (attachment_id,)
                )
                row = cur.fetchone()
            conn.commit()
            return self._deserialize_attachment(dict(row))
        finally:
            conn.close()

    def get_chat_attachment(
        self,
        attachment_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if user_id is None:
                    cur.execute(
                        "SELECT * FROM chat_attachments WHERE id = %s", (attachment_id,)
                    )
                else:
                    cur.execute(
                        "SELECT * FROM chat_attachments WHERE id = %s AND user_id = %s",
                        (attachment_id, user_id),
                    )
                row = cur.fetchone()
            conn.commit()
            return self._deserialize_attachment(dict(row)) if row else None
        finally:
            conn.close()

    def list_chat_attachments(
        self,
        *,
        user_id: int,
        conversation_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if conversation_id is None:
                    cur.execute(
                        "SELECT * FROM chat_attachments WHERE user_id = %s ORDER BY created_at DESC, id DESC",
                        (user_id,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM chat_attachments WHERE user_id = %s AND conversation_id = %s ORDER BY created_at DESC, id DESC",
                        (user_id, conversation_id),
                    )
                rows = cur.fetchall()
            conn.commit()
            return [self._deserialize_attachment(dict(row)) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _deserialize_message(row: Dict[str, Any]) -> Dict[str, Any]:
        row["sources"] = json.loads(row.get("sources_json") or "[]")
        row["attachments"] = json.loads(row.get("attachments_json") or "[]")
        row["thinking_preview"] = (row.get("thinking") or "")[:80]
        row["has_thinking"] = bool(row.get("thinking"))
        row["is_thinking"] = False
        row["is_streaming"] = row.get("status") == "streaming"
        return row

    @staticmethod
    def _deserialize_attachment(row: Dict[str, Any]) -> Dict[str, Any]:
        row["meta"] = json.loads(row.get("meta_json") or "{}")
        return row
