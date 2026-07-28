from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle
from backend.app.services.search_semantics import (
    TECHNICAL_TOKEN_RE,
    escape_like_literal,
    normalize_search_query,
)

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


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_doc_lookup_key(value: str | None) -> str:
    return (value or "").strip()


def _document_search_candidates(query: str, *, max_terms: int = 5) -> list[str]:
    normalized = normalize_search_query(query)
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
    return candidates


def _document_projection() -> str:
    return """
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


class MySQLDocumentRepository:
    """MySQL persistence for documents, search, feeds, and statistics."""

    def __init__(self, database: DatabaseLifecycle) -> None:
        self._database = database

    def upsert_document(self, doc: dict[str, Any]) -> None:
        sql = """
            INSERT INTO documents (id, source, source_channel, title, url, summary, published_date,
                                   tags, score, raw_score, stars, forks, language, rank_in_period, indexed,
                                   in_daily, in_weekly, in_monthly, local_pdf_path, created_at)
            VALUES (%(id)s, %(source)s, %(source_channel)s, %(title)s, %(url)s, %(summary)s, %(published_date)s,
                    %(tags)s, %(score)s, %(raw_score)s, %(stars)s, %(forks)s, %(language)s, %(rank_in_period)s, %(indexed)s,
                    %(in_daily)s, %(in_weekly)s, %(in_monthly)s, %(local_pdf_path)s, %(created_at)s)
            ON DUPLICATE KEY UPDATE
                source_channel=VALUES(source_channel), title=VALUES(title), url=VALUES(url),
                summary=VALUES(summary),
                published_date=COALESCE(NULLIF(VALUES(published_date), ''), published_date),
                tags=VALUES(tags), score=GREATEST(score, VALUES(score)),
                raw_score=GREATEST(raw_score, VALUES(raw_score)),
                stars=COALESCE(NULLIF(VALUES(stars), 0), stars),
                forks=COALESCE(NULLIF(VALUES(forks), 0), forks),
                language=COALESCE(NULLIF(VALUES(language), ''), language),
                rank_in_period=LEAST(rank_in_period, VALUES(rank_in_period)),
                indexed=VALUES(indexed), in_daily=GREATEST(in_daily, VALUES(in_daily)),
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
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, doc)

    def update_document_pdf_path(self, doc_id: str, local_pdf_path: str) -> None:
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET local_pdf_path = %s WHERE id = %s",
                    (local_pdf_path, doc_id),
                )

    def search_document_page(
        self,
        query: str,
        *,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        candidates = _document_search_candidates(query)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        if not candidates:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        patterns = [f"%{escape_like_literal(candidate, escape='=')}%" for candidate in candidates]
        field_match = (
            "(COALESCE(title, '') LIKE %s ESCAPE '=' "
            "OR COALESCE(summary, '') LIKE %s ESCAPE '=' "
            "OR COALESCE(tags, '') LIKE %s ESCAPE '=')"
        )
        search_sql = "(" + " OR ".join([field_match] * len(patterns)) + ")"
        where_parts = [search_sql]
        where_params: list[Any] = [pattern for pattern in patterns for _ in range(3)]
        clean_source = str(source or "").strip().lower()
        if clean_source:
            where_parts.append("source = %s")
            where_params.append(clean_source)
        where_sql = " AND ".join(where_parts)

        tier_clauses: list[str] = []
        tier_params: list[Any] = []
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
        with self._database.connection() as conn:
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

    def search_documents(
        self,
        query: str,
        limit: int = 20,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_document_page(
            query,
            source=source,
            page=1,
            page_size=max(1, min(int(limit), 100)),
        )["items"]

    def get_documents_by_ids(
        self,
        document_ids: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        placeholders = ", ".join(["%s"] * len(document_ids))
        sql = f"""
            SELECT id, source, source_channel, title, url, summary,
                   published_date, raw_score, score, rank_in_period, created_at,
                   local_pdf_path
            FROM documents
            WHERE id IN ({placeholders})
            ORDER BY FIELD(id, {placeholders})
            LIMIT %s
        """
        params = tuple(document_ids + document_ids + [limit])
        return self._fetch_rows(sql, params)

    def get_documents_by_title_tokens(
        self,
        tokens: list[str],
        *,
        min_matches: int = 3,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if len(tokens) < min_matches:
            return []
        wildcards = [f"%{token}%" for token in tokens]
        score_sql = " + ".join(["(LOWER(title) LIKE %s)"] * len(tokens))
        match_sql = " OR ".join(["LOWER(title) LIKE %s"] * len(tokens))
        sql = f"""
            SELECT id, source, source_channel, title, url, summary,
                   published_date, raw_score, score, rank_in_period, created_at,
                   local_pdf_path, ({score_sql}) AS keyword_score
            FROM documents
            WHERE ({match_sql})
            HAVING keyword_score >= %s
            ORDER BY keyword_score DESC,
                     CASE WHEN source = 'arxiv' THEN 0 ELSE 1 END ASC,
                     COALESCE(raw_score, score, 0) DESC,
                     published_date DESC
            LIMIT %s
        """
        return self._fetch_rows(
            sql,
            tuple(wildcards + wildcards + [min_matches, limit]),
        )

    def get_today_ranked_documents(
        self,
        limit: int = 15,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
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
        ids = [_normalize_doc_lookup_key(item) for item in (ids or [])]
        urls = [_normalize_doc_lookup_key(item) for item in (urls or [])]
        titles = [_normalize_doc_lookup_key(item) for item in (titles or [])]
        ids = [item for item in ids if item]
        urls = [item for item in urls if item]
        titles = [item for item in titles if item]

        conditions: list[str] = []
        params: list[Any] = []
        for column, values in (("id", ids), ("url", urls), ("title", titles)):
            if values:
                placeholders = ", ".join(["%s"] * len(values))
                conditions.append(f"{column} IN ({placeholders})")
                params.extend(values)
        if not conditions:
            return {}

        sql = f"""
            SELECT id, url, title, summary
            FROM documents
            WHERE ({' OR '.join(conditions)})
              AND COALESCE(NULLIF(TRIM(summary), ''), '') != ''
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            conn.commit()

        result: dict[str, str] = {}
        for row in rows:
            summary = (row.get("summary") or "").strip()
            if not summary:
                continue
            for prefix, value in (
                ("id", row.get("id")),
                ("url", row.get("url")),
                ("title", row.get("title")),
            ):
                key = _normalize_doc_lookup_key(value)
                if key:
                    result[f"{prefix}:{key}"] = summary
        return result

    def get_today_top_arxiv_documents(self) -> list[dict[str, Any]]:
        tz_cst = timezone(timedelta(hours=8))
        today = datetime.now(tz_cst).date().isoformat()
        sql_today = """
            SELECT id, source, source_channel, title, url, summary,
                   published_date, tags, score, raw_score, rank_in_period,
                   local_pdf_path, created_at
            FROM documents
            WHERE source = 'arxiv'
              AND LEFT(created_at, 10) = %s
            ORDER BY COALESCE(raw_score, score, 0) DESC
            LIMIT 10
        """
        sql_fallback = """
            SELECT id, source, source_channel, title, url, summary,
                   published_date, tags, score, raw_score, rank_in_period,
                   local_pdf_path, created_at
            FROM documents
            WHERE source = 'arxiv'
            ORDER BY created_at DESC, COALESCE(raw_score, score, 0) DESC
            LIMIT 10
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_today, (today,))
                rows = cur.fetchall()
            conn.commit()
            if rows:
                return [dict(row) for row in rows]
            with conn.cursor() as cur:
                cur.execute(sql_fallback)
                rows = cur.fetchall()
            conn.commit()
            return [dict(row) for row in rows]

    def get_paper_detail(self, paper_id: str) -> dict[str, Any] | None:
        sql = """
            SELECT id, source, source_channel, title, url, summary,
                   published_date, tags, score, raw_score, rank_in_period,
                   local_pdf_path, created_at
            FROM documents
            WHERE id = %s
            LIMIT 1
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (paper_id,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def get_paper_pdf_source(self, paper_id: str) -> dict[str, Any] | None:
        sql = "SELECT local_pdf_path, url, source FROM documents WHERE id = %s LIMIT 1"
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (paper_id,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def get_top_documents(
        self,
        limit: int = 10,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        projection = _document_projection()
        order_by = """
            ORDER BY
                COALESCE(d.raw_score, d.score, 0) DESC,
                d.published_date DESC
        """
        if source_type and source_type != "all":
            sql = f"{projection} WHERE d.source = %s {order_by} LIMIT %s"
            params: tuple[Any, ...] = (source_type, limit)
        else:
            sql = f"{projection} {order_by} LIMIT %s"
            params = (limit,)
        return self._fetch_rows(sql, params)

    def get_latest_documents(self, limit: int = 10) -> list[dict[str, Any]]:
        sql = f"{_document_projection()} ORDER BY d.created_at DESC LIMIT %s"
        return self._fetch_rows(sql, (limit,))

    def get_document_count(self) -> int:
        return self._fetch_count("SELECT COUNT(*) AS cnt FROM documents")

    def get_source_counts(self) -> dict[str, int]:
        sql = """
            SELECT source, COUNT(DISTINCT COALESCE(NULLIF(url, ''), title)) AS cnt
            FROM documents
            GROUP BY source
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
            conn.commit()
            return {row["source"]: row["cnt"] for row in rows}

    def get_today_document_count(self) -> int:
        tz_cst = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_cst).strftime("%Y-%m-%d")
        return self._fetch_count(
            "SELECT COUNT(*) AS cnt FROM documents WHERE LEFT(created_at, 10) = %s",
            (today_str,),
        )

    def clear_all_documents(self) -> int:
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM documents")
                row = cur.fetchone()
                count = int(row["cnt"] if row else 0)
                cur.execute("DELETE FROM documents")
            return count

    def _fetch_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return list(rows)

    def _fetch_count(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)
