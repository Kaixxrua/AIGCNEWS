from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.document_search_intent import (
    DateWindow,
    parse_query_intent,
    strip_ask_fillers,
)
from backend.app.domain.search_semantics import (
    TECHNICAL_TOKEN_RE,
    escape_like_literal,
    normalize_search_query,
)

_DOCUMENT_SEARCH_INTENT_PHRASES = (
    "learning resources", "learning materials", "help me find", "i would like to",
    "related content", "找一些", "找一点", "相关的内容", "相关内容", "学习资料",
    "学习材料", "进行学习", "我想要", "帮我找", "i want to", "find me",
)
_DOCUMENT_SEARCH_STOP_TERMS = {
    "about", "content", "find", "help", "learn", "learning", "material",
    "materials", "related", "resource", "resources", "tutorial", "tutorials",
    "want", "学习", "内容", "帮我", "教程", "资料",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_today() -> str:
    zone = getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(zone)).date().isoformat()


def _local_today_utc_bounds() -> tuple[str, str]:
    """调度时区自然日对应的 UTC 闭开区间（ISO 串）。

    「今日」以 scheduler_timezone 的日历日为准，换算成 UTC 上下界供
    timestamptz 范围比较；替代 LEFT(ts,10) 词法前缀（该写法把窗口整体
    偏移了时区差，凌晨入库的行永远落不进「今天」）。
    """
    zone = ZoneInfo(getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai")
    today = datetime.now(zone).date()
    start = datetime.combine(today, time.min).replace(tzinfo=zone)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).isoformat(),
        end.astimezone(timezone.utc).isoformat(),
    )


def _normalize_doc_lookup_key(value: str | None) -> str:
    return (value or "").strip()


# 反作弊跨渠道佐证：从文档 url/标题/正文提取 github.com/<owner>/<repo>。
# 只取前两段路径；owner 段排除 GitHub 保留路径前缀。
_GITHUB_REPO_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE
)
_GITHUB_NON_REPO_OWNERS = {
    "apps", "about", "collections", "codespaces", "copilot", "customer-stories",
    "enterprise", "events", "explore", "features", "git-guides", "issues",
    "login", "marketplace", "new", "notifications", "organizations", "pricing",
    "pulls", "readme", "search", "security", "settings", "signup", "sponsors",
    "stars", "team", "topics", "trending",
}


def extract_github_repo_slugs(*texts: str | None) -> set[str]:
    """从任意文本提取 github.com 仓库 slug（owner/repo，小写归一）。"""

    slugs: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _GITHUB_REPO_URL_RE.finditer(str(text)):
            slug = match.group(1)
            owner, _, repo = slug.partition("/")
            owner = owner.strip(".").lower()
            repo = repo.rstrip(".-_").lower()
            if not owner or not repo or owner in _GITHUB_NON_REPO_OWNERS:
                continue
            slugs.add(f"{owner}/{repo}")
    return slugs


@dataclass(frozen=True)
class DocumentSearchPlan:
    """检索计划：ILIKE 候选词（按优先级）+ 可选 published_date 窗口。

    candidates 为空而 window 存在 = 纯时间查询（"今天有什么"），只按日期过滤。
    """

    candidates: list[str]
    window: DateWindow | None = None


def _document_search_plan(query: str, *, today: date, max_terms: int = 5) -> DocumentSearchPlan:
    normalized = normalize_search_query(query)
    if not normalized:
        return DocumentSearchPlan([])
    lowered = normalized.casefold()
    has_intent = any(phrase in lowered for phrase in _DOCUMENT_SEARCH_INTENT_PHRASES)
    intent = parse_query_intent(normalized, today)
    # 提问式查询（带时间意图或提问词）：先剥时间短语，后续再剥问句外壳。
    asks = intent.window is not None or intent.asks
    if not has_intent and not asks and len(normalized) <= 48:
        return DocumentSearchPlan([normalized])
    cleaned = intent.remainder if asks else normalized
    for phrase in sorted(_DOCUMENT_SEARCH_INTENT_PHRASES, key=len, reverse=True):
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    if asks:
        cleaned = strip_ask_fillers(cleaned)
    cleaned = re.sub(r"(^|[\s,，。！？!?;:：；])(?:学习|帮我)(?=[A-Za-z0-9])", r"\1", cleaned)
    cleaned = " ".join(cleaned.strip(" ，。！？,.!?;:：；").split())
    if asks and intent.window is not None and not _has_keyword(cleaned):
        return DocumentSearchPlan([], intent.window)
    candidates = [normalized]
    residual_intent = any(term in cleaned.casefold() for term in _DOCUMENT_SEARCH_STOP_TERMS)
    if cleaned and not residual_intent and cleaned.casefold() != normalized.casefold():
        candidates.append(cleaned)
    seen = {candidate.casefold() for candidate in candidates}
    technical_terms: list[str] = []
    for token in TECHNICAL_TOKEN_RE.findall(cleaned or normalized):
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
    return DocumentSearchPlan(candidates, intent.window)


def _has_keyword(cleaned: str) -> bool:
    """剥壳后是否还剩可检索的词（标点残渣与单个非数字字符不算）。"""
    return any(
        token.casefold() not in _DOCUMENT_SEARCH_STOP_TERMS and (len(token) > 1 or token.isdigit())
        for token in TECHNICAL_TOKEN_RE.findall(cleaned)
    )


