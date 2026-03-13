from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.core.config import settings


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """SQLite repository for metadata, task records, briefings, eval results and GitHub hotness."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or settings.sqlite_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id          TEXT PRIMARY KEY,
                    source      TEXT,
                    source_channel TEXT,
                    title       TEXT,
                    url         TEXT,
                    summary     TEXT,
                    published_date TEXT,
                    tags        TEXT,
                    score       REAL DEFAULT 0.0,
                    raw_score   REAL DEFAULT 0.0,
                    indexed     INTEGER DEFAULT 0,
                    created_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS ingestion_tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name   TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    started_at  TEXT,
                    finished_at TEXT,
                    error_msg   TEXT,
                    item_count  INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS briefings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    date        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS rag_evaluations (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    query           TEXT NOT NULL,
                    answer          TEXT,
                    sources_json    TEXT,
                    recall_score    REAL,
                    citation_score  REAL,
                    subjective_score REAL,
                    evaluated_at    TEXT
                );

                CREATE TABLE IF NOT EXISTS github_repo_candidates (
                    repo_id          TEXT PRIMARY KEY,
                    full_name        TEXT NOT NULL,
                    title            TEXT,
                    url              TEXT,
                    description      TEXT,
                    language         TEXT,
                    topics_json      TEXT,
                    created_at       TEXT,
                    pushed_at        TEXT,
                    stars            INTEGER DEFAULT 0,
                    forks            INTEGER DEFAULT 0,
                    watchers         INTEGER DEFAULT 0,
                    source_channels  TEXT,
                    first_seen_at    TEXT,
                    last_seen_at     TEXT,
                    last_snapshot_at TEXT
                );

                CREATE TABLE IF NOT EXISTS github_repo_snapshots (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_id          TEXT NOT NULL,
                    snapshot_date    TEXT NOT NULL,
                    captured_at      TEXT NOT NULL,
                    stars            INTEGER DEFAULT 0,
                    forks            INTEGER DEFAULT 0,
                    watchers         INTEGER DEFAULT 0,
                    open_issues      INTEGER DEFAULT 0,
                    repo_created_at  TEXT,
                    repo_pushed_at   TEXT,
                    UNIQUE(repo_id, snapshot_date)
                );

                CREATE TABLE IF NOT EXISTS github_trending_hits (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_id          TEXT NOT NULL,
                    full_name        TEXT NOT NULL,
                    period           TEXT NOT NULL,
                    language         TEXT,
                    rank             INTEGER,
                    observed_date    TEXT NOT NULL,
                    captured_at      TEXT NOT NULL,
                    UNIQUE(repo_id, period, observed_date)
                );

                CREATE TABLE IF NOT EXISTS document_rank_snapshots (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id           TEXT NOT NULL,
                    snapshot_date    TEXT NOT NULL,
                    source_channel   TEXT NOT NULL,
                    rank_in_period   INTEGER,
                    raw_score        REAL,
                    score            REAL,
                    created_at       TEXT,
                    UNIQUE(doc_id, snapshot_date, source_channel)
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_date_channel
                    ON document_rank_snapshots(snapshot_date, source_channel);
                """
            )

            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            if "raw_score" not in columns:
                conn.execute(
                    "ALTER TABLE documents ADD COLUMN raw_score REAL DEFAULT 0.0"
                )
            if "source_channel" not in columns:
                conn.execute(
                    "ALTER TABLE documents ADD COLUMN source_channel TEXT DEFAULT ''"
                )
            if "rank_in_period" not in columns:
                conn.execute(
                    "ALTER TABLE documents ADD COLUMN rank_in_period INTEGER DEFAULT 9999"
                )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def upsert_document(self, doc: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO documents (id, source, source_channel, title, url, summary, published_date,
                                   tags, score, raw_score, rank_in_period, indexed, created_at)
            VALUES (:id, :source, :source_channel, :title, :url, :summary, :published_date,
                    :tags, :score, :raw_score, :rank_in_period, :indexed, :created_at)
            ON CONFLICT(id) DO UPDATE SET
                source_channel=excluded.source_channel,
                title=excluded.title,
                url=excluded.url,
                summary=excluded.summary,
                published_date=COALESCE(NULLIF(excluded.published_date, ''), documents.published_date),
                tags=excluded.tags,
                score=excluded.score,
                raw_score=excluded.raw_score,
                rank_in_period=excluded.rank_in_period,
                indexed=excluded.indexed
        """
        doc.setdefault("created_at", _utcnow())
        doc.setdefault("indexed", 0)
        doc.setdefault("score", 0.0)
        doc.setdefault("raw_score", doc.get("score", 0.0))
        doc.setdefault("source_channel", "")
        doc.setdefault("rank_in_period", 9999)
        if isinstance(doc.get("tags"), list):
            doc["tags"] = json.dumps(doc["tags"], ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(sql, doc)

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
                WHERE source = ?
                {order_by}
                LIMIT ?
            """
            params: tuple = (source_type, limit)
        else:
            sql = f"""
                SELECT * FROM documents
                {order_by}
                LIMIT ?
            """
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_latest_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最新的 N 条文档（按 created_at 倒序，忽略日期过滤，用于兜底）。"""
        sql = """
            SELECT * FROM documents
            ORDER BY created_at DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_document_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def get_source_counts(self) -> Dict[str, int]:
        """返回数据库中各来源的去重文档数量（全库统计，不受 period 过滤影响）。

        对同一来源按 url 去重（忽略日/周/月多 channel 重复写入的问题），
        确保统计卡片展示的是实际独特内容数量。
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source, COUNT(DISTINCT COALESCE(NULLIF(url,''), title)) as cnt
                FROM documents
                GROUP BY source
                """
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def clear_all_documents(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM documents")
            count = cur.fetchone()[0]
            conn.execute("DELETE FROM documents")
            return int(count)

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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id, snapshot_date, source_channel) DO UPDATE SET
                rank_in_period=excluded.rank_in_period,
                raw_score=excluded.raw_score,
                score=excluded.score
        """
        with self._connect() as conn:
            conn.execute(
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
        conditions = ["s.snapshot_date = ?"]
        params: list = [snapshot_date]

        if source_channel:
            conditions.append("s.source_channel = ?")
            params.append(source_channel)

        if source_type and source_type != "all":
            conditions.append("d.source = ?")
            params.append(source_type)

        params.append(limit)
        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                d.id, d.source, d.title, d.url, d.summary, d.published_date,
                d.tags, d.indexed, d.created_at,
                s.source_channel,
                s.rank_in_period,
                s.raw_score,
                s.score,
                s.snapshot_date
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            WHERE {where_clause}
            ORDER BY s.rank_in_period ASC, s.raw_score DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_snapshot_dates(self, limit: int = 60) -> List[str]:
        """返回有快照记录的日期列表（降序），用于前端日历高亮。"""
        sql = """
            SELECT DISTINCT snapshot_date
            FROM document_rank_snapshots
            ORDER BY snapshot_date DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [row[0] for row in rows]

    def get_snapshot_source_counts(self, snapshot_date: str) -> Dict[str, int]:
        """返回指定日期各来源在快照表中的去重文档数量。

        用于前端日历切换日期后，统计卡片展示该日期的实际采集量。
        按 source（从 documents 表 JOIN 获取）分组，按 doc_id 去重。
        """
        sql = """
            SELECT d.source, COUNT(DISTINCT s.doc_id) AS cnt
            FROM document_rank_snapshots s
            JOIN documents d ON s.doc_id = d.id
            WHERE s.snapshot_date = ?
            GROUP BY d.source
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (snapshot_date,)).fetchall()
        return {row[0]: row[1] for row in rows}

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: Optional[str] = None,
    ) -> set:
        """返回指定日期（和可选 channel）下快照表中的 doc_id 集合。

        用于跨天去重：例如 HackerNews 日榜排除昨日已上榜的条目。
        """
        conditions = ["s.snapshot_date = ?"]
        params: list = [snapshot_date]

        if source_channel:
            conditions.append("s.source_channel = ?")
            params.append(source_channel)

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT DISTINCT s.doc_id
            FROM document_rank_snapshots s
            WHERE {where_clause}
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {row[0] for row in rows}

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
                :repo_id, :full_name, :title, :url, :description, :language,
                :topics_json, :created_at, :pushed_at, :stars, :forks, :watchers,
                :source_channels, :first_seen_at, :last_seen_at, :last_snapshot_at
            )
            ON CONFLICT(repo_id) DO UPDATE SET
                full_name=excluded.full_name,
                title=excluded.title,
                url=excluded.url,
                description=excluded.description,
                language=excluded.language,
                topics_json=excluded.topics_json,
                created_at=excluded.created_at,
                pushed_at=excluded.pushed_at,
                stars=excluded.stars,
                forks=excluded.forks,
                watchers=excluded.watchers,
                source_channels=excluded.source_channels,
                last_seen_at=excluded.last_seen_at,
                last_snapshot_at=excluded.last_snapshot_at
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
        with self._connect() as conn:
            conn.execute(sql, payload)

    def insert_github_repo_snapshot(self, snapshot: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO github_repo_snapshots (
                repo_id, snapshot_date, captured_at, stars, forks, watchers,
                open_issues, repo_created_at, repo_pushed_at
            ) VALUES (
                :repo_id, :snapshot_date, :captured_at, :stars, :forks, :watchers,
                :open_issues, :repo_created_at, :repo_pushed_at
            )
            ON CONFLICT(repo_id, snapshot_date) DO UPDATE SET
                captured_at=excluded.captured_at,
                stars=excluded.stars,
                forks=excluded.forks,
                watchers=excluded.watchers,
                open_issues=excluded.open_issues,
                repo_created_at=excluded.repo_created_at,
                repo_pushed_at=excluded.repo_pushed_at
        """
        payload = dict(snapshot)
        payload.setdefault("captured_at", _utcnow())
        payload.setdefault("stars", 0)
        payload.setdefault("forks", 0)
        payload.setdefault("watchers", 0)
        payload.setdefault("open_issues", 0)
        payload.setdefault("repo_created_at", "")
        payload.setdefault("repo_pushed_at", "")
        with self._connect() as conn:
            conn.execute(sql, payload)

    def upsert_github_trending_hit(self, hit: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO github_trending_hits (
                repo_id, full_name, period, language, rank, observed_date, captured_at
            ) VALUES (
                :repo_id, :full_name, :period, :language, :rank, :observed_date, :captured_at
            )
            ON CONFLICT(repo_id, period, observed_date) DO UPDATE SET
                full_name=excluded.full_name,
                language=excluded.language,
                rank=excluded.rank,
                captured_at=excluded.captured_at
        """
        payload = dict(hit)
        payload.setdefault("language", "")
        payload.setdefault("rank", 999)
        payload.setdefault("captured_at", _utcnow())
        with self._connect() as conn:
            conn.execute(sql, payload)

    def get_github_hot_repos(
        self, period: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        window_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 1)
        decay_exp = {"daily": 0.5, "weekly": 0.25, "monthly": 0.12}.get(period, 0.5)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
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
                              AND s2.snapshot_date <= date(l.snapshot_date, '-{window_days} day')
                            ORDER BY s2.snapshot_date DESC
                            LIMIT 1
                        ) AS stars_prev_window,
                        (
                            SELECT AVG(delta_stars)
                            FROM (
                                SELECT MAX(s_new.stars - s_old.stars, 0) AS delta_stars
                                FROM github_repo_snapshots s_new
                                JOIN github_repo_snapshots s_old
                                  ON s_new.repo_id = s_old.repo_id
                                 AND s_old.snapshot_date = date(s_new.snapshot_date, '-1 day')
                                WHERE s_new.repo_id = l.repo_id
                                  AND s_new.snapshot_date >= date(l.snapshot_date, '-14 day')
                                GROUP BY s_new.snapshot_date
                            ) baseline
                        ) AS baseline_daily,
                        (
                            SELECT MIN(rank)
                            FROM github_trending_hits th
                            WHERE th.repo_id = l.repo_id
                              AND th.period = ?
                              AND th.observed_date >= date(l.snapshot_date, '-{window_days} day')
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
                    COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) AS growth,
                    COALESCE(l.baseline_daily, 0.0) AS baseline_daily,
                    COALESCE(l.best_trending_rank, 999) AS trending_rank,
                    CAST((julianday(l.snapshot_date) - julianday(substr(c.created_at, 1, 10))) AS REAL) AS repo_age_days,
                    CASE
                        WHEN l.best_trending_rank IS NULL THEN 0.0
                        ELSE 1.0 / (l.best_trending_rank + 1)
                    END AS trending_score,
                    (
                        (
                            CASE
                                WHEN ? = 'daily' THEN
                                    (COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / sqrt(COALESCE(NULLIF(l.stars, 0), 1)))
                                    * (1.0 + MIN(COALESCE(l.baseline_daily, 0.0), 200.0) / 400.0)
                                WHEN ? = 'weekly' THEN
                                    (COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / MAX(log(COALESCE(l.stars, 0) + 10.0), 1.0))
                                    * (1.0 + MIN(COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / (COALESCE(l.baseline_daily, 0.0) * 7.0 + 1.0), 5.0) / 5.0)
                                ELSE
                                    COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0)
                                    * (1.0 + MIN(COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / (COALESCE(l.baseline_daily, 0.0) * 30.0 + 1.0), 4.0) / 10.0)
                            END
                        )
                        * CASE
                            WHEN ? = 'daily' AND CAST((julianday(l.snapshot_date) - julianday(substr(c.created_at, 1, 10))) AS REAL) <= 90 THEN 1.25
                            WHEN ? = 'daily' THEN 0.72
                            WHEN ? = 'weekly' AND CAST((julianday(l.snapshot_date) - julianday(substr(c.created_at, 1, 10))) AS REAL) <= 180 THEN 1.12
                            WHEN ? = 'weekly' THEN 0.9
                            WHEN CAST((julianday(l.snapshot_date) - julianday(substr(c.created_at, 1, 10))) AS REAL) <= 365 THEN 1.05
                            ELSE 0.96
                        END
                        * CASE
                            WHEN ? = 'daily' AND l.stars >= 5000 THEN 0.72
                            WHEN ? = 'weekly' AND l.stars >= 20000 AND COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) < 1000 THEN 0.85
                            ELSE 1.0
                        END
                        * (1.0 + CASE WHEN l.best_trending_rank IS NULL THEN 0.0 ELSE 1.2 / (l.best_trending_rank + 2) END)
                        * (1.0 / POWER(1.0 + MAX((julianday('now') - julianday(l.captured_at)) * 24.0, 0.0), ?))
                    ) AS rank_score,
                    CASE
                        WHEN COALESCE(l.baseline_daily, 0.0) <= 0 THEN 0.0
                        ELSE COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) / (l.baseline_daily * ? + 1.0)
                    END AS spike_ratio
                FROM latest_with_prev l
                JOIN github_repo_candidates c ON c.repo_id = l.repo_id
                WHERE (
                    ? != 'daily'
                    OR CAST((julianday(l.snapshot_date) - julianday(substr(c.created_at, 1, 10))) AS REAL) <= 90
                    OR COALESCE(MAX(l.stars - COALESCE(l.stars_prev_window, l.stars), 0), 0) >= 300
                    OR COALESCE(l.best_trending_rank, 999) <= 10
                )
                ORDER BY rank_score DESC, growth DESC, l.stars DESC
                LIMIT ?
                """,
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
            ).fetchall()
        return [dict(r) for r in rows]

    def get_github_snapshot_count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM github_repo_snapshots"
            ).fetchone()[0]

    # ------------------------------------------------------------------
    # Ingestion tasks
    # ------------------------------------------------------------------

    def create_task(self, task_name: str) -> int:
        sql = """
            INSERT INTO ingestion_tasks (task_name, status, started_at)
            VALUES (?, 'running', ?)
        """
        with self._connect() as conn:
            cur = conn.execute(sql, (task_name, _utcnow()))
            return cur.lastrowid  # type: ignore[return-value]

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
            SET status=?, finished_at=?, error_msg=?, item_count=?
            WHERE id=?
        """
        with self._connect() as conn:
            conn.execute(sql, (status, _utcnow(), error_msg, item_count, task_id))

    def get_latest_task(self) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT * FROM ingestion_tasks
            ORDER BY id DESC
            LIMIT 1
        """
        with self._connect() as conn:
            row = conn.execute(sql).fetchone()
        return dict(row) if row else None

    def list_tasks(self, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM ingestion_tasks").fetchone()[0]
            rows = conn.execute(
                """
                SELECT * FROM ingestion_tasks
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def clear_all_tasks(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM ingestion_tasks")
            count = cur.fetchone()[0]
            conn.execute("DELETE FROM ingestion_tasks")
            return int(count)

    # ------------------------------------------------------------------
    # Briefings
    # ------------------------------------------------------------------

    def save_briefing(self, date_str: str, content: str) -> int:
        sql = """
            INSERT INTO briefings (date, content, created_at)
            VALUES (?, ?, ?)
        """
        with self._connect() as conn:
            cur = conn.execute(sql, (date_str, content, _utcnow()))
            return cur.lastrowid  # type: ignore[return-value]

    def get_latest_briefing(self) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT * FROM briefings
            ORDER BY id DESC
            LIMIT 1
        """
        with self._connect() as conn:
            row = conn.execute(sql).fetchone()
        return dict(row) if row else None

    def get_briefing_by_date(self, date_str: str) -> Optional[Dict[str, Any]]:
        """按 date 字段精确查找简报（支持 cache_key 格式，如 '2026-03-08_arxiv_daily'）。"""
        sql = "SELECT * FROM briefings WHERE date = ? ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, (date_str,)).fetchone()
        return dict(row) if row else None

    def list_briefings(self, limit: int = 30) -> List[Dict[str, Any]]:
        """返回最近的简报列表（id + date + created_at，不含完整 content）。"""
        sql = """
            SELECT id, date, created_at,
                   SUBSTR(content, 1, 100) AS content_preview
            FROM briefings
            ORDER BY id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

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
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            cur = conn.execute(
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
            return cur.lastrowid  # type: ignore[return-value]

    def get_eval_summary(self) -> Dict[str, Any]:
        sql = """
            SELECT
                COUNT(*) AS total,
                AVG(recall_score) AS avg_recall,
                AVG(citation_score) AS avg_citation,
                AVG(subjective_score) AS avg_subjective
            FROM rag_evaluations
        """
        with self._connect() as conn:
            row = conn.execute(sql).fetchone()
        return dict(row) if row else {"total": 0}

    def list_evaluations(self, limit: int = 20) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, query, recall_score, citation_score, subjective_score, evaluated_at
            FROM rag_evaluations
            ORDER BY id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]
