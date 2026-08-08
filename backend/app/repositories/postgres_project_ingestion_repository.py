# ruff: noqa: SIM117
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


_CANDIDATE_UPSERT_SQL = """
    INSERT INTO github_repo_candidates (
        repo_id, full_name, title, url, description, language, topics_json,
        created_at, pushed_at, stars, forks, watchers, source_channels,
        first_seen_at, last_seen_at, last_snapshot_at
    ) VALUES (
        %(repo_id)s, %(full_name)s, %(title)s, %(url)s, %(description)s,
        %(language)s, %(topics_json)s, %(created_at)s, %(pushed_at)s,
        %(stars)s, %(forks)s, %(watchers)s, %(source_channels)s,
        %(first_seen_at)s, %(last_seen_at)s, %(last_snapshot_at)s
    )
    ON CONFLICT (repo_id) DO UPDATE SET
        title=COALESCE(NULLIF(EXCLUDED.title, ''), github_repo_candidates.title),
        url=COALESCE(NULLIF(EXCLUDED.url, ''), github_repo_candidates.url),
        description=COALESCE(NULLIF(EXCLUDED.description, ''), github_repo_candidates.description),
        language=COALESCE(NULLIF(EXCLUDED.language, ''), github_repo_candidates.language),
        topics_json=COALESCE(NULLIF(EXCLUDED.topics_json, '[]'), github_repo_candidates.topics_json),
        created_at=COALESCE(NULLIF(github_repo_candidates.created_at, ''), EXCLUDED.created_at),
        pushed_at=GREATEST(COALESCE(github_repo_candidates.pushed_at, ''), COALESCE(EXCLUDED.pushed_at, '')),
        stars=GREATEST(COALESCE(github_repo_candidates.stars, 0), COALESCE(EXCLUDED.stars, 0)),
        forks=GREATEST(COALESCE(github_repo_candidates.forks, 0), COALESCE(EXCLUDED.forks, 0)),
        watchers=CASE
            WHEN %(community_metrics_complete)s IS TRUE
             AND COALESCE(EXCLUDED.last_snapshot_at, '') >= COALESCE(github_repo_candidates.last_snapshot_at, '')
            THEN EXCLUDED.watchers
            ELSE github_repo_candidates.watchers
        END,
        source_channels=EXCLUDED.source_channels,
        first_seen_at=LEAST(COALESCE(NULLIF(github_repo_candidates.first_seen_at, ''), EXCLUDED.first_seen_at), EXCLUDED.first_seen_at),
        last_seen_at=GREATEST(COALESCE(github_repo_candidates.last_seen_at, ''), COALESCE(EXCLUDED.last_seen_at, '')),
        last_snapshot_at=GREATEST(COALESCE(github_repo_candidates.last_snapshot_at, ''), COALESCE(EXCLUDED.last_snapshot_at, ''))
"""

_MARK_AVAILABLE_SQL = """
    UPDATE github_repo_candidates SET availability_status='active',
        not_found_count=0, availability_checked_at=%s
    WHERE LOWER(full_name)=LOWER(%s)
"""

