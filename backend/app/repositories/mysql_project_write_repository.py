from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from backend.app.core.config import settings
from backend.app.core.database import DatabaseLifecycle, mysql_database


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


class MySQLProjectWriteRepository:
    """MySQL adapter for GitHub identity, ingestion, metrics, and recommendations."""

    def __init__(self, database: DatabaseLifecycle | None = None) -> None:
        self._database = database or mysql_database

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
            aggregate_key, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        cur.execute(
            """
            INSERT INTO project_catalog_outbox (
                event_id, aggregate_type, aggregate_key, operation, source_method
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), aggregate_type, key_json, operation, source_method),
        )

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
        self._record_project_catalog_change_cur(
            cur,
            aggregate_type="github_repo_aliases",
            aggregate_key={"alias_repo_id": alias_repo_id},
            source_method="_upsert_github_repo_alias_cur",
        )

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
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_repo_candidates",
                    aggregate_key={"repo_id": canonical_repo_id},
                    source_method="upsert_github_repo_candidate",
                )
            conn.commit()
        finally:
            conn.close()

    def mark_github_repo_available(self, full_name: str, *, checked_at: str) -> bool:
        """Restore a repository after a successful public GitHub API response."""
        sql = """
            UPDATE github_repo_candidates
            SET availability_status = 'active',
                not_found_count = 0,
                availability_checked_at = %s
            WHERE LOWER(full_name) = LOWER(%s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT repo_id FROM github_repo_candidates "
                    "WHERE LOWER(full_name) = LOWER(%s) LIMIT 1",
                    (full_name,),
                )
                candidate = cur.fetchone() or {}
                cur.execute(sql, (checked_at, full_name))
                changed = cur.rowcount > 0
                if candidate.get("repo_id"):
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="github_repo_candidates",
                        aggregate_key={"repo_id": str(candidate["repo_id"])},
                        source_method="mark_github_repo_available",
                    )
            conn.commit()
            return changed
        finally:
            conn.close()

    def record_github_repo_not_found(self, full_name: str, *, checked_at: str) -> bool:
        """Mark a repository unavailable after two consecutive public API 404s."""
        sql = """
            UPDATE github_repo_candidates
            SET not_found_count = not_found_count + 1,
                availability_status = CASE
                    WHEN not_found_count + 1 >= 2 THEN 'not_found'
                    ELSE availability_status
                END,
                availability_checked_at = %s
            WHERE LOWER(full_name) = LOWER(%s)
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT repo_id, availability_status FROM github_repo_candidates WHERE LOWER(full_name) = LOWER(%s) FOR UPDATE",
                    (full_name,),
                )
                previous = cur.fetchone() or {}
                if not previous:
                    conn.commit()
                    return False
                cur.execute(sql, (checked_at, full_name))
                cur.execute(
                    "SELECT availability_status FROM github_repo_candidates WHERE LOWER(full_name) = LOWER(%s)",
                    (full_name,),
                )
                current = cur.fetchone() or {}
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_repo_candidates",
                    aggregate_key={"repo_id": str(previous["repo_id"])},
                    source_method="record_github_repo_not_found",
                )
            conn.commit()
            return (
                previous.get("availability_status") != "not_found"
                and current.get("availability_status") == "not_found"
            )
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
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_repo_candidates",
                    aggregate_key={"repo_id": canonical_repo_id},
                    source_method="ensure_github_repo_candidate",
                )
            conn.commit()
            return canonical_repo_id
        except Exception:
            conn.rollback()
            raise
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
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_repo_snapshots",
                    aggregate_key={
                        "repo_id": str(payload["repo_id"]),
                        "snapshot_date": str(payload["snapshot_date"]),
                    },
                    source_method="insert_github_repo_snapshot",
                )
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
                cur.execute(
                    """
                    SELECT id
                    FROM github_trending_hits
                    WHERE repo_id = %s AND period = %s AND observed_date = %s
                    LIMIT 1
                    """,
                    (
                        payload["repo_id"],
                        payload["period"],
                        payload["observed_date"],
                    ),
                )
                row = cur.fetchone() or {}
                if row.get("id") is not None:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="github_trending_hits",
                        aggregate_key={"id": int(row["id"])},
                        source_method="upsert_github_trending_hit",
                    )
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
                last_snapshot_at,
                availability_status,
                not_found_count,
                availability_checked_at
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
                COUNT(DISTINCT CASE
                    WHEN s.repo_id IS NOT NULL OR c.availability_status = 'not_found' THEN c.repo_id
                END) AS snapshot_count,
                COUNT(DISTINCT CASE
                    WHEN m.repo_id IS NOT NULL OR c.availability_status = 'not_found' THEN c.repo_id
                END) AS metric_count,
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
                for payload in normalized:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="github_repo_daily_metrics",
                        aggregate_key={
                            "repo_id": str(payload["repo_id"]),
                            "metric_date": str(payload["metric_date"]),
                        },
                        source_method="upsert_github_daily_metrics",
                    )
            conn.commit()
            return int(affected or 0)
        finally:
            conn.close()

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
                self._record_project_catalog_change_cur(
                    cur,
                    aggregate_type="github_repo_recommendations",
                    aggregate_key={"repo_id": canonical_repo_id},
                    source_method="recommend_github_project",
                )
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
                if removed:
                    self._record_project_catalog_change_cur(
                        cur,
                        aggregate_type="github_repo_recommendations",
                        aggregate_key={"repo_id": canonical_repo_id},
                        source_method="unrecommend_github_project",
                    )
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