def _document_search_candidates(query: str, *, max_terms: int = 5, today: date | None = None) -> list[str]:
    return _document_search_plan(
        query, today=today or date.fromisoformat(_local_today()), max_terms=max_terms
    ).candidates


def _document_projection(*, github_visible: bool = True) -> str:
    """文档读路径共享投影；github_visible=False 时裁剪 github 补全连接。

    github 星数/语言补全只对可能含 github 行的结果集有意义：调用方已按
    具体非 github source 过滤时，c/gs 连接永不命中，COALESCE 回退链
    等价于直接读 d 自身列——省掉 github_repo_candidates(2.5 万行) 与
    github_repo_snapshots(65 万行) 的全量扫描（X 看板每页曾 1.4s+）。
    github_visible=True 时 gs 用 LATERAL + (repo_id, snapshot_date) 索引
    倒序 LIMIT 1 逐行探测；勿改回 DISTINCT ON 全表物化（整表排序落盘，
    与结果集大小无关）。
    """
    if github_visible:
        metric_columns = """COALESCE(NULLIF(d.stars, 0), NULLIF(gs.stars, 0), c.stars, 0) AS stars,
               COALESCE(NULLIF(d.forks, 0), NULLIF(gs.forks, 0), c.forks, 0) AS forks,
               COALESCE(NULLIF(d.language, ''), c.language, '') AS language,"""
        github_joins = """LEFT JOIN github_repo_candidates c
          ON d.source = 'github' AND (c.full_name = d.title
              OR (NULLIF(c.url, '') IS NOT NULL AND c.url = d.url))
        LEFT JOIN LATERAL (
            SELECT g.stars, g.forks
            FROM github_repo_snapshots g
            WHERE g.repo_id = c.repo_id
            ORDER BY g.snapshot_date DESC
            LIMIT 1
        ) gs ON TRUE"""
    else:
        metric_columns = """COALESCE(NULLIF(d.stars, 0), 0) AS stars,
               COALESCE(NULLIF(d.forks, 0), 0) AS forks,
               COALESCE(NULLIF(d.language, ''), '') AS language,"""
        github_joins = ""
    return f"""
        SELECT d.id, d.source, d.source_channel, d.title, d.url, d.summary,
               d.published_date, d.published_at, d.tags, d.score, d.raw_score,
               {metric_columns}
               d.rank_in_period, d.indexed, d.in_daily, d.in_weekly,
               d.in_monthly, d.local_pdf_path, d.media, d.quote, d.link_card, d.author_avatar_url, d.author_name, d.retweeted_by, d.translation_zh, d.authors, d.arxiv_id, d.created_at
        FROM documents d
        {github_joins}
    """


def _deserialize_row_media(row: dict[str, Any]) -> dict[str, Any]:
    """把 JSON 文本列反序列化：media → 列表，quote/link_card → 对象；失败置 None。"""
    # 注意：authors 刻意保持 JSON 字符串（与 tags 一致）。REST 读路径经
    # safe_document 透传标量，若在此反序列化成列表会被 str(value) 打成
    # Python repr；MCP 侧由 _public_doc 单独解析为真数组。
    media = row.get("media")
    if isinstance(media, str) and media:
        try:
            row["media"] = json.loads(media)
        except json.JSONDecodeError:
            row["media"] = None
    quote = row.get("quote")
    if isinstance(quote, str) and quote:
        try:
            row["quote"] = json.loads(quote)
        except json.JSONDecodeError:
            row["quote"] = None
    link_card = row.get("link_card")
    if isinstance(link_card, str) and link_card:
        try:
            row["link_card"] = json.loads(link_card)
        except json.JSONDecodeError:
            row["link_card"] = None
    return row


