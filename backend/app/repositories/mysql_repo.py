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


def _json_dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


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
                alter_stmts = [
                    "ALTER TABLE documents ADD COLUMN in_daily TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN in_weekly TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN in_monthly TINYINT DEFAULT 0",
                    "ALTER TABLE documents ADD COLUMN local_pdf_path VARCHAR(512) DEFAULT NULL",
                    # Phase 4: 认证鉴权改造 — users 表邮箱字段迁移
                    "ALTER TABLE users MODIFY phone VARCHAR(20) NULL",
                    "ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL UNIQUE AFTER phone",
                    "ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 1 AFTER email",
                    "ALTER TABLE users ADD COLUMN invite_code_used VARCHAR(64) NULL AFTER email_verified",
                ]
                for stmt in alter_stmts:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
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
                score=GREATEST(score, VALUES(score)),
                raw_score=GREATEST(raw_score, VALUES(raw_score)),
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
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM users")
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)
        finally:
            conn.close()

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
                d.in_daily, d.in_weekly, d.in_monthly,
                s.source_channel,
                s.rank_in_period,
                s.raw_score,
                s.score,
                s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
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

    def get_snapshot_dates(self, limit: int = 60) -> List[str]:
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
    # Briefing Subscriptions
    # ------------------------------------------------------------------

    def upsert_briefing_subscription(
        self, user_id: int, email: str, source: str = "all", period: str = "daily"
    ) -> Dict[str, Any]:
        """创建或激活简报订阅（若已存在则更新为 is_active=1）。"""
        sql = """
            INSERT INTO briefing_subscriptions (user_id, email, source, period, is_active, updated_at)
            VALUES (%s, %s, %s, %s, 1, NOW())
            ON DUPLICATE KEY UPDATE
                email = VALUES(email),
                is_active = 1,
                updated_at = NOW()
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id, email, source, period))
                # 查询刚刚 upsert 的记录
                cur.execute(
                    "SELECT * FROM briefing_subscriptions WHERE user_id = %s AND source = %s AND period = %s",
                    (user_id, source, period),
                )
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else {}
        finally:
            conn.close()

    def cancel_briefing_subscription(
        self, user_id: int, source: str = "all", period: str = "daily"
    ) -> bool:
        """取消简报订阅（软删除，设 is_active=0）。"""
        sql = """
            UPDATE briefing_subscriptions
            SET is_active = 0, updated_at = NOW()
            WHERE user_id = %s AND source = %s AND period = %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id, source, period))
                affected = cur.rowcount
            conn.commit()
            return affected > 0
        finally:
            conn.close()

    def get_user_briefing_subscriptions(self, user_id: int) -> List[Dict[str, Any]]:
        """获取指定用户的所有活跃订阅。"""
        sql = """
            SELECT id, source, period, is_active, created_at, updated_at
            FROM briefing_subscriptions
            WHERE user_id = %s AND is_active = 1
            ORDER BY created_at ASC
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
        finally:
            conn.close()

    def get_active_subscribers(
        self, source: str = "all", period: str = "daily"
    ) -> List[Dict[str, Any]]:
        """获取指定 source+period 的所有活跃订阅者（含 email）。"""
        sql = """
            SELECT bs.id, bs.user_id, bs.email, bs.source, bs.period
            FROM briefing_subscriptions bs
            WHERE bs.is_active = 1 AND bs.source = %s AND bs.period = %s
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (source, period))
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
        sql = "SELECT id, phone, email, username, hashed_password, role, created_at FROM users WHERE phone = %s"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (phone,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """按邮箱查询用户（邮箱不区分大小写）。"""
        sql = "SELECT id, phone, email, username, hashed_password, role, created_at FROM users WHERE email = %s"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (email.lower(),))
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

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        invite_code_used: str = "",
        role: str = "user",
        username: str = "",
    ) -> int:
        """使用邮箱创建新用户（Phase 4 邮箱注册流程）。"""
        sql = """
            INSERT INTO users (email, username, hashed_password, role, email_verified, invite_code_used)
            VALUES (%s, %s, %s, %s, 1, %s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (email.lower(), username, hashed_password, role, invite_code_used),
                )
                new_id = cur.lastrowid
            conn.commit()
            return new_id  # type: ignore[return-value]
        finally:
            conn.close()

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