_SNAPSHOT_UPSERT_SQL = """
    INSERT INTO github_repo_snapshots (
        repo_id, snapshot_date, captured_at, stars, forks, watchers,
        community_metrics_complete, open_issues, repo_created_at, repo_pushed_at
    ) VALUES (
        %(repo_id)s, %(snapshot_date)s, %(captured_at)s, %(stars)s,
        %(forks)s, %(watchers)s, %(community_metrics_complete)s,
        %(open_issues)s, %(repo_created_at)s, %(repo_pushed_at)s
    ) ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
        captured_at=GREATEST(COALESCE(github_repo_snapshots.captured_at,''), COALESCE(EXCLUDED.captured_at,'')),
        stars=GREATEST(COALESCE(github_repo_snapshots.stars,0), COALESCE(EXCLUDED.stars,0)),
        forks=CASE
            WHEN EXCLUDED.community_metrics_complete IS TRUE AND github_repo_snapshots.community_metrics_complete IS NOT TRUE THEN EXCLUDED.forks
            WHEN EXCLUDED.community_metrics_complete IS TRUE AND github_repo_snapshots.community_metrics_complete IS TRUE THEN GREATEST(COALESCE(github_repo_snapshots.forks,0),COALESCE(EXCLUDED.forks,0))
            WHEN github_repo_snapshots.community_metrics_complete IS TRUE THEN github_repo_snapshots.forks
            ELSE GREATEST(COALESCE(github_repo_snapshots.forks,0),COALESCE(EXCLUDED.forks,0)) END,
        watchers=CASE
            WHEN EXCLUDED.community_metrics_complete IS TRUE
             AND (github_repo_snapshots.community_metrics_complete IS NOT TRUE
               OR COALESCE(EXCLUDED.captured_at,'') >= COALESCE(github_repo_snapshots.captured_at,''))
            THEN EXCLUDED.watchers
            ELSE github_repo_snapshots.watchers END,
        community_metrics_complete=CASE
            WHEN github_repo_snapshots.community_metrics_complete IS TRUE THEN TRUE
            WHEN EXCLUDED.community_metrics_complete IS TRUE THEN TRUE
            WHEN github_repo_snapshots.community_metrics_complete IS FALSE
              OR EXCLUDED.community_metrics_complete IS FALSE THEN FALSE
            ELSE NULL END,
        open_issues=GREATEST(COALESCE(github_repo_snapshots.open_issues,0),COALESCE(EXCLUDED.open_issues,0)),
        repo_created_at=COALESCE(NULLIF(github_repo_snapshots.repo_created_at,''),EXCLUDED.repo_created_at),
        repo_pushed_at=GREATEST(COALESCE(github_repo_snapshots.repo_pushed_at,''),COALESCE(EXCLUDED.repo_pushed_at,''))
"""


