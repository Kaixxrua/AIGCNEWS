from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import pymysql

try:
    from DBUtils.PooledDB import PooledDB
except ModuleNotFoundError:
    from dbutils.pooled_db import PooledDB

from backend.app.core.config import settings


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_doc_lookup_key(value: Optional[str]) -> str:
    return (value or "").strip()


class MySQLRepository:
    """MySQL repository for metadata, task records, briefings, eval results and GitHub hotness."""

    def __init__(self) -> None:
        self._pool = PooledDB(
            creator=pymysql,
            mincached=2,
            maxcached=5,
            maxconnections=20,
            blocking=True,
            host=getattr(settings, "mysql_host", "localhost"),
            port=getattr(settings, "mysql_port", 3306),
            user=getattr(settings, "mysql_user", "root"),
            password=getattr(settings, "mysql_password", ""),
            database=getattr(settings, "mysql_database", "rag_aigc"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self):
        conn = self._pool.connection()
        return conn

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
                last_snapshot_at VARCHAR(64)
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
                open_issues INT DEFAULT 0,
                repo_created_at VARCHAR(64),
                repo_pushed_at VARCHAR(64),
                UNIQUE KEY uq_repo_snap (repo_id, snapshot_date)
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
                UNIQUE KEY uq_trend (repo_id, period, observed_date)
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
                phone VARCHAR(20) UNIQUE NOT NULL,
                username VARCHAR(64),
                hashed_password VARCHAR(256) NOT NULL,
                role ENUM('user', 'admin') DEFAULT 'user',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
                # 增量迁移：为 documents 表添加新字段（已存在则跳过）
                alter_stmts = [
                    "ALTER TABLE documents ADD COLUMN in_daily TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN in_weekly TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN in_monthly TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN local_pdf_path VARCHAR(512) DEFAULT NULL",
                ]
                for stmt in alter_stmts:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass  # 字段已存在，忽略 Duplicate column 错误
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def upsert_document(self, doc: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO documents (id, source, source_channel, title, url, summary, published_date,
                                   tags, score, raw_score, rank_in_period, indexed,
                                   in_daily, in_weekly, in_monthly, local_pdf_path, created_at)
            VALUES (%(id)s, %(source)s, %(source_channel)s, %(title)s, %(url)s, %(summary)s, %(published_date)s,
                    %(tags)s, %(score)s, %(raw_score)s, %(rank_in_period)s, %(indexed)s,
                    %(in_daily)s, %(in_weekly)s, %(in_monthly)s, %(local_pdf_path)s, %(created_at)s)
            ON DUPLICATE KEY UPDATE
                source_channel=VALUES(source_channel),
                title=VALUES(title),
                url=VALUES(url),
                summary=VALUES(summary),
                published_date=COALESCE(NULLIF(VALUES(published_date), ''), published_date),
                tags=VALUES(tags),
                score=VALUES(score),
                raw_score=VALUES(raw_score),
                rank_in_period=VALUES(rank_in_period),
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
        """更新指定文档的本地 PDF 路径（PDF 落盘后调用）。"""
        sql = "UPDATE documents SET local_pdf_path = %s WHERE id = %s"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (local_pdf_path, doc_id))
            conn.commit()
        finally:
            conn.close()

    def get_existing_document_summaries(
        self,
        *,
        ids: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        titles: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """批量查询已存在文档的 summary。

        返回的 key 形如 `id:<id>` / `url:<url>` / `title:<title>`，
        仅包含 summary 非空的记录。
        """
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
        order_by = """
            ORDER BY
                COALESCE(raw_score, score, 0) DESC,
                published_date DESC
        """

        if source_type and source_type != "all":
            sql = f"""
                SELECT * FROM documents
                WHERE source = %s
                {order_by}
                LIMIT %s
            """
            params: tuple = (source_type, limit)
        else:
            sql = f"""
                SELECT * FROM documents
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
        """获取最新的 N 条文档（按 created_at 倒序，忽略日期过滤，用于兜底）。"""
        sql = """
            SELECT * FROM documents
            ORDER BY created_at DESC
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
        """返回数据库中各来源的去重文档数量（全库统计，不受 period 过滤影响）。

        对同一来源按 url 去重（忽略日/周/月多 channel 重复写入的问题），
        确保统计卡片展示的是实际独特内容数量。
        """
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
    # Document rank snapshots (历史排行快照)
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
        """写入或更新一条排行快照记录（每天每渠道每文档唯一）。"""
        sql = """
            INSERT INTO document_rank_snapshots
                (doc_id, snapshot_date, source_channel, rank_in_period, raw_score, score, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rank_in_period=VALUES(rank_in_period),
                raw_score=VALUES(raw_score),
                score=VALUES(score)
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
        """通过 JOIN 快照表查询指定日期的文档排行数据。

        返回的每条记录包含 documents 表的元数据 + 快照表的 rank/score。
        快照表的 rank_in_period / raw_score / score 会覆盖 documents 表中的同名字段。
        """
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
                d.in_daily, d.in_weekly, d.in_monthly,
                s.source_channel,
                s.rank_in_period,
                s.raw_score,
                s.score,
                s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            WHERE {where_clause}
            ORDER BY s.raw_score DESC, s.rank_in_period ASC
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

    def get_snapshot_dates(self, limit: int = 60) -> List[str]:
        """返回有快照记录的日期列表（降序），用于前端日历高亮。"""
        sql = """
            SELECT DISTINCT snapshot_date
            FROM document_rank_snapshots
            ORDER BY snapshot_date DESC
            LIMIT %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
            conn.commit()
            return [row["snapshot_date"] for row in rows]
        finally:
            conn.close()

    def get_snapshot_source_counts(self, snapshot_date: str) -> Dict[str, int]:
        """返回指定日期各来源在快照表中的去重文档数量。

        用于前端日历切换日期后，统计卡片展示该日期的实际采集量。
        按 source（从 documents 表 JOIN 获取）分组，按 doc_id 去重。
        """
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
        """返回指定日期（和可选 channel）下快照表中的 doc_id 集合。

        用于跨天去重：例如 HackerNews 日榜排除昨日已上榜的条目。
        """
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
                full_name=VALUES(full_name),
                title=VALUES(title),
                url=VALUES(url),
                description=VALUES(description),
                language=VALUES(language),
                topics_json=VALUES(topics_json),
                created_at=VALUES(created_at),
                pushed_at=VALUES(pushed_at),
                stars=VALUES(stars),
                forks=VALUES(forks),
                watchers=VALUES(watchers),
                source_channels=VALUES(source_channels),
                last_seen_at=VALUES(last_seen_at),
                last_snapshot_at=VALUES(last_snapshot_at)
        """
        payload = dict(repo)
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
                cur.execute(sql, payload)
            conn.commit()
        finally:
            conn.close()

    def insert_github_repo_snapshot(self, snapshot: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO github_repo_snapshots (
                repo_id, snapshot_date, captured_at, stars, forks, watchers,
                open_issues, repo_created_at, repo_pushed_at
            ) VALUES (
                %(repo_id)s, %(snapshot_date)s, %(captured_at)s, %(stars)s, %(forks)s, %(watchers)s,
                %(open_issues)s, %(repo_created_at)s, %(repo_pushed_at)s
            )
            ON DUPLICATE KEY UPDATE
                captured_at=VALUES(captured_at),
                stars=VALUES(stars),
                forks=VALUES(forks),
                watchers=VALUES(watchers),
                open_issues=VALUES(open_issues),
                repo_created_at=VALUES(repo_created_at),
                repo_pushed_at=VALUES(repo_pushed_at)
        """
        payload = dict(snapshot)
        payload.setdefault("captured_at", _utcnow())
        payload.setdefault("stars", 0)
        payload.setdefault("forks", 0)
        payload.setdefault("watchers", 0)
        payload.setdefault("open_issues", 0)
        payload.setdefault("repo_created_at", "")
        payload.setdefault("repo_pushed_at", "")
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
            conn.commit()
        finally:
            conn.close()

    def upsert_github_trending_hit(self, hit: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO github_trending_hits (
                repo_id, full_name, period, language, `rank`, observed_date, captured_at
            ) VALUES (
                %(repo_id)s, %(full_name)s, %(period)s, %(language)s, %(rank)s, %(observed_date)s, %(captured_at)s
            )
            ON DUPLICATE KEY UPDATE
                full_name=VALUES(full_name),
                language=VALUES(language),
                `rank`=VALUES(`rank`),
                captured_at=VALUES(captured_at)
        """
        payload = dict(hit)
        payload.setdefault("language", "")
        payload.setdefault("rank", 999)
        payload.setdefault("captured_at", _utcnow())
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
            conn.commit()
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
                        WHEN %s = 'weekly' AND CAST(DATEDIFF(l.snapshot_date, LEFT(c.created_at, 10)) AS DOUBLE) AS DOUBLE <= 180 THEN 1.12
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

    # ------------------------------------------------------------------
    # Ingestion tasks
    # ------------------------------------------------------------------

    def create_task(self, task_name: str) -> int:
        sql = """
            INSERT INTO ingestion_tasks (task_name, status, started_at)
            VALUES (%s, 'running', %s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (task_name, _utcnow()))
                task_id = cur.lastrowid
            conn.commit()
            return task_id  # type: ignore[return-value]
        finally:
            conn.close()

    def finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: Optional[str] = None,
        item_count: int = 0,
    ) -> None:
        sql = """
            UPDATE ingestion_tasks
            SET status=%s, finished_at=%s, error_msg=%s, item_count=%s
            WHERE id=%s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (status, _utcnow(), error_msg, item_count, task_id))
            conn.commit()
        finally:
            conn.close()

    def get_latest_task(self) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT * FROM ingestion_tasks
            ORDER BY id DESC
            LIMIT 1
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_recent_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """返回最近的 N 条任务记录（按 id 倒序）。"""
        sql = "SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT %s"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                return cur.fetchall()
        finally:
            conn.close()

    def list_tasks(self, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM ingestion_tasks")
                total_row = cur.fetchone()
                total = total_row["cnt"] if total_row else 0
                cur.execute(
                    """
                    SELECT * FROM ingestion_tasks
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (page_size, offset),
                )
                rows = cur.fetchall()
            conn.commit()
            return {
                "items": list(rows),
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    def clear_all_tasks(self) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM ingestion_tasks")
                row = cur.fetchone()
                count = int(row["cnt"] if row else 0)
                cur.execute("DELETE FROM ingestion_tasks")
            conn.commit()
            return count
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Briefings
    # ------------------------------------------------------------------

    def save_briefing(self, date_str: str, content: str) -> int:
        sql = """
            INSERT INTO briefings (date, content, created_at)
            VALUES (%s, %s, %s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (date_str, content, _utcnow()))
                briefing_id = cur.lastrowid
            conn.commit()
            return briefing_id  # type: ignore[return-value]
        finally:
            conn.close()

    def get_latest_briefing(self) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT * FROM briefings
            ORDER BY id DESC
            LIMIT 1
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_briefing_by_date(self, date_str: str) -> Optional[Dict[str, Any]]:
        """按 date 字段精确查找简报（支持 cache_key 格式，如 '2026-03-08_arxiv_daily'）。"""
        sql = "SELECT * FROM briefings WHERE date = %s ORDER BY id DESC LIMIT 1"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (date_str,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_briefings(self, limit: int = 30) -> List[Dict[str, Any]]:
        """返回最近的简报列表（id + date + created_at，不含完整 content）。"""
        sql = """
            SELECT id, date, created_at,
                   SUBSTRING(content, 1, 100) AS content_preview
            FROM briefings
            ORDER BY id DESC
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
        sql = """
            INSERT INTO rag_evaluations
                (query, answer, sources_json, recall_score, citation_score,
                 subjective_score, evaluated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        query,
                        answer,
                        json.dumps(sources, ensure_ascii=False),
                        recall_score,
                        citation_score,
                        subjective_score,
                        _utcnow(),
                    ),
                )
                evaluation_id = cur.lastrowid
            conn.commit()
            return evaluation_id  # type: ignore[return-value]
        finally:
            conn.close()

    def get_eval_summary(self) -> Dict[str, Any]:
        sql = """
            SELECT
                COUNT(*) AS total,
                AVG(recall_score) AS avg_recall,
                AVG(citation_score) AS avg_citation,
                AVG(subjective_score) AS avg_subjective
            FROM rag_evaluations
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else {"total": 0}
        finally:
            conn.close()

    def list_evaluations(self, limit: int = 20) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, query, recall_score, citation_score, subjective_score, evaluated_at
            FROM rag_evaluations
            ORDER BY id DESC
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

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """根据手机号查询用户，返回 dict 或 None。"""
        sql = "SELECT id, phone, username, hashed_password, role, created_at FROM users WHERE phone = %s"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (phone,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_user(
        self,
        phone: str,
        username: str,
        hashed_password: str,
        role: str = "user",
    ) -> int:
        """创建新用户，返回新插入记录的 id。"""
        sql = """
            INSERT INTO users (phone, username, hashed_password, role)
            VALUES (%s, %s, %s, %s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (phone, username, hashed_password, role))
                new_id = cur.lastrowid
            conn.commit()
            return new_id  # type: ignore[return-value]
        finally:
            conn.close()