class PostgresDocumentRepository:
    """PostgreSQL persistence for documents, search, feeds, and statistics."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    @staticmethod
    def _document_params(doc: dict[str, Any]) -> dict[str, Any]:
        params = dict(doc)
        defaults = {
            "created_at": _utcnow(), "indexed": 0, "in_daily": 0,
            "in_weekly": 0, "in_monthly": 0, "score": 0.0,
            "stars": 0, "forks": 0, "language": "", "source_channel": "",
            "rank_in_period": 9999, "local_pdf_path": None, "media": None,
            "quote": None, "link_card": None, "published_at": None,
            "author_avatar_url": None, "author_name": None, "retweeted_by": None,
            "translation_zh": None, "authors": None, "arxiv_id": None,
        }
        for key, value in defaults.items():
            params.setdefault(key, params.get("score", 0.0) if key == "raw_score" else value)
        params.setdefault("raw_score", params.get("score", 0.0))
        for key in ("tags", "authors", "media", "quote", "link_card"):
            if isinstance(params.get(key), (list, dict)):
                params[key] = json.dumps(params[key], ensure_ascii=False)
        for key in ("indexed", "in_daily", "in_weekly", "in_monthly"):
            params[key] = bool(params[key])
        return params

    def upsert_document(self, doc: dict[str, Any]) -> None:
        params = self._document_params(doc)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                self._execute_document_upsert(cursor, params)

    def upsert_x_document_with_translation_targets(
        self, doc: dict[str, Any], targets: list[dict[str, Any]]
    ) -> bool:
        """Upsert an X document and seed its translation targets atomically.

        The returned flag describes only the ``documents`` row.  Translation-task
        upserts below are deliberately not part of the new-document accounting.
        """
        params = self._document_params(doc)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                inserted = self._execute_document_upsert(
                    cursor, params, return_inserted=True
                )
                for target in targets:
                    source_text = str(target.get("source_text") or "")
                    if not source_text:
                        continue
                    source_tweet_id = str(target.get("source_tweet_id") or "")
                    target_kind = str(target.get("target_kind") or "")
                    source_lang = str(target.get("source_lang") or "")
                    fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
                    cursor.execute(
                        """
                        INSERT INTO x_translation_tasks
                            (document_id, target_kind, source_tweet_id, source_text,
                             source_lang, source_fingerprint, status, skip_reason,
                             translation_zh, prompt_version)
                        VALUES (%s, %s, %s, %s, %s, %s,
                                CASE WHEN lower(%s) LIKE 'zh%%' OR lower(%s) = 'zxx'
                                     THEN 'skipped' ELSE 'pending' END,
                                CASE WHEN lower(%s) LIKE 'zh%%' OR lower(%s) = 'zxx'
                                     THEN 'source_language' ELSE NULL END,
                                NULL, 'x-translation-v1')
                        ON CONFLICT (document_id, target_kind) DO UPDATE SET
                            source_tweet_id = EXCLUDED.source_tweet_id,
                            source_text = EXCLUDED.source_text,
                            source_lang = EXCLUDED.source_lang,
                            source_fingerprint = EXCLUDED.source_fingerprint,
                            status = CASE
                                WHEN x_translation_tasks.source_fingerprint = EXCLUDED.source_fingerprint
                                    THEN x_translation_tasks.status
                                WHEN lower(EXCLUDED.source_lang) LIKE 'zh%%'
                                     OR lower(EXCLUDED.source_lang) = 'zxx'
                                    THEN 'skipped'
                                ELSE 'pending'
                            END,
                            skip_reason = CASE
                                WHEN lower(EXCLUDED.source_lang) LIKE 'zh%%'
                                     OR lower(EXCLUDED.source_lang) = 'zxx'
                                    THEN 'source_language' ELSE NULL END,
                            translation_zh = CASE
                                WHEN x_translation_tasks.source_fingerprint = EXCLUDED.source_fingerprint
                                    THEN x_translation_tasks.translation_zh
                                ELSE NULL
                            END,
                            completed_at = CASE
                                WHEN x_translation_tasks.source_fingerprint = EXCLUDED.source_fingerprint
                                    THEN x_translation_tasks.completed_at
                                ELSE NULL
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (params["id"], target_kind, source_tweet_id, source_text,
                         source_lang, fingerprint, source_lang, source_lang,
                         source_lang, source_lang),
                    )
        return inserted

    @staticmethod
    def _execute_document_upsert(
        cursor: Any,
        params: dict[str, Any],
        *,
        return_inserted: bool = False,
    ) -> bool:
        sql = """
            INSERT INTO documents
                (id, source, source_channel, title, url, summary, published_date,
                 published_at, tags, score, raw_score, stars, forks, language, rank_in_period,
                 indexed, in_daily, in_weekly, in_monthly, local_pdf_path, media, quote, link_card, author_avatar_url, author_name, retweeted_by, translation_zh, authors, arxiv_id, created_at)
            VALUES
                (%(id)s, %(source)s, %(source_channel)s, %(title)s, %(url)s,
                 %(summary)s, %(published_date)s, %(published_at)s, %(tags)s, %(score)s,
                 %(raw_score)s, %(stars)s, %(forks)s, %(language)s,
                 %(rank_in_period)s, %(indexed)s, %(in_daily)s, %(in_weekly)s,
                 %(in_monthly)s, %(local_pdf_path)s, %(media)s, %(quote)s, %(link_card)s, %(author_avatar_url)s, %(author_name)s, %(retweeted_by)s, %(translation_zh)s, %(authors)s, %(arxiv_id)s, %(created_at)s)
            ON CONFLICT (id) DO UPDATE SET
                source_channel=EXCLUDED.source_channel, title=EXCLUDED.title,
                url=EXCLUDED.url, summary=EXCLUDED.summary,
                published_date=COALESCE(NULLIF(EXCLUDED.published_date, ''), documents.published_date),
                published_at=COALESCE(NULLIF(EXCLUDED.published_at, ''), documents.published_at),
                tags=EXCLUDED.tags, score=GREATEST(documents.score, EXCLUDED.score),
                raw_score=GREATEST(documents.raw_score, EXCLUDED.raw_score),
                stars=COALESCE(NULLIF(EXCLUDED.stars, 0), documents.stars),
                forks=COALESCE(NULLIF(EXCLUDED.forks, 0), documents.forks),
                language=COALESCE(NULLIF(EXCLUDED.language, ''), documents.language),
                rank_in_period=LEAST(documents.rank_in_period, EXCLUDED.rank_in_period),
                indexed=EXCLUDED.indexed,
                in_daily=(documents.in_daily OR EXCLUDED.in_daily),
                in_weekly=(documents.in_weekly OR EXCLUDED.in_weekly),
                in_monthly=(documents.in_monthly OR EXCLUDED.in_monthly),
                local_pdf_path=COALESCE(EXCLUDED.local_pdf_path, documents.local_pdf_path),
                media=COALESCE(NULLIF(EXCLUDED.media, ''), documents.media),
                quote=CASE
                    WHEN NULLIF(EXCLUDED.quote, '') IS NULL THEN documents.quote
                    WHEN EXCLUDED.source <> 'x' OR documents.source <> 'x' THEN EXCLUDED.quote
                    -- The source projection never carries durable LLM translations.
                    -- Keep a completed quote translation only when it still belongs
                    -- to this exact quoted tweet text (the task fingerprint input).
                    WHEN NOT pg_input_is_valid(EXCLUDED.quote, 'jsonb') THEN documents.quote
                    WHEN NULLIF(documents.quote, '') IS NULL THEN EXCLUDED.quote
                    WHEN NOT pg_input_is_valid(documents.quote, 'jsonb') THEN EXCLUDED.quote
                    WHEN jsonb_typeof(EXCLUDED.quote::jsonb) <> 'object' THEN EXCLUDED.quote
                    WHEN jsonb_typeof(documents.quote::jsonb) <> 'object' THEN EXCLUDED.quote
                    WHEN NULLIF(BTRIM(EXCLUDED.quote::jsonb ->> 'tweet_id'), '') IS NULL THEN EXCLUDED.quote
                    WHEN NULLIF(BTRIM(EXCLUDED.quote::jsonb ->> 'text'), '') IS NULL THEN EXCLUDED.quote
                    WHEN EXCLUDED.quote::jsonb ->> 'tweet_id'
                         IS DISTINCT FROM documents.quote::jsonb ->> 'tweet_id' THEN EXCLUDED.quote
                    WHEN EXCLUDED.quote::jsonb ->> 'text'
                         IS DISTINCT FROM documents.quote::jsonb ->> 'text' THEN EXCLUDED.quote
                    WHEN jsonb_typeof(documents.quote::jsonb -> 'translation_zh') = 'string'
                         AND NULLIF(BTRIM(documents.quote::jsonb ->> 'translation_zh'), '') IS NOT NULL
                         AND (
                            jsonb_typeof(EXCLUDED.quote::jsonb -> 'translation_zh') IS DISTINCT FROM 'string'
                            OR NULLIF(BTRIM(EXCLUDED.quote::jsonb ->> 'translation_zh'), '') IS NULL
                         )
                        THEN jsonb_set(
                            EXCLUDED.quote::jsonb,
                            '{translation_zh}',
                            to_jsonb(documents.quote::jsonb ->> 'translation_zh'),
                            true
                        )::text
                    ELSE EXCLUDED.quote
                END,
                link_card=COALESCE(NULLIF(EXCLUDED.link_card, ''), documents.link_card),
                author_avatar_url=COALESCE(NULLIF(EXCLUDED.author_avatar_url, ''), documents.author_avatar_url),
                author_name=COALESCE(NULLIF(EXCLUDED.author_name, ''), documents.author_name),
                retweeted_by=COALESCE(NULLIF(EXCLUDED.retweeted_by, ''), documents.retweeted_by),
                translation_zh=COALESCE(NULLIF(EXCLUDED.translation_zh, ''), documents.translation_zh),
                authors=COALESCE(NULLIF(EXCLUDED.authors, ''), documents.authors),
                arxiv_id=COALESCE(NULLIF(EXCLUDED.arxiv_id, ''), documents.arxiv_id)
        """
        if return_inserted:
            sql += " RETURNING (xmax = 0) AS inserted"
        cursor.execute(sql, params)
        if not return_inserted:
            return False
        row = cursor.fetchone()
        if isinstance(row, dict):
            return bool(row.get("inserted"))
        if row:
            return bool(row[0])
        return False

    def delete_document(self, doc_id: str) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM document_rank_snapshots WHERE doc_id = %s",
                    (doc_id,),
                )
                cursor.execute(
                    "DELETE FROM documents WHERE id = %s",
                    (doc_id,),
                )
                return bool(cursor.rowcount)

    def delete_documents(self, doc_ids: list[str]) -> list[str]:
        """单事务批量删除文档及其排行快照；返回实际删除的 id（按入参顺序去重）。

        两张表的删除在同一事务内完成，任一失败整体回滚、不留半完成状态；
        以 documents 删除的 RETURNING 为准区分已删除与未找到。
        """
        unique_ids = list(dict.fromkeys(doc_ids))
        if not unique_ids:
            return []
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM document_rank_snapshots WHERE doc_id = ANY(%s)",
                    (unique_ids,),
                )
                cursor.execute(
                    "DELETE FROM documents WHERE id = ANY(%s) RETURNING id",
                    (unique_ids,),
                )
                deleted = {row["id"] for row in cursor.fetchall()}
        return [doc_id for doc_id in unique_ids if doc_id in deleted]

    def update_document_pdf_path(self, doc_id: str, local_pdf_path: str) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET local_pdf_path = %s WHERE id = %s",
                    (local_pdf_path, doc_id),
                )

    def list_arxiv_documents_missing_authors(
        self, *, after_id: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """按 id  keyset 分页列出尚缺作者信息的 arXiv 文档（回填脚本专用）。"""
        return self._fetch_rows(
            "SELECT id, url FROM documents WHERE source = 'arxiv'"
            " AND (authors IS NULL OR authors = '') AND id > %s"
            " ORDER BY id LIMIT %s",
            (after_id, max(1, min(int(limit), 10000))),
        )

    def update_document_authors(self, doc_id: str, authors: str, arxiv_id: str) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET authors = %s, arxiv_id = %s WHERE id = %s",
                    (authors, arxiv_id, doc_id),
                )

    def list_arxiv_document_summaries(
        self, *, after_id: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """按 id keyset 分页列出全部 arXiv 文档的摘要（摘要复核脚本专用）。

        旧解析的缺陷（链接两侧丢空格、误取评论段）无法用 SQL 条件圈定，
        只能逐篇对照 arXiv API / HF 详情页的真摘要复核，故不预筛。
        """
        return self._fetch_rows(
            "SELECT id, arxiv_id, summary FROM documents WHERE source = 'arxiv'"
            " AND id > %s ORDER BY id LIMIT %s",
            (after_id, max(1, min(int(limit), 10000))),
        )

    def update_document_summary_if_unchanged(
        self, doc_id: str, expected: str | None, summary: str
    ) -> bool:
        """仅当库中摘要仍是读出时的值才覆盖（与并发采集的新写入不相互踩踏）。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET summary = %s"
                    " WHERE id = %s AND summary IS NOT DISTINCT FROM %s",
                    (summary, doc_id, expected),
                )
                return cursor.rowcount == 1

    def search_document_page(
        self,
        query: str,
        *,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        plan = _document_search_plan(query, today=date.fromisoformat(_local_today()))
        candidates = plan.candidates
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        if not candidates and plan.window is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        patterns = [f"%{escape_like_literal(candidate, escape='=')}%" for candidate in candidates]
        field_match = "(COALESCE(title, '') ILIKE %s ESCAPE '=' OR COALESCE(summary, '') ILIKE %s ESCAPE '=' OR COALESCE(tags, '') ILIKE %s ESCAPE '=')"
        where_parts: list[str] = []
        where_params: list[Any] = []
        if patterns:
            where_parts.append("(" + " OR ".join([field_match] * len(patterns)) + ")")
            where_params.extend(pattern for pattern in patterns for _ in range(3))
        if plan.window is not None:
            # published_date 是 YYYY-MM-DD 前缀的 VARCHAR（arXiv 带 T 时刻），字典序即时间序。
            where_parts.append("published_date >= %s AND published_date < %s")
            where_params.extend([plan.window.since, plan.window.until])
        clean_source = str(source or "").strip().lower()
        if clean_source:
            where_parts.append("source = %s")
            where_params.append(clean_source)
        where_sql = " AND ".join(where_parts)
        order_parts: list[str] = []
        order_params: list[Any] = []
        if patterns:
            tier_clauses: list[str] = []
            for index, pattern in enumerate(patterns):
                tier_clauses.append(f"WHEN COALESCE(title, '') ILIKE %s ESCAPE '=' THEN {index * 2}")
                order_params.append(pattern)
                tier_clauses.append(f"WHEN (COALESCE(summary, '') ILIKE %s ESCAPE '=' OR COALESCE(tags, '') ILIKE %s ESCAPE '=') THEN {index * 2 + 1}")
                order_params.extend([pattern, pattern])
            order_parts.append(f"CASE {' '.join(tier_clauses)} ELSE {len(patterns) * 2} END ASC")
            order_parts.append("(" + " + ".join(f"CASE WHEN {field_match} THEN 1 ELSE 0 END" for _ in patterns) + ") DESC")
            order_params.extend(pattern for pattern in patterns for _ in range(3))
        if plan.window is not None:
            # 只比日期：arXiv 的 T 时刻后缀不应压过同日其他源，同日内交给热度。
            order_parts.append("LEFT(published_date, 10) DESC")
        order_parts.extend([
            "COALESCE(raw_score, score, 0) DESC",
            'created_at DESC, id COLLATE "C" ASC',
        ])
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS cnt FROM documents WHERE {where_sql}", tuple(where_params))
                total_row = cursor.fetchone()
                total = int(total_row["cnt"] if total_row else 0)
                cursor.execute(
                    f"""SELECT id, source, source_channel, title, url, summary,
                               published_date, tags, score, raw_score, rank_in_period,
                               local_pdf_path, authors, arxiv_id, created_at
                        FROM documents WHERE {where_sql}
                        ORDER BY {', '.join(order_parts)}
                        LIMIT %s OFFSET %s""",
                    tuple(where_params + order_params + [page_size, (page - 1) * page_size]),
                )
                items = [dict(row) for row in cursor.fetchall()]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def search_documents(self, query: str, limit: int = 20, *, source: str | None = None) -> list[dict[str, Any]]:
        return self.search_document_page(query, source=source, page=1, page_size=max(1, min(int(limit), 100)))["items"]

    def get_documents_by_ids(
        self,
        document_ids: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        sql = """
            WITH requested AS (
                SELECT id, MIN(ordinality) AS caller_order
                FROM unnest(%s::text[]) WITH ORDINALITY AS requested_id(id, ordinality)
                GROUP BY id
            )
            SELECT d.id, d.source, d.source_channel, d.title, d.url, d.summary,
                   d.published_date, d.raw_score, d.score, d.rank_in_period,
                   d.created_at, d.local_pdf_path
            FROM requested
            JOIN documents d ON d.id = requested.id
            ORDER BY requested.caller_order ASC
            LIMIT %s
        """
        return self._fetch_rows(sql, (document_ids, limit))

    def get_documents_by_title_tokens(
        self,
        tokens: list[str],
        *,
        min_matches: int = 3,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if len(tokens) < min_matches:
            return []
        wildcards = [f"%{escape_like_literal(token, escape='=')}%" for token in tokens]
        score_sql = " + ".join(
            ["CASE WHEN LOWER(title) LIKE %s ESCAPE '=' THEN 1 ELSE 0 END"] * len(tokens)
        )
        sql = f"""
            WITH ranked AS (
                SELECT id, source, source_channel, title, url, summary,
                       published_date, raw_score, score, rank_in_period, created_at,
                       local_pdf_path, ({score_sql}) AS keyword_score
                FROM documents
            )
            SELECT id, source, source_channel, title, url, summary,
                   published_date, raw_score, score, rank_in_period, created_at,
                   local_pdf_path, keyword_score
            FROM ranked
            WHERE keyword_score >= %s
            ORDER BY keyword_score DESC,
                     CASE WHEN source = 'arxiv' THEN 0 ELSE 1 END ASC,
                     COALESCE(raw_score, score, 0) DESC,
                     published_date DESC
            LIMIT %s
        """
        return self._fetch_rows(sql, tuple(wildcards + [min_matches, limit]))

    def get_today_ranked_documents(
        self,
        limit: int = 15,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        today = _local_today()
        fields = (
            "id, source, source_channel, title, url, summary, published_date, "
            "raw_score, score, rank_in_period, created_at"
        )
        if source and source != "all":
            return self._fetch_rows(
                f"SELECT {fields} FROM documents "
                "WHERE LEFT(created_at, 10) = %s AND source = %s "
                "ORDER BY raw_score DESC, rank_in_period ASC LIMIT %s",
                (today, source, limit),
            )
        return self._fetch_rows(
            f"SELECT {fields} FROM documents "
            "WHERE LEFT(created_at, 10) = %s "
            "ORDER BY raw_score DESC, rank_in_period ASC LIMIT %s",
            (today, limit),
        )

    def get_knowledge_ranked_documents(
        self,
        limit: int = 50,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        fields = (
            "id, source, source_channel, title, url, summary, published_date, "
            "raw_score, score, rank_in_period, created_at"
        )
        if source and source != "all":
            return self._fetch_rows(
                f"SELECT {fields} FROM documents WHERE source = %s "
                "ORDER BY raw_score DESC, created_at DESC LIMIT %s",
                (source, limit),
            )
        return self._fetch_rows(
            f"SELECT {fields} FROM documents "
            "ORDER BY raw_score DESC, created_at DESC LIMIT %s",
            (limit,),
        )

    def get_existing_document_summaries(
        self,
        *,
        ids: list[str] | None = None,
        urls: list[str] | None = None,
        titles: list[str] | None = None,
    ) -> dict[str, str]:
        groups = [
            ("id", [value for item in (ids or []) if (value := _normalize_doc_lookup_key(item))]),
            ("url", [value for item in (urls or []) if (value := _normalize_doc_lookup_key(item))]),
            ("title", [value for item in (titles or []) if (value := _normalize_doc_lookup_key(item))]),
        ]
        conditions: list[str] = []
        params: list[Any] = []
        for column, values in groups:
            if values:
                conditions.append(f"{column} = ANY(%s)")
                params.append(values)
        if not conditions:
            return {}
        rows = self._fetch_rows(
            f"SELECT id, url, title, summary FROM documents WHERE ({' OR '.join(conditions)}) AND COALESCE(NULLIF(TRIM(summary), ''), '') != ''",
            tuple(params),
        )
        result: dict[str, str] = {}
        for row in rows:
            summary = (row.get("summary") or "").strip()
            for prefix, value in (("id", row.get("id")), ("url", row.get("url")), ("title", row.get("title"))):
                key = _normalize_doc_lookup_key(value)
                if key:
                    result[f"{prefix}:{key}"] = summary
        return result

    def get_today_top_arxiv_documents(self) -> list[dict[str, Any]]:
        today = _local_today()
        fields = "id, source, source_channel, title, url, summary, published_date, tags, score, raw_score, rank_in_period, local_pdf_path, created_at"
        rows = self._fetch_rows(
            f"SELECT {fields} FROM documents WHERE source = 'arxiv' AND LEFT(created_at, 10) = %s ORDER BY COALESCE(raw_score, score, 0) DESC LIMIT 10",
            (today,),
        )
        return rows or self._fetch_rows(
            f"SELECT {fields} FROM documents WHERE source = 'arxiv' ORDER BY created_at DESC, COALESCE(raw_score, score, 0) DESC LIMIT 10",
            (),
        )

    def get_paper_detail(self, paper_id: str) -> dict[str, Any] | None:
        fields = "id, source, source_channel, title, url, summary, published_date, tags, score, raw_score, rank_in_period, local_pdf_path, authors, arxiv_id, created_at"
        return self._fetch_one(f"SELECT {fields} FROM documents WHERE id = %s LIMIT 1", (paper_id,))

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> dict[str, Any] | None:
        """按 arXiv 编号（不带版本号）找论文；同一篇入库过几行时取最近入库的那行，与详情同一组字段。"""
        fields = "id, source, source_channel, title, url, summary, published_date, tags, score, raw_score, rank_in_period, local_pdf_path, authors, arxiv_id, created_at"
        return self._fetch_one(
            f"SELECT {fields} FROM documents WHERE source = 'arxiv' AND arxiv_id = %s ORDER BY created_at DESC, id LIMIT 1",
            (arxiv_id,),
        )

    def get_paper_pdf_source(self, paper_id: str) -> dict[str, Any] | None:
        return self._fetch_one("SELECT local_pdf_path, url, source FROM documents WHERE id = %s LIMIT 1", (paper_id,))

    def get_top_documents(self, limit: int = 10, source_type: str | None = None) -> list[dict[str, Any]]:
        projection = _document_projection(
            github_visible=source_type in (None, "", "all", "github")
        )
        order = "ORDER BY COALESCE(d.raw_score, d.score, 0) DESC, d.published_date DESC"
        if source_type and source_type != "all":
            return self._fetch_rows(f"{projection} WHERE d.source = %s {order} LIMIT %s", (source_type, limit))
        return self._fetch_rows(f"{projection} {order} LIMIT %s", (limit,))

    def get_recent_top_documents(
        self,
        *,
        source_type: str,
        since_date: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """简报兜底：单源、日期域内（入库日期 >= since_date）按分数排序的文档。

        用 created_at 词法前缀做日期过滤而非 published_at —— published_at
        存在空串/脏串（github 源无发布时间），会系统性漏行；created_at 是
        采集入库时间，所有源都有值，语义等价于"近期进入文档池的条目"。
        """
        return self._fetch_rows(
            f"{_document_projection(github_visible=source_type in ('', 'all', 'github'))}"
            " WHERE d.source = %s AND LEFT(d.created_at, 10) >= %s "
            "ORDER BY COALESCE(d.raw_score, d.score, 0) DESC, d.created_at DESC LIMIT %s",
            (source_type, since_date, limit),
        )

    def list_github_repo_mentions(
        self,
        *,
        since_date: str,
        until_date: str,
    ) -> set[str]:
        """反作弊佐证：窗口内非 github 渠道文档提及的 owner/repo 集合（小写）。

        用 created_at（UTC 入库时间）词法前缀过滤而非 published_date ——
        各源 published_date 时区不统一且存在脏串（与 get_recent_top_documents
        同款口径）；佐证是存在性判断，宁宽勿漏，窗口由调用方前后各扩一天。
        url 全字段匹配；X 的仓库链接只在推文正文里，故 title/summary 一并提取。
        PH 只存 permalink 不含 repo 链接，本期不纳入佐证源。
        """
        rows = self._fetch_rows(
            """
            SELECT d.url, d.title, d.summary
            FROM documents d
            WHERE d.source IN ('hackernews','news','dailyhot','x')
              AND LEFT(d.created_at, 10) BETWEEN %s AND %s
              AND (d.url ILIKE '%%github.com%%' OR d.title ILIKE '%%github.com%%'
                   OR d.summary ILIKE '%%github.com%%')
            """,
            (since_date, until_date),
        )
        mentions: set[str] = set()
        for row in rows:
            mentions.update(
                extract_github_repo_slugs(
                    row.get("url"), row.get("title"), row.get("summary")
                )
            )
        return mentions

    def get_latest_documents(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._fetch_rows(f"{_document_projection()} ORDER BY d.created_at DESC LIMIT %s", (limit,))

    def list_recent_by_source(
        self,
        source: str,
        *,
        since_iso: str,
        until_iso: str | None = None,
        limit: int = 500,
        keyset_after: tuple[str, float, str] | None = None,
        x_handles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """滚动窗口读取近期文档，新到旧。

        窗口/排序键 = COALESCE(NULLIF(published_at,''), NULLIF(published_date,''),
        created_at)——与展示层 pubDate/lastmod 同一回退链：X 源为推文发布时间，
        github 等榜单源为每日上榜刷新的 published_date（窗口语义即「近 N 小时
        上榜」，重上榜仓不受首次入池时间限制），其余源为业务日期。
        额外 OR created_at >= since 兜底两种键形态漏检：
          1. date-only 键在边界日词法偏严（"2026-08-16" < "2026-08-16T00:00:00+00:00"）；
          2. 业务日期滞后于入池的源（arXiv 老论文当日新收录）。
        until_iso 只约束主键：X 行主键即 published_at，看板 days_back 回移
        语义不变（路由层另有 published_at 精确复筛）。
        """
        if source == "x":
            # X 的发布时间是唯一的窗口/排序主键。不要回退到 created_at：
            # 回退会让迟到入库的旧推文挤进当前窗口，也会让非法时间串
            # 破坏 published_at 的时间线语义。
            # keyset_after = 上一页末行的排序位置 (published_at, score, id)，
            # 与下方 ORDER BY 完全同序；严格不等式续查天然跳过同值并列。
            score_expr = "COALESCE(d.raw_score, d.score, 0)"
            clause = (
                f"{_document_projection(github_visible=(source == 'github'))} WHERE d.source = %s"
                " AND NULLIF(d.published_at, '') IS NOT NULL"
                " AND d.published_at >= %s"
            )
            params: list[Any] = [source, since_iso]
            if until_iso:
                clause += " AND d.published_at < %s"
                params.append(until_iso)
            if x_handles is not None:
                # Match the followed account, including reposts from other authors.
                clause += (
                    " AND LOWER(COALESCE(NULLIF(LTRIM(BTRIM(d.retweeted_by), '@'), ''),"
                    " SUBSTRING(d.url FROM '^(?:https?://)?(?:www[.])?"
                    "(?:x|twitter)[.]com/([^/?[:space:]]+)/status/'), '')) = ANY(%s)"
                )
                params.append(x_handles)
            if keyset_after is not None:
                last_published, last_score, last_id = keyset_after
                clause += (
                    f" AND (d.published_at < %s"
                    f" OR (d.published_at = %s AND {score_expr} < %s)"
                    f" OR (d.published_at = %s AND {score_expr} = %s AND d.id < %s))"
                )
                params.extend(
                    [
                        last_published,
                        last_published,
                        last_score,
                        last_published,
                        last_score,
                        last_id,
                    ]
                )
            rows = self._fetch_rows(
                clause
                + " ORDER BY d.published_at DESC, "
                f"{score_expr} DESC, d.id DESC LIMIT %s",
                (*params, limit),
            )
            return [_deserialize_row_media(row) for row in rows]

        recent_at = "COALESCE(NULLIF(d.published_at, ''), NULLIF(d.published_date, ''), d.created_at)"
        clause = (
            f"{_document_projection(github_visible=(source == 'github'))} WHERE d.source = %s"
            f" AND ({recent_at} >= %s OR d.created_at >= %s)"
        )
        params = [source, since_iso, since_iso]
        if until_iso:
            clause += f" AND {recent_at} <= %s"
            params.append(until_iso)
        rows = self._fetch_rows(
            clause
            + f" ORDER BY {recent_at} DESC, COALESCE(d.raw_score, d.score, 0) DESC LIMIT %s",
            (*params, limit),
        )
        return [_deserialize_row_media(row) for row in rows]

    def list_x_snapshot_backfill_rows(self) -> list[dict[str, Any]]:
        """补拉重建用：全部 X 文档的 id/published_at/分数（发布时间升序）。

        不做 published_at 有效性过滤——脏时间串由服务层解析时剔除并计数，
        便于管理端回报「无法归属日期」的存量规模。
        """
        return self._fetch_rows(
            """
            SELECT d.id, d.published_at, d.raw_score, d.score
            FROM documents d
            WHERE d.source = 'x'
            ORDER BY d.published_at ASC
            """,
            (),
        )

    def list_x_documents_for_probe(self, limit: int) -> list[dict[str, Any]]:
        """janitor 探测用：X 文档的 id/url/quote（发布新的在前，截断到 limit）。

        quote 为 JSON 文本列，由 _fetch_rows 按既有口径反序列化为对象；
        坏 JSON 置 None（服务层按「无被引」处理）。
        """
        return self._fetch_rows(
            """
            SELECT d.id, d.url, d.quote
            FROM documents d
            WHERE d.source = 'x'
            ORDER BY d.published_at DESC
            LIMIT %s
            """,
            (max(1, min(int(limit), 5000)),),
        )

    def clear_quotes_for_docs(self, doc_ids: list[str]) -> list[str]:
        """单事务清引用卡：quote 置 NULL；返回实际更新的 id（按入参顺序去重）。

        以 UPDATE ... RETURNING 为准区分已清理与无卡/未找到。
        """
        unique_ids = list(dict.fromkeys(doc_ids))
        if not unique_ids:
            return []
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET quote = NULL"
                    " WHERE id = ANY(%s) AND quote IS NOT NULL RETURNING id",
                    (unique_ids,),
                )
                cleared = {row["id"] for row in cursor.fetchall()}
        return [doc_id for doc_id in unique_ids if doc_id in cleared]

    def get_document_count(self) -> int:
        return self._fetch_count("SELECT COUNT(*) AS cnt FROM documents")

    def get_source_counts(self) -> dict[str, int]:
        rows = self._fetch_rows("SELECT source, COUNT(DISTINCT COALESCE(NULLIF(url, ''), title)) AS cnt FROM documents GROUP BY source", ())
        return {row["source"]: int(row["cnt"]) for row in rows}

    def get_today_document_count(self) -> int:
        start_utc, end_utc = _local_today_utc_bounds()
        # 「今日」= scheduler_timezone（默认 Asia/Shanghai）的自然日：
        # 时间戳经 ::timestamptz 归一后与当日 UTC 闭开区间比较，凌晨入库
        # 当日即计入、零点翻篇即清零。github 源不计 documents 行，改计
        # github_repo_enrichments 同窗口 status='succeeded' 的入库项目
        # （github_library_total 的当日增量；候选池 first_seen 不计）。
        # 注意：upsert 重富化会覆写 enriched_at，prompt 版本升级等批量重跑
        # 当日会把旧项目计入本计数。
        return self._fetch_count(
            """
            SELECT (
                SELECT COUNT(*) FROM documents
                WHERE source <> 'github'
                  AND NULLIF(created_at, '')::timestamptz >= %s::timestamptz
                  AND NULLIF(created_at, '')::timestamptz < %s::timestamptz
            ) + (
                SELECT COUNT(*) FROM github_repo_enrichments
                WHERE status = 'succeeded'
                  AND NULLIF(enriched_at, '')::timestamptz >= %s::timestamptz
                  AND NULLIF(enriched_at, '')::timestamptz < %s::timestamptz
            ) AS cnt
            """,
            (start_utc, end_utc, start_utc, end_utc),
        )

    def clear_all_documents(self) -> int:
        # 文档与排行快照同事务清空：不留指向已删文档的孤儿快照行
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM documents")
                row = cursor.fetchone()
                count = int(row["cnt"] if row else 0)
                cursor.execute("DELETE FROM document_rank_snapshots")
                cursor.execute("DELETE FROM documents")
                return count

    def _fetch_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return [_deserialize_row_media(dict(row)) for row in cursor.fetchall()]

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return _deserialize_row_media(dict(row)) if row else None

    def _fetch_count(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        row = self._fetch_one(sql, params)
        return int(row["cnt"] if row else 0)
