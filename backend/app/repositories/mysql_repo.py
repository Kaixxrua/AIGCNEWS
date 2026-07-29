from __future__ import annotations

import json
import logging
import re
import uuid
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
from backend.app.repositories.mysql_conversation_repository import (
    MySQLConversationRepository,
)
from backend.app.repositories.mysql_document_repository import MySQLDocumentRepository
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
from backend.app.repositories.mysql_project_write_repository import (
    MySQLProjectWriteRepository,
)
from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
    ProjectLexicalRetrievalPlan,
)
from backend.app.repositories.mysql_rank_snapshot_repository import (
    MySQLRankSnapshotRepository,
)
from backend.app.repositories.mysql_runtime_provider_repository import (
    MySQLRuntimeProviderSettingRepository,
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
    item["availability_status"] = (
        "not_found" if item.get("availability_status") == "not_found" else "active"
    )
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
    item["availability_status"] = (
        "not_found" if item.get("availability_status") == "not_found" else "active"
    )
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
        self._conversations: MySQLConversationRepository | None = None
        self._documents: MySQLDocumentRepository | None = None
        self._rank_snapshots: MySQLRankSnapshotRepository | None = None
        self._evaluations: MySQLEvaluationRepository | None = None
        self._mcp_server_configs: MySQLMcpServerConfigRepository | None = None
        self._mcp_access_tokens: MySQLMcpAccessTokenRepository | None = None
        self._user_accounts: MySQLUserAccountRepository | None = None
        self._runtime_provider_settings: MySQLRuntimeProviderSettingRepository | None = None
        self._project_writes: MySQLProjectWriteRepository | None = None
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

    @staticmethod
    def _record_project_catalog_change_cur(
        cur: Any,
        *,
        aggregate_type: str,
        aggregate_key: dict[str, Any],
        operation: str = "reconcile",
        source_method: str,
    ) -> None:
        if not bool(getattr(settings, "project_catalog_outbox_capture_enabled", False)):
            return
        key_json = json.dumps(
            aggregate_key,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        cur.execute(
            """
            INSERT INTO project_catalog_outbox (
                event_id, aggregate_type, aggregate_key, operation, source_method
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                aggregate_type,
                key_json,
                operation,
                source_method,
            ),
        )

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
    def conversations(self) -> MySQLConversationRepository:
        if self._conversations is None:
            self._conversations = MySQLConversationRepository(self._database)
        return self._conversations

    @property
    def documents(self) -> MySQLDocumentRepository:
        if self._documents is None:
            self._documents = MySQLDocumentRepository(self._database)
        return self._documents

    @property
    def rank_snapshots(self) -> MySQLRankSnapshotRepository:
        if self._rank_snapshots is None:
            self._rank_snapshots = MySQLRankSnapshotRepository(self._database)
        return self._rank_snapshots

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

    @property
    def runtime_provider_settings(self) -> MySQLRuntimeProviderSettingRepository:
        if self._runtime_provider_settings is None:
            self._runtime_provider_settings = MySQLRuntimeProviderSettingRepository(
                self._database
            )
        return self._runtime_provider_settings

    @property
    def project_writes(self) -> MySQLProjectWriteRepository:
        project_writes = getattr(self, "_project_writes", None)
        if project_writes is None:
            project_writes = MySQLProjectWriteRepository(getattr(self, "_database", None))
            self._project_writes = project_writes
        return project_writes

    def _project_write_delegate(self) -> MySQLProjectWriteRepository:
        adapter = self.project_writes
        adapter._connect = self._connect
        resolve_override = self.__dict__.get("_resolve_github_repo_id_cur")
        if resolve_override is not None:
            adapter._resolve_github_repo_id_cur = resolve_override
        alias_override = self.__dict__.get("_upsert_github_repo_alias_cur")
        if alias_override is not None:
            adapter._upsert_github_repo_alias_cur = alias_override
        return adapter

    def resolve_github_repo_id(self, repo_id: str = "", full_name: str = "") -> str:
        return self._project_write_delegate().resolve_github_repo_id(repo_id, full_name)

    def _resolve_github_repo_id_cur(self, cur, repo_id: str = "", full_name: str = "") -> str:
        return self._project_write_delegate()._resolve_github_repo_id_cur(cur, repo_id, full_name)

    def _upsert_github_repo_alias_cur(
        self, cur, *, alias_repo_id: str, canonical_repo_id: str, full_name: str
    ) -> None:
        self._project_write_delegate()._upsert_github_repo_alias_cur(
            cur,
            alias_repo_id=alias_repo_id,
            canonical_repo_id=canonical_repo_id,
            full_name=full_name,
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
                availability_status VARCHAR(32) NOT NULL DEFAULT 'active',
                not_found_count INT NOT NULL DEFAULT 0,
                availability_checked_at VARCHAR(64),
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
                    "ALTER TABLE github_repo_candidates ADD COLUMN availability_status VARCHAR(32) NOT NULL DEFAULT 'active' AFTER last_snapshot_at",
                    "ALTER TABLE github_repo_candidates ADD COLUMN not_found_count INT NOT NULL DEFAULT 0 AFTER availability_status",
                    "ALTER TABLE github_repo_candidates ADD COLUMN availability_checked_at VARCHAR(64) NULL AFTER not_found_count",
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
        return self.documents.upsert_document(doc)

    def update_document_pdf_path(self, doc_id: str, local_pdf_path: str) -> None:
        return self.documents.update_document_pdf_path(doc_id, local_pdf_path)

    def get_user_count(self) -> int:
        """返回已注册用户总数。"""
        return self.user_accounts.get_user_count()

    def get_today_registered_user_count(self) -> int:
        """返回今日注册用户数（CST）。"""
        return self.user_accounts.get_today_registered_user_count()

    def count_user_messages_today(self, user_id: int) -> int:
        return self.conversations.count_user_messages_today(user_id)

    def clear_all_documents(self) -> int:
        return self.documents.clear_all_documents()

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
        return self.rank_snapshots.upsert_rank_snapshot(
            doc_id,
            snapshot_date,
            source_channel,
            rank_in_period,
            raw_score,
            score,
        )

    def get_snapshot_documents(
        self,
        snapshot_date: str,
        source_channel: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        return self.rank_snapshots.get_snapshot_documents(
            snapshot_date,
            source_channel,
            source_type,
            limit,
        )

    def get_snapshot_dates(
        self,
        limit: int = 60,
        source: Optional[str] = None,
        period: Optional[str] = None,
    ) -> List[str]:
        return self.rank_snapshots.get_snapshot_dates(limit, source, period)

    def get_snapshot_source_counts(self, snapshot_date: str) -> Dict[str, int]:
        return self.rank_snapshots.get_snapshot_source_counts(snapshot_date)

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: Optional[str] = None,
    ) -> Set[str]:
        return self.rank_snapshots.get_snapshot_doc_ids(snapshot_date, source_channel)

    def delete_snapshots_by_channel(
        self, snapshot_date: str, source_channel: str
    ) -> int:
        return self.rank_snapshots.delete_snapshots_by_channel(
            snapshot_date,
            source_channel,
        )

    # ------------------------------------------------------------------
    # GitHub hotness
    # ------------------------------------------------------------------

    def upsert_github_repo_candidate(self, repo: Dict[str, Any]) -> None:
        self._project_write_delegate().upsert_github_repo_candidate(repo)

    def mark_github_repo_available(self, full_name: str, *, checked_at: str) -> bool:
        return self._project_write_delegate().mark_github_repo_available(full_name, checked_at=checked_at)

    def record_github_repo_not_found(self, full_name: str, *, checked_at: str) -> bool:
        return self._project_write_delegate().record_github_repo_not_found(full_name, checked_at=checked_at)

    def ensure_github_repo_candidate(self, repo: Dict[str, Any]) -> str:
        return self._project_write_delegate().ensure_github_repo_candidate(repo)

    def insert_github_repo_snapshot(self, snapshot: Dict[str, Any]) -> None:
        self._project_write_delegate().insert_github_repo_snapshot(snapshot)

    def upsert_github_trending_hit(self, hit: Dict[str, Any]) -> str:
        return self._project_write_delegate().upsert_github_trending_hit(hit)

    def get_github_hot_repos(
        self, period: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        return self._project_write_delegate().get_github_hot_repos(period, limit)

    def get_github_snapshot_count(self) -> int:
        return self._project_write_delegate().get_github_snapshot_count()

    def list_github_project_metric_targets(
        self, *, min_stars: int = 500, limit: int = 0
    ) -> List[Dict[str, Any]]:
        return self._project_write_delegate().list_github_project_metric_targets(
            min_stars=min_stars, limit=limit
        )

    def get_github_metric_refresh_status(
        self, *, metric_date: str, min_stars: int = 500, limit: int = 0
    ) -> Dict[str, Any]:
        return self._project_write_delegate().get_github_metric_refresh_status(
            metric_date=metric_date, min_stars=min_stars, limit=limit
        )

    def get_github_daily_metric_inputs(
        self,
        *,
        metric_date: str,
        previous_date: str,
        baseline_start_date: str,
        min_stars: int = 500,
        repo_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return self._project_write_delegate().get_github_daily_metric_inputs(
            metric_date=metric_date,
            previous_date=previous_date,
            baseline_start_date=baseline_start_date,
            min_stars=min_stars,
            repo_ids=repo_ids,
        )

    def upsert_github_daily_metrics(self, metrics: List[Dict[str, Any]]) -> int:
        return self._project_write_delegate().upsert_github_daily_metrics(metrics)

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
                if row.get("id") is not None:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="tool_websites",
                        aggregate_key={"id": int(row["id"])},
                        source_method="upsert_tool_website",
                    )
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
                    """
                    SELECT user_id, project_source, project_id
                    FROM project_favorites
                    WHERE project_source = 'website' AND project_id = %s
                    FOR UPDATE
                    """,
                    (str(website_id),),
                )
                favorites = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT user_id, website_id
                    FROM user_tool_websites
                    WHERE website_id = %s
                    FOR UPDATE
                    """,
                    (website_id,),
                )
                links = list(cur.fetchall())
                cur.execute(
                    """
                    SELECT user_id, website_id
                    FROM user_tool_website_overrides
                    WHERE website_id = %s
                    FOR UPDATE
                    """,
                    (website_id,),
                )
                overrides = list(cur.fetchall())
                cur.execute(
                    "SELECT website_id FROM tool_website_enrichments WHERE website_id = %s FOR UPDATE",
                    (website_id,),
                )
                enrichment = cur.fetchone()
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
                for favorite in favorites:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="project_favorites",
                        aggregate_key={
                            "user_id": int(favorite["user_id"]),
                            "project_source": str(favorite["project_source"]),
                            "project_id": str(favorite["project_id"]),
                        },
                        operation="delete",
                        source_method="delete_tool_website",
                    )
                for override in overrides:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="user_tool_website_overrides",
                        aggregate_key={
                            "user_id": int(override["user_id"]),
                            "website_id": int(override["website_id"]),
                        },
                        operation="delete",
                        source_method="delete_tool_website",
                    )
                for link in links:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="user_tool_websites",
                        aggregate_key={
                            "user_id": int(link["user_id"]),
                            "website_id": int(link["website_id"]),
                        },
                        operation="delete",
                        source_method="delete_tool_website",
                    )
                if enrichment:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="tool_website_enrichments",
                        aggregate_key={"website_id": website_id},
                        operation="delete",
                        source_method="delete_tool_website",
                    )
                if deleted:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="tool_websites",
                        aggregate_key={"id": website_id},
                        operation="delete",
                        source_method="delete_tool_website",
                    )
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
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="tool_website_enrichments",
                    aggregate_key={"website_id": int(data["website_id"])},
                    source_method="upsert_tool_website_enrichment",
                )
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
        return self._project_write_delegate().recommend_github_project(
            repo_id=repo_id,
            full_name=full_name,
            recommended_by_user_id=recommended_by_user_id,
        )

    def unrecommend_github_project(
        self, *, repo_id: Any = None, full_name: str = ""
    ) -> Dict[str, Any]:
        return self._project_write_delegate().unrecommend_github_project(
            repo_id=repo_id, full_name=full_name
        )

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
                BINARY c.repo_id ASC
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
            strict_terms = tuple(term for term in q.strict_terms if term.strip())
            concept_groups = tuple(
                tuple(
                    dict.fromkeys(
                        term
                        for term in (*concept.primary_terms, *concept.aliases)
                        if term.strip()
                    )
                )
                for concept in q.concepts
            )
            concept_groups = tuple(group for group in concept_groups if group)
            normalized_query = normalize_search_query(q.normalized_query)
        else:
            strict_terms = tuple(project_search_terms(q))
            concept_groups = ()
            normalized_query = normalize_search_query(q)
        if not strict_terms and not concept_groups:
            return ProjectLexicalCandidateLanes()
        strict_limit = max(1, min(int(strict_limit or 150), 150))
        relaxed_limit = max(1, min(int(relaxed_limit or 150), 150))
        prefix = f"{_escape_like_literal(normalized_query)}%"
        filters = ["COALESCE(c.stars, 0) >= %s", "ga.alias_repo_id IS NULL"]
        filter_params: List[Any] = [min_stars]
        if enriched_only:
            filters.append("ge.status COLLATE utf8mb4_unicode_ci = _utf8mb4'succeeded' COLLATE utf8mb4_unicode_ci")
        if category:
            filters.append("ge.category_slug = %s")
            filter_params.append(category)
        if subcategory:
            default_subcategory = DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")
            if category and subcategory == default_subcategory:
                filters.append("(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
            else:
                filters.append("ge.subcategory_slug = %s")
            filter_params.append(subcategory)
        if language:
            filters.append("LOWER(COALESCE(c.language, '')) = LOWER(%s)")
            filter_params.append(language)
        if tag:
            filters.append("COALESCE(ge.tags_json, '') LIKE %s")
            filter_params.append(f'%"{tag.strip()}"%')

        term_match = (
            "(c.full_name LIKE %s ESCAPE '=' OR COALESCE(c.title, '') LIKE %s ESCAPE '=' OR "
            "COALESCE(c.description, '') LIKE %s ESCAPE '=' OR COALESCE(ge.description_zh, '') LIKE %s ESCAPE '=' OR "
            "COALESCE(c.language, '') LIKE %s ESCAPE '=' OR COALESCE(c.topics_json, '') LIKE %s ESCAPE '=' OR "
            "COALESCE(ge.tags_json, '') LIKE %s ESCAPE '=')"
        )
        coverage_clauses: List[str] = []
        coverage_params: List[Any] = []
        for term in strict_terms:
            coverage_clauses.append(f"CASE WHEN {term_match} THEN 1 ELSE 0 END")
            coverage_params.extend([f"%{_escape_like_literal(term)}%"] * 7)
        for concept_group in concept_groups:
            group_match = " OR ".join(term_match for _ in concept_group)
            coverage_clauses.append(f"CASE WHEN ({group_match}) THEN 1 ELSE 0 END")
            for term in concept_group:
                coverage_params.extend([f"%{_escape_like_literal(term)}%"] * 7)
        coverage_expression = " + ".join(coverage_clauses)
        required_coverage = len(coverage_clauses)
        scored_sql = f"""
            SELECT
                c.repo_id,
                c.full_name,
                COALESCE(c.stars, 0) AS stars,
                ({coverage_expression}) AS term_coverage,
                CASE
                    WHEN LOWER(c.full_name) = LOWER(%s) THEN 4
                    WHEN LOWER(COALESCE(c.title, '')) = LOWER(%s) THEN 3
                    WHEN c.full_name LIKE %s ESCAPE '=' THEN 2
                    WHEN COALESCE(c.title, '') LIKE %s ESCAPE '=' THEN 1
                    ELSE 0
                END AS match_strength
            FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
            LEFT JOIN github_repo_aliases ga
              ON ga.alias_repo_id = c.repo_id
             AND ga.canonical_repo_id <> c.repo_id
            WHERE {' AND '.join(filters)}
        """
        scored_params = coverage_params + [normalized_query, normalized_query, prefix, prefix] + filter_params

        def lane_sql(*, strict: bool) -> str:
            qualification = "term_coverage = %s" if strict else "term_coverage > 0"
            ordering = (
                "match_strength DESC, stars DESC, BINARY repo_id ASC"
                if strict
                else "term_coverage DESC, match_strength DESC, stars DESC, BINARY repo_id ASC"
            )
            return f"""
                SELECT repo_id, term_coverage, match_strength
                FROM ({scored_sql}) scored
                WHERE {qualification}
                ORDER BY {ordering}
                LIMIT %s
            """

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    lane_sql(strict=True),
                    tuple(scored_params + [required_coverage, strict_limit]),
                )
                strict_rows = cur.fetchall()
                cur.execute(
                    lane_sql(strict=False),
                    tuple(scored_params + [relaxed_limit]),
                )
                relaxed_rows = cur.fetchall()
            conn.commit()
        finally:
            conn.close()

        def candidates(rows: List[Dict[str, Any]], lane: str) -> tuple[ProjectLexicalCandidate, ...]:
            return tuple(
                ProjectLexicalCandidate(
                    repo_id=str(row.get("repo_id") or ""),
                    lane=lane,
                    term_coverage=int(row.get("term_coverage") or 0),
                    match_strength=int(row.get("match_strength") or 0),
                )
                for row in rows
                if row.get("repo_id")
            )

        return ProjectLexicalCandidateLanes(
            strict=candidates(strict_rows, "strict"),
            relaxed=candidates(relaxed_rows, "relaxed"),
        )

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
                c.availability_status,
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
                'active' AS availability_status,
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
        order_params: List[Any] = []
        if sort == "relevance" and clean_candidate_repo_ids is not None:
            relevance_placeholders = ", ".join(["%s"] * len(clean_candidate_repo_ids))
            order_by = f"FIELD(repo_id, {relevance_placeholders}), full_name ASC"
            order_params.extend(clean_candidate_repo_ids)
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
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_project_semantic_sources",
                    aggregate_key={"repo_id": canonical_repo_id},
                    source_method="upsert_github_project_semantic_source",
                )
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
                canonical_repo_id = self._resolve_github_repo_id_cur(
                    cur,
                    str(data.get("repo_id") or ""),
                )
                data["repo_id"] = canonical_repo_id
                cur.execute(sql, data)
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_repo_enrichments",
                    aggregate_key={"repo_id": canonical_repo_id},
                    source_method="upsert_github_repo_enrichment",
                )
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

    def get_briefing(self, briefing_id: int) -> Optional[Dict[str, Any]]:
        return self.briefings.get_briefing(briefing_id)

    def list_briefings(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self.briefings.list_briefings(limit)

    # ------------------------------------------------------------------
    # Runtime Provider Settings
    # ------------------------------------------------------------------

    def get_runtime_provider_setting(self, provider: str = "") -> Optional[Dict[str, Any]]:
        return self.runtime_provider_settings.get_runtime_provider_setting(provider)

    def upsert_runtime_provider_setting(
        self,
        provider: str,
        base_url: str = "",
        api_key: Optional[str] = None,
        clear_api_key: bool = False,
        model_name: str = "",
    ) -> Dict[str, Any]:
        return self.runtime_provider_settings.upsert_runtime_provider_setting(
            provider,
            base_url,
            api_key,
            clear_api_key,
            model_name,
        )

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
        return self.conversations.get_or_create_conversation(
            user_id=user_id, scope=scope, scope_key=scope_key, title=title
        )

    def create_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.conversations.create_conversation(
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title,
            keep_latest=0,
        )

    def delete_conversation_by_id(
        self, conversation_id: int, *, user_id: Optional[int] = None
    ) -> bool:
        return self.conversations.delete_conversation_by_id(
            conversation_id, user_id=user_id
        )

    def get_conversation_by_id(
        self, conversation_id: int, *, user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        return self.conversations.get_conversation_by_id(
            conversation_id, user_id=user_id
        )

    def list_conversations(
        self,
        *,
        user_id: int,
        scope: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        return self.conversations.list_conversations(
            user_id=user_id, scope=scope, page=page, page_size=page_size
        )

    def touch_conversation(self, conversation_id: int) -> None:
        return self.conversations.touch_conversation(conversation_id)

    def refresh_conversation_stats(
        self,
        conversation_id: int,
        *,
        title: Optional[str] = None,
        last_message_preview: Optional[str] = None,
    ) -> None:
        return self.conversations.refresh_conversation_stats(
            conversation_id, title=title, last_message_preview=last_message_preview
        )

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
        return self.conversations.create_chat_message(
            conversation_id=conversation_id, role=role, content=content,
            thinking=thinking, sources=sources, attachments=attachments, status=status,
            parent_message_id=parent_message_id,
        )

    def list_chat_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        return self.conversations.list_chat_messages(conversation_id)

    def get_chat_message(
        self, message_id: int, *, user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        return self.conversations.get_chat_message(message_id, user_id=user_id)

    def delete_message_branch(self, message_id: int) -> List[int]:
        return self.conversations.delete_message_branch(message_id)

    def delete_messages_after(self, message_id: int) -> List[int]:
        return self.conversations.delete_messages_after(message_id)

    def trim_conversation_messages(
        self, *, conversation_id: int, keep_latest: int = 10
    ) -> int:
        return self.conversations.trim_conversation_messages(
            conversation_id=conversation_id, keep_latest=keep_latest
        )

    def trim_user_conversations(
        self, *, user_id: int, keep_latest: int = 10
    ) -> int:
        return self.conversations.trim_user_conversations(
            user_id=user_id, keep_latest=keep_latest
        )

    def cleanup_stale_conversations(
        self, *, stale_days: int = 7, limit: int = 5
    ) -> int:
        return self.conversations.cleanup_stale_conversations(
            stale_days=stale_days, limit=limit
        )

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
    def _deserialize_attachment(row: Dict[str, Any]) -> Dict[str, Any]:
        row["meta"] = json.loads(row.get("meta_json") or "{}")
        return row