class PostgresGitHubProjectIngestionRepository:
    """PostgreSQL writes and metric reads used by GitHub project ingestion."""

    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database

    @staticmethod
    def _resolve_repo_id(cursor: Any, repo_id: str = "", full_name: str = "") -> str:
        repo_id = (repo_id or "").strip()
        full_name = (full_name or "").strip()
        if repo_id:
            cursor.execute(
                "SELECT canonical_repo_id FROM github_repo_aliases "
                "WHERE alias_repo_id = %s LIMIT 1",
                (repo_id,),
            )
            row = cursor.fetchone()
            if row and row.get("canonical_repo_id"):
                return str(row["canonical_repo_id"])
        if full_name:
            cursor.execute(
                """
                SELECT repo_id FROM github_repo_candidates
                WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
                ORDER BY (repo_id = full_name) DESC, COALESCE(stars, 0) DESC,
                         COALESCE(last_seen_at, '') DESC
                LIMIT 1
                """,
                (full_name,),
            )
            row = cursor.fetchone()
            if row and row.get("repo_id"):
                return str(row["repo_id"])
        return full_name or repo_id

    @staticmethod
    def _upsert_alias(
        cursor: Any, *, alias_repo_id: str, canonical_repo_id: str, full_name: str
    ) -> None:
        alias_repo_id = (alias_repo_id or "").strip()
        canonical_repo_id = (canonical_repo_id or "").strip()
        full_name = (full_name or "").strip()
        if (
            not alias_repo_id
            or not canonical_repo_id
            or alias_repo_id == canonical_repo_id
        ):
            return
        now = _utcnow()
        cursor.execute(
            """
            INSERT INTO github_repo_aliases
                (alias_repo_id, canonical_repo_id, full_name, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (alias_repo_id) DO UPDATE SET
                canonical_repo_id = EXCLUDED.canonical_repo_id,
                full_name = EXCLUDED.full_name,
                updated_at = EXCLUDED.updated_at
            """,
            (alias_repo_id, canonical_repo_id, full_name, now, now),
        )

    @staticmethod
    def _candidate_payload(
        repo: dict[str, Any], *, ensure: bool = False
    ) -> dict[str, Any]:
        payload = dict(repo)
        payload["full_name"] = str(
            payload.get("full_name")
            or payload.get("title")
            or payload.get("repo_id")
            or ""
        ).strip()
        payload["repo_id"] = str(payload.get("repo_id") or payload["full_name"]).strip()
        payload.setdefault("title", payload["full_name"])
        payload.setdefault(
            "url",
            f"https://github.com/{payload['full_name']}"
            if ensure and payload["full_name"]
            else "",
        )
        payload.setdefault("description", "")
        payload.setdefault("language", "")
        payload.setdefault("topics_json", "[]")
        payload.setdefault("created_at", "")
        payload.setdefault("pushed_at", "")
        payload.setdefault("stars", 0)
        payload.setdefault("forks", 0)
        payload.setdefault("watchers", 0)
        payload["community_metrics_complete"] = bool(
            payload.get("community_metrics_complete")
        )
        payload.setdefault("source_channels", "trending_daily" if ensure else "")
        now = _utcnow()
        payload.setdefault("first_seen_at", now)
        payload.setdefault("last_seen_at", now)
        payload.setdefault("last_snapshot_at", now)
        return payload

    @staticmethod
    def _normalize_snapshot_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
        payload = dict(snapshot)
        payload.setdefault("captured_at", _utcnow())
        for key in ("stars", "forks", "watchers", "open_issues"):
            payload.setdefault(key, 0)
        completeness = payload.get("community_metrics_complete")
        payload["community_metrics_complete"] = (
            None if completeness is None else bool(completeness)
        )
        payload.setdefault("repo_created_at", "")
        payload.setdefault("repo_pushed_at", "")
        return payload

    def upsert_github_repo_candidate(self, repo: dict[str, Any]) -> None:
        payload = self._candidate_payload(repo)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                requested = payload["repo_id"]
                canonical = self._resolve_repo_id(
                    cursor, requested, payload["full_name"]
                )
                payload["repo_id"] = canonical
                cursor.execute(_CANDIDATE_UPSERT_SQL, payload)
                self._upsert_alias(
                    cursor,
                    alias_repo_id=requested,
                    canonical_repo_id=canonical,
                    full_name=payload["full_name"],
                )

    def get_github_repo_source_channels(
        self, repo_ids: list[str]
    ) -> dict[str, str]:
        if not repo_ids:
            return {}
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT repo_id, COALESCE(source_channels, '') AS channels "
                    "FROM github_repo_candidates WHERE repo_id = ANY(%s)",
                    (repo_ids,),
                )
                return {row["repo_id"]: row["channels"] for row in cursor.fetchall()}

    def ensure_github_repo_candidate(self, repo: dict[str, Any]) -> str:
        payload = self._candidate_payload(repo, ensure=True)
        sql = """
            INSERT INTO github_repo_candidates (
                repo_id, full_name, title, url, description, language, topics_json,
                created_at, pushed_at, stars, forks, watchers, source_channels,
                first_seen_at, last_seen_at, last_snapshot_at
            ) VALUES (
                %(repo_id)s, %(full_name)s, %(title)s, %(url)s, %(description)s,
                %(language)s, %(topics_json)s, %(created_at)s, %(pushed_at)s,
                %(stars)s, %(forks)s, %(watchers)s, %(source_channels)s,
                %(first_seen_at)s, %(last_seen_at)s, %(last_snapshot_at)s
            ) ON CONFLICT DO NOTHING
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                requested = payload["repo_id"]
                canonical = self._resolve_repo_id(
                    cursor, requested, payload["full_name"]
                )
                self._upsert_alias(
                    cursor,
                    alias_repo_id=requested,
                    canonical_repo_id=canonical,
                    full_name=payload["full_name"],
                )
                payload["repo_id"] = canonical
                cursor.execute(sql, payload)
        return canonical

    def mark_github_repo_available(self, full_name: str, *, checked_at: str) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_MARK_AVAILABLE_SQL, (checked_at, full_name))
                return cursor.rowcount > 0

    def record_github_repo_not_found(self, full_name: str, *, checked_at: str) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT availability_status FROM github_repo_candidates "
                    "WHERE LOWER(full_name)=LOWER(%s) FOR UPDATE",
                    (full_name,),
                )
                previous = cursor.fetchone()
                if not previous:
                    return False
                cursor.execute(
                    """
                    UPDATE github_repo_candidates
                    SET not_found_count=not_found_count+1,
                        availability_status=CASE WHEN not_found_count+1>=2
                            THEN 'not_found' ELSE availability_status END,
                        availability_checked_at=%s
                    WHERE LOWER(full_name)=LOWER(%s)
                    RETURNING availability_status
                    """,
                    (checked_at, full_name),
                )
                current = cursor.fetchone() or {}
                return (
                    previous.get("availability_status") != "not_found"
                    and current.get("availability_status") == "not_found"
                )

    def insert_github_repo_snapshot(self, snapshot: dict[str, Any]) -> None:
        payload = self._normalize_snapshot_payload(snapshot)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                payload["repo_id"] = self._resolve_repo_id(
                    cursor,
                    str(payload.get("repo_id") or ""),
                    str(payload.get("full_name") or ""),
                )
                cursor.execute(_SNAPSHOT_UPSERT_SQL, payload)

    def upsert_github_repo_metric_observations(
        self,
        observations: list[dict[str, Any]],
        *,
        checked_at: str,
    ) -> int:
        """单事务批量写入一次日刷观测：候选 upsert + 可用性恢复 + 快照插入。

        每条 observation 形如 {"candidate": {...}, "available_full_name": str,
        "snapshot": {...}}，与三个单行方法共用同一套 SQL 与归一化逻辑。
        任一观测失败整批回滚、不留中间态，调用方按整批成功/失败计数；
        返回写入的观测条数。
        """
        if not observations:
            return 0
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                candidates: list[dict[str, Any]] = []
                aliases: list[tuple[str, str, str]] = []
                availability_marks: list[tuple[str, str]] = []
                for observation in observations:
                    payload = self._candidate_payload(
                        observation.get("candidate") or {}
                    )
                    requested = payload["repo_id"]
                    canonical = self._resolve_repo_id(
                        cursor, requested, payload["full_name"]
                    )
                    payload["repo_id"] = canonical
                    candidates.append(payload)
                    aliases.append((requested, canonical, payload["full_name"]))
                    available_full_name = str(
                        observation.get("available_full_name")
                        or payload["full_name"]
                    ).strip()
                    if available_full_name:
                        availability_marks.append((checked_at, available_full_name))
                cursor.executemany(_CANDIDATE_UPSERT_SQL, candidates)
                for requested, canonical, full_name in aliases:
                    self._upsert_alias(
                        cursor,
                        alias_repo_id=requested,
                        canonical_repo_id=canonical,
                        full_name=full_name,
                    )
                if availability_marks:
                    cursor.executemany(_MARK_AVAILABLE_SQL, availability_marks)
                snapshots: list[dict[str, Any]] = []
                for observation in observations:
                    payload = self._normalize_snapshot_payload(
                        observation.get("snapshot") or {}
                    )
                    payload["repo_id"] = self._resolve_repo_id(
                        cursor,
                        str(payload.get("repo_id") or ""),
                        str(payload.get("full_name") or ""),
                    )
                    snapshots.append(payload)
                cursor.executemany(_SNAPSHOT_UPSERT_SQL, snapshots)
        return len(observations)

    def upsert_github_trending_hit(self, hit: dict[str, Any]) -> str:
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
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                payload["repo_id"] = self._resolve_repo_id(
                    cursor,
                    str(payload.get("repo_id") or ""),
                    str(payload.get("full_name") or ""),
                )
                cursor.execute(
                    """
                    INSERT INTO github_trending_hits (
                        repo_id, full_name, period, language, rank, observed_date,
                        captured_at, period_star_growth, period_growth_observed_at
                    ) VALUES (
                        %(repo_id)s, %(full_name)s, %(period)s, %(language)s, %(rank)s,
                        %(observed_date)s, %(captured_at)s, %(period_star_growth)s,
                        %(period_growth_observed_at)s
                    ) ON CONFLICT (repo_id, period, observed_date) DO UPDATE SET
                        full_name=EXCLUDED.full_name,
                        language=COALESCE(NULLIF(EXCLUDED.language,''),github_trending_hits.language),
                        rank=LEAST(COALESCE(github_trending_hits.rank,EXCLUDED.rank),EXCLUDED.rank),
                        period_star_growth=CASE WHEN EXCLUDED.period_star_growth IS NOT NULL
                            AND (github_trending_hits.period_growth_observed_at IS NULL OR EXCLUDED.period_growth_observed_at>=github_trending_hits.period_growth_observed_at)
                            THEN EXCLUDED.period_star_growth ELSE github_trending_hits.period_star_growth END,
                        period_growth_observed_at=CASE WHEN EXCLUDED.period_star_growth IS NOT NULL
                            AND (github_trending_hits.period_growth_observed_at IS NULL OR EXCLUDED.period_growth_observed_at>=github_trending_hits.period_growth_observed_at)
                            THEN EXCLUDED.period_growth_observed_at ELSE github_trending_hits.period_growth_observed_at END,
                        captured_at=GREATEST(COALESCE(github_trending_hits.captured_at,''),COALESCE(EXCLUDED.captured_at,''))
                    """,
                    payload,
                )
        return str(payload["repo_id"])

    def get_github_hot_repos(
        self, period: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        window_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 1)
        decay_exp = {"daily": 0.5, "weekly": 0.25, "monthly": 0.12}.get(period, 0.5)
        sql = """
            WITH latest AS (
                SELECT DISTINCT ON (repo_id) * FROM github_repo_snapshots
                ORDER BY repo_id, snapshot_date DESC
            ), values_with_prev AS (
                SELECT l.*,
                    (SELECT s.stars FROM github_repo_snapshots s
                     WHERE s.repo_id=l.repo_id AND TO_DATE(s.snapshot_date,'YYYY-MM-DD')<=TO_DATE(l.snapshot_date,'YYYY-MM-DD')-(%s * INTERVAL '1 day')
                     ORDER BY s.snapshot_date DESC LIMIT 1) stars_prev_window,
                    (SELECT AVG(GREATEST(n.stars-o.stars,0)) FROM github_repo_snapshots n
                     JOIN github_repo_snapshots o ON o.repo_id=n.repo_id
                       AND TO_DATE(o.snapshot_date,'YYYY-MM-DD')=TO_DATE(n.snapshot_date,'YYYY-MM-DD')-INTERVAL '1 day'
                     WHERE n.repo_id=l.repo_id AND TO_DATE(n.snapshot_date,'YYYY-MM-DD')>=TO_DATE(l.snapshot_date,'YYYY-MM-DD')-INTERVAL '14 days') baseline_daily,
                    (SELECT MIN(th.rank) FROM github_trending_hits th WHERE th.repo_id=l.repo_id
                     AND th.period=%s AND TO_DATE(th.observed_date,'YYYY-MM-DD')>=TO_DATE(l.snapshot_date,'YYYY-MM-DD')-(%s * INTERVAL '1 day')) best_trending_rank
                FROM latest l
            ), scored AS (
                SELECT c.repo_id,c.full_name,c.title,c.url,c.description,c.language,c.topics_json,
                    c.created_at,c.pushed_at,l.snapshot_date,l.captured_at,l.stars,l.forks,l.watchers,l.open_issues,
                    GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0) growth,
                    COALESCE(l.baseline_daily,0.0) baseline_daily,COALESCE(l.best_trending_rank,999) trending_rank,
                    (TO_DATE(l.snapshot_date,'YYYY-MM-DD')-TO_DATE(LEFT(c.created_at,10),'YYYY-MM-DD'))::double precision repo_age_days,
                    CASE WHEN l.best_trending_rank IS NULL THEN 0.0 ELSE 1.0/(l.best_trending_rank+1) END trending_score,
                    CASE WHEN COALESCE(l.baseline_daily,0)<=0 THEN 0.0 ELSE GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)/(l.baseline_daily*%s+1.0) END spike_ratio,
                    ((CASE WHEN %s='daily' THEN (GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)/SQRT(GREATEST(l.stars,1)))*(1.0+LEAST(COALESCE(l.baseline_daily,0),200)/400)
                           WHEN %s='weekly' THEN (GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)/GREATEST(LN(l.stars+10.0),1))*(1.0+LEAST(GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)/(COALESCE(l.baseline_daily,0)*7+1),5)/5)
                           ELSE GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)*(1.0+LEAST(GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)/(COALESCE(l.baseline_daily,0)*30+1),4)/10) END)
                     * CASE WHEN %s='daily' AND TO_DATE(l.snapshot_date,'YYYY-MM-DD')-TO_DATE(LEFT(c.created_at,10),'YYYY-MM-DD')<=90 THEN 1.25 WHEN %s='daily' THEN .72 WHEN %s='weekly' AND TO_DATE(l.snapshot_date,'YYYY-MM-DD')-TO_DATE(LEFT(c.created_at,10),'YYYY-MM-DD')<=180 THEN 1.12 WHEN %s='weekly' THEN .9 WHEN TO_DATE(l.snapshot_date,'YYYY-MM-DD')-TO_DATE(LEFT(c.created_at,10),'YYYY-MM-DD')<=365 THEN 1.05 ELSE .96 END
                     * CASE WHEN %s='daily' AND l.stars>=5000 THEN .72 WHEN %s='weekly' AND l.stars>=20000 AND GREATEST(l.stars-COALESCE(l.stars_prev_window,l.stars),0)<1000 THEN .85 ELSE 1 END
                     * (1.0+CASE WHEN l.best_trending_rank IS NULL THEN 0 ELSE 1.2/(l.best_trending_rank+2) END)
                     * (1.0/POWER(1.0+GREATEST(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-NULLIF(l.captured_at,'')::timestamptz))/3600,0),%s))) rank_score
                FROM values_with_prev l JOIN github_repo_candidates c ON c.repo_id=l.repo_id
            ) SELECT * FROM scored WHERE (%s!='daily' OR repo_age_days<=90 OR growth>=300 OR trending_rank<=10)
              ORDER BY rank_score DESC,growth DESC,stars DESC LIMIT %s
        """
        params = (
            window_days,
            period,
            window_days,
            float(window_days),
            period,
            period,
            period,
            period,
            period,
            period,
            period,
            period,
            decay_exp,
            period,
            max(0, int(limit)),
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def get_github_snapshot_count(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM github_repo_snapshots")
                row = cursor.fetchone()
                return int(row["cnt"] if row else 0)

    def list_github_project_metric_targets(
        self, *, min_stars: int = 500, limit: int = 0
    ) -> list[dict[str, Any]]:
        params: list[Any] = [min_stars]
        limit_sql = ""
        if limit and int(limit) > 0:
            limit_sql = " LIMIT %s"
            params.append(max(1, min(int(limit), 20000)))
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT repo_id,full_name,title,url,description,language,topics_json,
                              created_at,pushed_at,COALESCE(stars,0) stars,COALESCE(forks,0) forks,
                              COALESCE(watchers,0) watchers,source_channels,first_seen_at,last_seen_at,
                              last_snapshot_at,availability_status,not_found_count,availability_checked_at
                       FROM github_repo_candidates
                       WHERE COALESCE(stars,0)>=%s AND COALESCE(full_name,'')!=''
                       ORDER BY COALESCE(stars,0) DESC,full_name ASC"""
                    + limit_sql,
                    tuple(params),
                )
                return list(cursor.fetchall())

    def get_github_metric_refresh_status(
        self, *, metric_date: str, min_stars: int = 500, limit: int = 0
    ) -> dict[str, Any]:
        repo_ids = [
            str(row.get("repo_id") or "").strip()
            for row in self.list_github_project_metric_targets(
                min_stars=min_stars, limit=limit
            )
            if str(row.get("repo_id") or "").strip()
        ]
        if not repo_ids:
            return {
                "metric_date": metric_date,
                "target_count": 0,
                "snapshot_count": 0,
                "metric_count": 0,
                "oldest_captured_at": None,
            }
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT CASE WHEN s.repo_id IS NOT NULL OR c.availability_status='not_found' THEN c.repo_id END) snapshot_count,
                           COUNT(DISTINCT CASE WHEN m.repo_id IS NOT NULL OR c.availability_status='not_found' THEN c.repo_id END) metric_count,
                           MIN(s.captured_at) oldest_captured_at
                    FROM github_repo_candidates c
                    LEFT JOIN github_repo_snapshots s ON s.repo_id=c.repo_id AND s.snapshot_date=%s
                    LEFT JOIN github_repo_daily_metrics m ON m.repo_id=c.repo_id AND m.metric_date=%s
                    WHERE c.repo_id=ANY(%s)
                    """,
                    (metric_date, metric_date, repo_ids),
                )
                row = cursor.fetchone() or {}
        return {
            "metric_date": metric_date,
            "target_count": len(repo_ids),
            "snapshot_count": int(row.get("snapshot_count") or 0),
            "metric_count": int(row.get("metric_count") or 0),
            "oldest_captured_at": row.get("oldest_captured_at"),
        }

    def get_github_daily_metric_inputs(
        self,
        *,
        metric_date: str,
        previous_date: str,
        baseline_start_date: str,
        min_stars: int = 500,
        repo_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized = [
            str(value).strip() for value in (repo_ids or []) if str(value).strip()
        ]
        repo_filter = " AND s.repo_id=ANY(%s)" if normalized else ""
        params: list[Any] = [
            baseline_start_date,
            metric_date,
            baseline_start_date,
            metric_date,
            previous_date,
            metric_date,
            metric_date,
            min_stars,
        ]
        if normalized:
            params.append(normalized)
        sql = (
            """
            SELECT s.repo_id,c.full_name,s.snapshot_date metric_date,COALESCE(s.stars,0) stars,
                COALESCE(s.forks,0) forks,COALESCE(s.watchers,0) watchers,
                s.community_metrics_complete,COALESCE(s.open_issues,0) open_issues,s.repo_created_at,
                COALESCE(NULLIF(s.repo_pushed_at,''),NULLIF(c.pushed_at,'')) repo_pushed_at,
                prev.snapshot_date previous_snapshot_date,COALESCE(prev.stars,0) previous_stars,
                COALESCE(prev.forks,0) previous_forks,COALESCE(prev.watchers,0) previous_watchers,
                prev.community_metrics_complete previous_community_metrics_complete,
                daily_hit.period_star_growth trending_daily_star_growth,
                daily_hit.period_growth_observed_at trending_daily_observed_at,
                COALESCE((SELECT AVG(m.daily_star_growth) FROM github_repo_daily_metrics m
                    WHERE m.repo_id=s.repo_id AND m.metric_date>=%s AND m.metric_date<%s
                    AND m.daily_growth_source IN ('snapshot_delta','github_trending_daily')),0.0) baseline_7d,
                (SELECT COUNT(*) FROM github_repo_daily_metrics m WHERE m.repo_id=s.repo_id
                    AND m.metric_date>=%s AND m.metric_date<%s
                    AND m.daily_growth_source IN ('snapshot_delta','github_trending_daily')) baseline_sample_count
            FROM github_repo_snapshots s
            LEFT JOIN github_repo_snapshots prev ON prev.repo_id=s.repo_id AND prev.snapshot_date=%s
            LEFT JOIN github_repo_candidates c ON c.repo_id=s.repo_id
            LEFT JOIN github_trending_hits daily_hit ON daily_hit.repo_id=s.repo_id
                AND daily_hit.period='daily' AND daily_hit.observed_date=%s
                AND daily_hit.period_star_growth IS NOT NULL
            WHERE s.snapshot_date=%s AND COALESCE(s.stars,c.stars,0)>=%s
        """
            + repo_filter
            + " ORDER BY COALESCE(s.stars,0) DESC,COALESCE(c.full_name,s.repo_id) ASC"
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return list(cursor.fetchall())

    def upsert_github_daily_metrics(self, metrics: list[dict[str, Any]]) -> int:
        if not metrics:
            return 0
        normalized: list[dict[str, Any]] = []
        defaults = {
            "stars": 0,
            "forks": 0,
            "watchers": 0,
            "open_issues": 0,
            "previous_snapshot_date": None,
            "previous_stars": 0,
            "daily_star_growth": 0,
            "daily_fork_growth": 0,
            "daily_watcher_growth": 0,
            "daily_growth_source": "unavailable",
            "daily_growth_observed_at": None,
            "scale_corrected_growth_score": 0.0,
            "growth_acceleration_score": 0.0,
            "absolute_growth_score": 0.0,
            "maintenance_activity_score": 0.0,
            "community_engagement_score": 0.0,
            "hot_score": 0.0,
            "score_version": "daily_hot_v5",
        }
        for metric in metrics:
            payload = dict(metric)
            for key, value in defaults.items():
                payload.setdefault(key, value)
            payload["daily_growth_available"] = bool(
                payload.get("daily_growth_available")
            )
            payload.setdefault("updated_at", _utcnow())
            normalized.append(payload)
        sql = """
            INSERT INTO github_repo_daily_metrics (
                repo_id,metric_date,stars,forks,watchers,open_issues,previous_snapshot_date,
                previous_stars,daily_star_growth,daily_fork_growth,daily_watcher_growth,
                daily_growth_available,daily_growth_source,daily_growth_observed_at,
                scale_corrected_growth_score,growth_acceleration_score,absolute_growth_score,
                maintenance_activity_score,community_engagement_score,hot_score,score_version,updated_at
            ) VALUES (
                %(repo_id)s,%(metric_date)s,%(stars)s,%(forks)s,%(watchers)s,%(open_issues)s,
                %(previous_snapshot_date)s,%(previous_stars)s,%(daily_star_growth)s,
                %(daily_fork_growth)s,%(daily_watcher_growth)s,%(daily_growth_available)s,
                %(daily_growth_source)s,%(daily_growth_observed_at)s,%(scale_corrected_growth_score)s,
                %(growth_acceleration_score)s,%(absolute_growth_score)s,%(maintenance_activity_score)s,
                %(community_engagement_score)s,%(hot_score)s,%(score_version)s,%(updated_at)s
            ) ON CONFLICT (repo_id,metric_date) DO UPDATE SET
                stars=EXCLUDED.stars,forks=EXCLUDED.forks,watchers=EXCLUDED.watchers,
                open_issues=EXCLUDED.open_issues,previous_snapshot_date=EXCLUDED.previous_snapshot_date,
                previous_stars=EXCLUDED.previous_stars,daily_star_growth=EXCLUDED.daily_star_growth,
                daily_fork_growth=EXCLUDED.daily_fork_growth,daily_watcher_growth=EXCLUDED.daily_watcher_growth,
                daily_growth_available=EXCLUDED.daily_growth_available,daily_growth_source=EXCLUDED.daily_growth_source,
                daily_growth_observed_at=EXCLUDED.daily_growth_observed_at,
                scale_corrected_growth_score=EXCLUDED.scale_corrected_growth_score,
                growth_acceleration_score=EXCLUDED.growth_acceleration_score,
                absolute_growth_score=EXCLUDED.absolute_growth_score,
                maintenance_activity_score=EXCLUDED.maintenance_activity_score,
                community_engagement_score=EXCLUDED.community_engagement_score,
                hot_score=EXCLUDED.hot_score,score_version=EXCLUDED.score_version,updated_at=EXCLUDED.updated_at
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(sql, normalized)
        return len(normalized)
