# ruff: noqa: SIM117
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.domain.github_heat import (
    MAX_GAP_DAYS,
    ROLLING_WINDOW_HOURS,
    SCORE_VERSION as HEAT_SCORE_VERSION,
    TOP_STREAK_LOOKBACK_DAYS,
    TOP_STREAK_PRIOR_DAYS_CAP,
    TOP_STREAK_RANK_LIMIT,
    TOP_STREAK_RESET_DAYS,
    heat_growth_sql,
)
from backend.app.monitoring import live_stats_broadcaster

logger = logging.getLogger(__name__)


class GitHubIdentityConflict(ValueError):
    """An observation belongs to a different repository behind a reused name."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


_CANDIDATE_UPSERT_SQL = """
    INSERT INTO github_repo_candidates (
        repo_id, full_name, title, url, description, language, license_spdx_id,
        topics_json,
        created_at, pushed_at, stars, forks, watchers, source_channels,
        first_seen_at, last_seen_at, last_snapshot_at
    ) VALUES (
        %(repo_id)s, %(full_name)s, %(title)s, %(url)s, %(description)s,
        %(language)s, %(license_spdx_id)s, %(topics_json)s, %(created_at)s, %(pushed_at)s,
        %(stars)s, %(forks)s, %(watchers)s, %(source_channels)s,
        %(first_seen_at)s, %(last_seen_at)s, %(last_snapshot_at)s
    )
    ON CONFLICT (repo_id) DO UPDATE SET
        title=COALESCE(NULLIF(EXCLUDED.title, ''), github_repo_candidates.title),
        url=COALESCE(NULLIF(EXCLUDED.url, ''), github_repo_candidates.url),
        description=COALESCE(NULLIF(EXCLUDED.description, ''), github_repo_candidates.description),
        language=COALESCE(NULLIF(EXCLUDED.language, ''), github_repo_candidates.language),
        license_spdx_id=COALESCE(NULLIF(EXCLUDED.license_spdx_id, ''), github_repo_candidates.license_spdx_id),
        topics_json=COALESCE(NULLIF(EXCLUDED.topics_json, '[]'), github_repo_candidates.topics_json),
        -- 建仓时间以 GitHub API 为准：日期不同即纠正，同日只接受更精确的时间戳
        created_at=CASE
            WHEN NULLIF(EXCLUDED.created_at, '') IS NULL THEN github_repo_candidates.created_at
            WHEN NULLIF(github_repo_candidates.created_at, '') IS NULL
                OR LEFT(github_repo_candidates.created_at, 10) <> LEFT(EXCLUDED.created_at, 10)
                OR LENGTH(EXCLUDED.created_at) > LENGTH(github_repo_candidates.created_at)
            THEN EXCLUDED.created_at
            ELSE github_repo_candidates.created_at
        END,
        pushed_at=GREATEST(COALESCE(github_repo_candidates.pushed_at, ''), COALESCE(EXCLUDED.pushed_at, '')),
        stars=CASE WHEN %(community_metrics_complete)s IS TRUE THEN
            CASE WHEN COALESCE(EXCLUDED.last_snapshot_at, '') >= COALESCE(github_repo_candidates.last_snapshot_at, '')
                THEN EXCLUDED.stars ELSE github_repo_candidates.stars END
            ELSE GREATEST(github_repo_candidates.stars, EXCLUDED.stars) END,
        forks=CASE WHEN %(community_metrics_complete)s IS TRUE THEN
            CASE WHEN COALESCE(EXCLUDED.last_snapshot_at, '') >= COALESCE(github_repo_candidates.last_snapshot_at, '')
                THEN EXCLUDED.forks ELSE github_repo_candidates.forks END
            ELSE GREATEST(github_repo_candidates.forks, EXCLUDED.forks) END,
        watchers=CASE
            WHEN %(community_metrics_complete)s IS TRUE THEN
                CASE WHEN COALESCE(EXCLUDED.last_snapshot_at, '') >= COALESCE(github_repo_candidates.last_snapshot_at, '')
                    THEN EXCLUDED.watchers ELSE github_repo_candidates.watchers END
            ELSE github_repo_candidates.watchers
        END,
        source_channels=(
            SELECT COALESCE(string_agg(DISTINCT part, ',' ORDER BY part), '')
            FROM unnest(string_to_array(
                concat_ws(',', github_repo_candidates.source_channels, EXCLUDED.source_channels),
                ','
            )) AS part
            WHERE part <> ''
        ),
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
        %(repo_id)s::character varying, %(snapshot_date)s, %(captured_at)s, %(stars)s,
        %(forks)s, %(watchers)s, %(community_metrics_complete)s,
        %(open_issues)s,
        COALESCE(
            NULLIF(%(repo_created_at)s::character varying, ''),
            (SELECT NULLIF(c.created_at, '') FROM github_repo_candidates c
             WHERE c.repo_id = %(repo_id)s::character varying),
            ''
        ),
        %(repo_pushed_at)s
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
        repo_created_at=CASE
            WHEN NULLIF(%(repo_created_at)s::character varying, '') IS NULL
            THEN COALESCE(NULLIF(github_repo_snapshots.repo_created_at,''),EXCLUDED.repo_created_at)
            WHEN NULLIF(EXCLUDED.repo_created_at, '') IS NULL THEN github_repo_snapshots.repo_created_at
            WHEN NULLIF(github_repo_snapshots.repo_created_at, '') IS NULL
                OR LEFT(github_repo_snapshots.repo_created_at,10)<>LEFT(EXCLUDED.repo_created_at,10)
                OR LENGTH(EXCLUDED.repo_created_at)>LENGTH(github_repo_snapshots.repo_created_at)
            THEN EXCLUDED.repo_created_at ELSE github_repo_snapshots.repo_created_at END,
        repo_pushed_at=GREATEST(COALESCE(github_repo_snapshots.repo_pushed_at,''),COALESCE(EXCLUDED.repo_pushed_at,''))
"""


_STAR_OBSERVATION_UPSERT_SQL = """
    INSERT INTO github_repo_star_observations (repo_id, observed_at, stars, forks, watchers)
    VALUES (%(repo_id)s, %(observed_at)s, %(stars)s, %(forks)s, %(watchers)s)
    ON CONFLICT (repo_id, observed_at) DO UPDATE SET
        stars=GREATEST(github_repo_star_observations.stars, EXCLUDED.stars),
        forks=GREATEST(github_repo_star_observations.forks, EXCLUDED.forks),
        watchers=COALESCE(EXCLUDED.watchers, github_repo_star_observations.watchers)
"""

# 滚动 24 小时星增只需窗口起点前的一条观测；多留两天给采集中断兜底。
STAR_OBSERVATION_RETENTION_HOURS = 72

# 疑似诱饵仓库隔离名单（迁移 0082）的阈值，规则见 _GITHUB_QUARANTINE_SQL。
GITHUB_QUARANTINE_SURGE_SCORE = 0.8
GITHUB_QUARANTINE_NAME_MIN_OWNERS = 3
GITHUB_QUARANTINE_NAME_MIN_REMOVED = 2

# 整体重算隔离名单，一条语句内算出新名单、放出不再命中的、补进新命中的：
#   coordinated_surge  任一天刷星嫌疑分达阈值且带 coordinated_creation 信号；
#   name_reuse         同一仓库名（忽略大小写）从第一个被 GitHub 删掉的副本建仓当天起
#                      建的那一批，跨足够多账号、已删足够多且占一半以上，整批隔离；
#                      更早建的同名仓库视为原作保留。
# 只看 canonical 行（改名留下的别名行本就不公开）；一个仓库只记一条理由，刷星优先。
# added 拿语句开始时的旧名单比对（同一语句里的查询看不到本语句的写入）。
_GITHUB_QUARANTINE_SQL = """
    WITH coordinated AS (
        SELECT DISTINCT m.repo_id
        FROM github_repo_daily_metrics m
        WHERE m.growth_suspicion_score >= %(surge_score)s
          AND m.growth_suspicion_signals LIKE %(surge_signal)s
    ), named AS (
        SELECT c.repo_id,
               LOWER(split_part(c.full_name, '/', 2)) AS name,
               LOWER(split_part(c.full_name, '/', 1)) AS owner,
               c.availability_status,
               CASE WHEN c.created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                    THEN LEFT(c.created_at, 10) END AS created_day
        FROM github_repo_candidates c
        WHERE NOT EXISTS (SELECT 1 FROM github_repo_aliases ga
                          WHERE ga.alias_repo_id = c.repo_id AND ga.canonical_repo_id <> c.repo_id)
    ), wave AS (
        SELECT n.repo_id, n.name, n.owner, n.availability_status
        FROM named n
        JOIN (SELECT name, MIN(created_day) AS since FROM named
              WHERE availability_status = 'not_found' AND created_day IS NOT NULL
              GROUP BY name) first_removed USING (name)
        WHERE n.created_day >= first_removed.since
    ), bait_names AS (
        SELECT name FROM wave GROUP BY name
        HAVING COUNT(DISTINCT owner) >= %(name_min_owners)s
           AND COUNT(*) FILTER (WHERE availability_status = 'not_found') >= %(name_min_removed)s
           AND 2 * COUNT(*) FILTER (WHERE availability_status = 'not_found') >= COUNT(*)
    ), next_quarantine AS (
        SELECT repo_id, 'coordinated_surge' AS reason FROM coordinated
        UNION ALL
        SELECT w.repo_id, 'name_reuse' FROM wave w JOIN bait_names USING (name)
        WHERE NOT EXISTS (SELECT 1 FROM coordinated co WHERE co.repo_id = w.repo_id)
    ), released AS (
        DELETE FROM github_repo_quarantine q
        WHERE NOT EXISTS (SELECT 1 FROM next_quarantine nq WHERE nq.repo_id = q.repo_id)
        RETURNING q.repo_id
    ), upserted AS (
        INSERT INTO github_repo_quarantine (repo_id, reason)
        SELECT repo_id, reason FROM next_quarantine
        ON CONFLICT (repo_id) DO UPDATE SET reason = EXCLUDED.reason
        WHERE github_repo_quarantine.reason <> EXCLUDED.reason
    )
    SELECT (SELECT COUNT(*) FROM next_quarantine) AS quarantined,
           (SELECT COUNT(*) FROM next_quarantine nq
            WHERE NOT EXISTS (SELECT 1 FROM github_repo_quarantine q
                              WHERE q.repo_id = nq.repo_id)) AS added,
           (SELECT COUNT(*) FROM released) AS released
"""


def _star_observation_payload(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """由已归一的快照载荷派生一条星数观测；时间或星数不可用时跳过。

    观测只是滚动窗口的原料，宁缺毋滥：解析失败绝不能连累同事务的快照写入。
    """
    stars = int(snapshot.get("stars") or 0)
    if stars <= 0:
        return None
    try:
        observed_at = datetime.fromisoformat(
            str(snapshot.get("captured_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    complete = snapshot.get("community_metrics_complete") is True
    return {
        "repo_id": snapshot["repo_id"],
        "observed_at": observed_at,
        "stars": stars,
        "forks": int(snapshot.get("forks") or 0),
        "watchers": int(snapshot.get("watchers") or 0) if complete else None,
    }


class PostgresGitHubProjectIngestionRepository:
    """PostgreSQL writes and metric reads used by GitHub project ingestion."""

    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database

    @staticmethod
    def _lock_identities(cursor: Any, *names: str) -> None:
        # Serialize discovery of the same previously unknown identity across
        # independent writers; row locks cannot lock a row that does not exist.
        for name in sorted({name.strip().lower() for name in names if name.strip()}):
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("github-identity:" + name,))

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
        payload.setdefault("license_spdx_id", "")
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

    # ---------- 改名归一化（zombie 项目自愈） ----------

    # 改名合并时随迁的时序子表：同键冲突保留 captured_at/updated_at 较新的一方
    _SERIES_CHILD_TABLES = (
        ("github_repo_snapshots", ("snapshot_date",), "captured_at"),
        ("github_repo_daily_metrics", ("metric_date",), "updated_at"),
        ("github_trending_hits", ("period", "observed_date"), "captured_at"),
        ("github_repo_star_observations", ("observed_at",), "observed_at"),
    )
    # 单行子表：canonical 已有行则弃用旧行副本，否则整体迁移
    _SINGLETON_CHILD_TABLES = (
        "github_project_logos",
        "github_repo_recommendations",
        "github_project_semantic_sources",
    )

    @staticmethod
    def _find_candidate_row_by_name(
        cursor: Any, full_name: str
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT repo_id, full_name, title, url, description, language, topics_json,
                   created_at, source_channels, first_seen_at, availability_status
            FROM github_repo_candidates
            WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(%s))
            ORDER BY (repo_id = full_name) DESC, COALESCE(stars, 0) DESC
            LIMIT 1
            """,
            (full_name,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _node_alias_ids(cursor: Any, canonical_repo_id: str) -> set[str]:
        """canonical 名下所有 node 形态别名（不含名称型 alias）。"""
        cursor.execute(
            "SELECT alias_repo_id FROM github_repo_aliases "
            "WHERE canonical_repo_id=%s AND POSITION('/' IN alias_repo_id)=0",
            (canonical_repo_id,),
        )
        nodes = {str(row["alias_repo_id"]) for row in cursor.fetchall()}
        if "/" not in canonical_repo_id:
            nodes.add(canonical_repo_id)
        # REST database IDs and GraphQL node IDs are different representations;
        # a legacy numeric alias alone does not contradict an incoming node ID.
        return {node for node in nodes if not node.isdecimal()}

    @staticmethod
    def _apply_not_found_observation(
        cursor: Any, full_name: str, checked_at: str
    ) -> tuple[bool, bool]:
        """在既有事务内累计一次 404 观测；返回 (已处理, 本次新转 not_found)。

        与公开方法 record_github_repo_not_found 共用同一 UPDATE 语义，
        供批量观测事务复用而不嵌套开事务。
        """
        cursor.execute(
            "SELECT availability_status FROM github_repo_candidates "
            "WHERE LOWER(full_name)=LOWER(%s) FOR UPDATE",
            (full_name,),
        )
        previous = cursor.fetchone()
        if not previous:
            return False, False
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
        newly = (
            previous.get("availability_status") != "not_found"
            and current.get("availability_status") == "not_found"
        )
        return True, newly

    @classmethod
    def _move_series_child_rows(
        cls, cursor: Any, *, old_repo_id: str, new_repo_id: str
    ) -> None:
        for table, key_columns, fresh_column in cls._SERIES_CHILD_TABLES:
            key_join = " AND ".join(f"b.{column} = a.{column}" for column in key_columns)
            # 旧侧不新于新侧的同键行直接弃用
            cursor.execute(
                f"DELETE FROM {table} a USING {table} b "
                f"WHERE a.repo_id=%s AND b.repo_id=%s AND {key_join} "
                f"AND COALESCE(a.{fresh_column}::text,'') <= COALESCE(b.{fresh_column}::text,'')",
                (old_repo_id, new_repo_id),
            )
            # 新侧更旧的同键行让位给即将迁入的旧侧副本
            cursor.execute(
                f"DELETE FROM {table} a USING {table} b "
                f"WHERE a.repo_id=%s AND b.repo_id=%s AND {key_join} "
                f"AND COALESCE(a.{fresh_column}::text,'') < COALESCE(b.{fresh_column}::text,'')",
                (new_repo_id, old_repo_id),
            )
            cursor.execute(
                f"UPDATE {table} SET repo_id=%s WHERE repo_id=%s",
                (new_repo_id, old_repo_id),
            )

    @classmethod
    def _move_singleton_child_rows(
        cls, cursor: Any, *, old_repo_id: str, new_repo_id: str
    ) -> None:
        for table in cls._SINGLETON_CHILD_TABLES:
            cursor.execute(
                f"DELETE FROM {table} a USING {table} b "
                f"WHERE a.repo_id=%s AND b.repo_id=%s",
                (old_repo_id, new_repo_id),
            )
            cursor.execute(
                f"UPDATE {table} SET repo_id=%s WHERE repo_id=%s",
                (new_repo_id, old_repo_id),
            )

    @staticmethod
    def _move_enrichment_row(
        cursor: Any, *, old_repo_id: str, new_repo_id: str
    ) -> None:
        """画像行迁移：任一侧 status='succeeded' 优先保留，避免已成品画像被覆盖。"""
        cursor.execute(
            "SELECT status FROM github_repo_enrichments WHERE repo_id=%s",
            (new_repo_id,),
        )
        new_row = cursor.fetchone()
        cursor.execute(
            "SELECT status FROM github_repo_enrichments WHERE repo_id=%s",
            (old_repo_id,),
        )
        old_row = cursor.fetchone()
        if not old_row:
            return
        keep_old = old_row.get("status") == "succeeded" and (
            not new_row or new_row.get("status") != "succeeded"
        )
        if keep_old:
            cursor.execute(
                "DELETE FROM github_repo_enrichments WHERE repo_id=%s", (new_repo_id,)
            )
            cursor.execute(
                "UPDATE github_repo_enrichments SET repo_id=%s WHERE repo_id=%s",
                (new_repo_id, old_repo_id),
            )
        else:
            cursor.execute(
                "DELETE FROM github_repo_enrichments WHERE repo_id=%s", (old_repo_id,)
            )

    @staticmethod
    def _move_favorite_rows(
        cursor: Any, *, old_repo_id: str, new_repo_id: str
    ) -> None:
        """用户收藏软引用随迁（project_favorites 无 FK，靠合并时显式改指）。

        同一用户同时收藏过新旧两行时，旧侧让位删除以满足唯一约束。
        """
        cursor.execute(
            "DELETE FROM project_favorites a USING project_favorites b "
            "WHERE a.project_source='github' AND b.project_source='github' "
            "AND a.project_id=%s AND b.project_id=%s AND a.user_id=b.user_id",
            (old_repo_id, new_repo_id),
        )
        cursor.execute(
            "UPDATE project_favorites SET project_id=%s "
            "WHERE project_source='github' AND project_id=%s",
            (new_repo_id, old_repo_id),
        )

    @staticmethod
    def _merge_channel_strings(*values: str) -> str:
        parts: list[str] = []
        for value in values:
            for part in str(value or "").split(","):
                part = part.strip()
                if part and part not in parts:
                    parts.append(part)
        return ",".join(parts)

    @classmethod
    def _merge_candidate_scalars(
        cls,
        cursor: Any,
        *,
        keep_repo_id: str,
        drop_row: dict[str, Any],
        checked_at: str,
    ) -> None:
        cursor.execute(
            "SELECT source_channels, first_seen_at FROM github_repo_candidates "
            "WHERE repo_id=%s",
            (keep_repo_id,),
        )
        keep_row = cursor.fetchone() or {}
        merged_channels = cls._merge_channel_strings(
            str(keep_row.get("source_channels") or ""),
            str(drop_row.get("source_channels") or ""),
        )
        seen_candidates = [
            value
            for value in (
                str(keep_row.get("first_seen_at") or ""),
                str(drop_row.get("first_seen_at") or ""),
            )
            if value
        ]
        first_seen = min(seen_candidates) if seen_candidates else ""
        cursor.execute(
            """
            UPDATE github_repo_candidates c SET
                title=COALESCE(NULLIF(c.title,''), o.title),
                url=COALESCE(NULLIF(c.url,''), o.url),
                description=COALESCE(NULLIF(c.description,''), o.description),
                language=COALESCE(NULLIF(c.language,''), o.language),
                license_spdx_id=COALESCE(NULLIF(c.license_spdx_id,''), o.license_spdx_id),
                topics_json=COALESCE(NULLIF(c.topics_json,'[]'), o.topics_json),
                created_at=COALESCE(NULLIF(c.created_at,''), o.created_at),
                pushed_at=GREATEST(COALESCE(c.pushed_at,''), COALESCE(o.pushed_at,'')),
                stars=GREATEST(COALESCE(c.stars,0), COALESCE(o.stars,0)),
                forks=GREATEST(COALESCE(c.forks,0), COALESCE(o.forks,0)),
                watchers=GREATEST(COALESCE(c.watchers,0), COALESCE(o.watchers,0)),
                source_channels=%s,
                first_seen_at=%s,
                last_seen_at=GREATEST(COALESCE(c.last_seen_at,''), COALESCE(o.last_seen_at,'')),
                last_snapshot_at=GREATEST(COALESCE(c.last_snapshot_at,''), COALESCE(o.last_snapshot_at,'')),
                availability_status='active', not_found_count=0, availability_checked_at=%s
            FROM github_repo_candidates o
            WHERE c.repo_id=%s AND o.repo_id=%s
            """,
            (
                merged_channels,
                first_seen,
                checked_at or _utcnow(),
                keep_repo_id,
                drop_row["repo_id"],
            ),
        )

    @staticmethod
    def _clone_candidate_row(
        cursor: Any,
        *,
        old_row: dict[str, Any],
        new_full_name: str,
        checked_at: str,
    ) -> None:
        """把旧行克隆为新 full_name 身份（name 型 PK 改名的前半步）。"""
        cursor.execute(
            """
            INSERT INTO github_repo_candidates (
                repo_id, full_name, title, url, description, language, license_spdx_id,
                topics_json,
                created_at, pushed_at, stars, forks, watchers, source_channels,
                first_seen_at, last_seen_at, last_snapshot_at,
                availability_status, not_found_count, availability_checked_at
            )
            SELECT %s, %s,
                   CASE WHEN LOWER(COALESCE(title,''))=LOWER(%s) OR COALESCE(title,'')=''
                        THEN %s ELSE title END,
                   url, description, language, license_spdx_id, topics_json, created_at, pushed_at,
                   stars, forks, watchers, source_channels,
                   first_seen_at, last_seen_at, last_snapshot_at,
                   'active', 0, %s
            FROM github_repo_candidates WHERE repo_id=%s
            """,
            (
                new_full_name,
                new_full_name,
                str(old_row.get("full_name") or ""),
                new_full_name,
                checked_at or _utcnow(),
                str(old_row["repo_id"]),
            ),
        )

    @staticmethod
    def _rename_candidate_row(
        cursor: Any,
        *,
        repo_id: str,
        old_full_name: str,
        new_full_name: str,
        checked_at: str,
    ) -> None:
        """就地改名：repo_id 不动，full_name/title 归一到新名并复位可用性。"""
        cursor.execute(
            """
            UPDATE github_repo_candidates SET
                full_name=%s,
                title=CASE
                    WHEN LOWER(COALESCE(title,''))=LOWER(%s) OR COALESCE(title,'')=''
                    THEN %s ELSE title END,
                availability_status='active', not_found_count=0, availability_checked_at=%s
            WHERE repo_id=%s
            """,
            (
                new_full_name,
                old_full_name,
                new_full_name,
                checked_at or _utcnow(),
                repo_id,
            ),
        )

    def _merge_candidate_rows(
        self,
        cursor: Any,
        *,
        keep_repo_id: str,
        drop_row: dict[str, Any],
        checked_at: str,
    ) -> None:
        """把 drop_row 整仓并入 keep：子表随迁、别名改指、删除旧行并留名型别名。"""
        drop_repo_id = str(drop_row["repo_id"])
        self._move_series_child_rows(
            cursor, old_repo_id=drop_repo_id, new_repo_id=keep_repo_id
        )
        self._move_enrichment_row(
            cursor, old_repo_id=drop_repo_id, new_repo_id=keep_repo_id
        )
        self._move_singleton_child_rows(
            cursor, old_repo_id=drop_repo_id, new_repo_id=keep_repo_id
        )
        self._move_favorite_rows(
            cursor, old_repo_id=drop_repo_id, new_repo_id=keep_repo_id
        )
        self._merge_candidate_scalars(
            cursor, keep_repo_id=keep_repo_id, drop_row=drop_row, checked_at=checked_at
        )
        now = _utcnow()
        cursor.execute(
            "UPDATE github_repo_aliases SET canonical_repo_id=%s, updated_at=%s "
            "WHERE canonical_repo_id=%s AND alias_repo_id<>%s",
            (keep_repo_id, now, drop_repo_id, keep_repo_id),
        )
        self._upsert_alias(
            cursor,
            alias_repo_id=drop_repo_id,
            canonical_repo_id=keep_repo_id,
            full_name=str(drop_row.get("full_name") or ""),
        )
        cursor.execute(
            "DELETE FROM github_repo_candidates WHERE repo_id=%s", (drop_repo_id,)
        )

    def _reconcile_repo_rename(
        self,
        cursor: Any,
        *,
        old_full_name: str,
        new_full_name: str,
        seen_repo_id: str = "",
        checked_at: str = "",
    ) -> str:
        """把候选行归一到 GitHub 权威新名；返回动作标识供日志/测试断言。

        动作取值：
          missing              库里没有旧名行，无需处理
          noop                 已是新名（或输入无效）
          casing               仅大小写差异，就地归一
          renamed              旧名行改名为新名（node 型 PK 就地更新；
                               name 型 PK 走克隆新身份行 + 并入旧行）
          merged               新旧两名各占一行 → 并入保留新名行
          conflict_name_reuse  node id 防线触发：疑似名称被他人重用，拒绝合并
        """
        old_full_name = (old_full_name or "").strip()
        new_full_name = (new_full_name or "").strip()
        if not old_full_name or not new_full_name or "/" not in new_full_name:
            return "noop"
        if old_full_name == new_full_name:
            return "noop"
        self._lock_identities(cursor, old_full_name, new_full_name)
        old_row = self._find_candidate_row_by_name(cursor, old_full_name)
        if not old_row:
            return "missing"
        if old_row["full_name"].lower() == new_full_name.lower():
            if old_row["full_name"] != new_full_name:
                self._rename_candidate_row(
                    cursor,
                    repo_id=old_row["repo_id"],
                    old_full_name=old_row["full_name"],
                    new_full_name=new_full_name,
                    checked_at=checked_at,
                )
                return "casing"
            return "noop"
        new_row = self._find_candidate_row_by_name(cursor, new_full_name)
        old_nodes = self._node_alias_ids(cursor, old_row["repo_id"])
        new_nodes = self._node_alias_ids(cursor, new_row["repo_id"]) if new_row else set()
        if old_nodes and new_nodes and old_nodes.isdisjoint(new_nodes):
            logger.warning("GitHub identity conflict: refusing merge %s -> %s", old_full_name, new_full_name)
            return "conflict_name_reuse"
        # Both sides must agree. A node alias pointing at either side is not
        # evidence that the other side is the same repository (names get reused).
        if seen_repo_id and "/" not in seen_repo_id and not seen_repo_id.isdecimal():
            for known in (old_nodes, new_nodes):
                if known and seen_repo_id not in known:
                    logger.warning("GitHub identity conflict: refusing merge %s -> %s", old_full_name, new_full_name)
                    return "conflict_name_reuse"
        # node id 防线：拿到 API 返回的 node id 时，确认它与旧名行同源，
        # 防止“旧仓删除 + 同名新仓”被误当成改名而吞掉别人的历史。
        if seen_repo_id and "/" not in seen_repo_id:
            cursor.execute(
                "SELECT canonical_repo_id FROM github_repo_aliases "
                "WHERE alias_repo_id=%s LIMIT 1",
                (seen_repo_id,),
            )
            via_node = cursor.fetchone()
            if via_node:
                via_canonical = str(via_node["canonical_repo_id"] or "")
                new_peek = self._find_candidate_row_by_name(cursor, new_full_name)
                allowed = {old_row["repo_id"], str((new_peek or {}).get("repo_id") or "")}
                if via_canonical not in allowed:
                    logger.warning(
                        "[GitHubProjectIngestion] 改名归一被拒绝：%s -> %s，node %s "
                        "归属 %s，疑似名称重用",
                        old_full_name,
                        new_full_name,
                        seen_repo_id,
                        via_canonical,
                    )
                    return "conflict_name_reuse"
            else:
                known_nodes = self._node_alias_ids(cursor, old_row["repo_id"])
                if known_nodes and seen_repo_id not in known_nodes:
                    logger.warning(
                        "[GitHubProjectIngestion] 改名归一被拒绝：%s -> %s，node %s "
                        "不在旧行已知 node 集合内",
                        old_full_name,
                        new_full_name,
                        seen_repo_id,
                    )
                    return "conflict_name_reuse"
        if not new_row:
            if old_row["repo_id"].lower() == old_row["full_name"].lower():
                # name 型 PK 内嵌旧名：克隆新身份行再并入旧行，
                # 避免旧名后续写入撞上过期 PK（PK 与 full_name 永久脱节）
                self._clone_candidate_row(
                    cursor,
                    old_row=old_row,
                    new_full_name=new_full_name,
                    checked_at=checked_at,
                )
                self._merge_candidate_rows(
                    cursor,
                    keep_repo_id=new_full_name,
                    drop_row=old_row,
                    checked_at=checked_at,
                )
                surviving = new_full_name
            else:
                self._rename_candidate_row(
                    cursor,
                    repo_id=old_row["repo_id"],
                    old_full_name=old_row["full_name"],
                    new_full_name=new_full_name,
                    checked_at=checked_at,
                )
                surviving = str(old_row["repo_id"])
            logger.info(
                "[GitHubProjectIngestion] 仓库改名就地同步：%s -> %s",
                old_row["full_name"],
                new_full_name,
            )
            action = "renamed"
        elif new_row["repo_id"] == old_row["repo_id"]:
            return "noop"  # 大小写唯一约束下理论不可达，防御
        else:
            # 新旧两名各占一行：一律保留新名行（承载最新采集与画像），旧行并入删除
            self._merge_candidate_rows(
                cursor,
                keep_repo_id=new_row["repo_id"],
                drop_row=old_row,
                checked_at=checked_at,
            )
            surviving = str(new_row["repo_id"])
            logger.info(
                "[GitHubProjectIngestion] 仓库改名合并：%s -> %s（保留 %s）",
                old_full_name,
                new_full_name,
                surviving,
            )
            action = "merged"
        # 旧名长期可解析：后续以旧名写入的观测/快照仍归并到存续行
        self._upsert_alias(
            cursor,
            alias_repo_id=old_full_name,
            canonical_repo_id=surviving,
            full_name=old_full_name,
        )
        return action

    def _resolve_for_write(
        self,
        cursor: Any,
        *,
        requested: str,
        full_name: str,
        checked_at: str = "",
    ) -> str:
        """写入前的 canonical 解析；别名落点名称过期时先触发改名归一。

        仅 node 形态 repo_id 参与自愈：名称型 repo_id（trending 等）无法证明
        与既有行同源，不做改名动作。
        """
        requested = (requested or "").strip()
        full_name = (full_name or "").strip()
        self._lock_identities(cursor, full_name or requested)
        # A current name row wins over a historical name alias. The alias can
        # outlive a rename and subsequently refer to an unrelated new project.
        if "/" in requested and full_name:
            current = self._find_candidate_row_by_name(cursor, full_name)
            if current:
                return str(current["repo_id"])
        canonical = self._resolve_repo_id(cursor, requested, full_name)
        if "/" in requested or not requested:
            if full_name and canonical.lower() != full_name.lower():
                raise GitHubIdentityConflict(f"GitHub identity conflict: unverified name alias {full_name}")
            return canonical
        known = self._node_alias_ids(cursor, canonical)
        if known and not requested.isdecimal() and requested not in known:
            raise GitHubIdentityConflict(f"GitHub identity conflict: {full_name or canonical}")
        if not full_name or canonical == requested:
            return canonical
        cursor.execute(
            "SELECT full_name FROM github_repo_candidates WHERE repo_id=%s LIMIT 1",
            (canonical,),
        )
        row = cursor.fetchone()
        stored = str((row or {}).get("full_name") or "")
        if stored and stored != full_name:
            action = self._reconcile_repo_rename(
                cursor,
                old_full_name=stored,
                new_full_name=full_name,
                seen_repo_id=requested,
                checked_at=checked_at,
            )
            if action == "conflict_name_reuse":
                raise GitHubIdentityConflict(f"GitHub identity conflict: {stored} -> {full_name}")
            canonical = self._resolve_repo_id(cursor, requested, full_name)
        return canonical

    # ---------- 候选与快照写入 ----------

    def upsert_github_repo_candidate(self, repo: dict[str, Any]) -> None:
        payload = self._candidate_payload(repo)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                requested = payload["repo_id"]
                canonical = self._resolve_for_write(
                    cursor, requested=requested, full_name=payload["full_name"]
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
                canonical = self._resolve_for_write(
                    cursor, requested=requested, full_name=payload["full_name"]
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
                changed = cursor.rowcount > 0
        if changed:
            live_stats_broadcaster.notify_live_stats_changed("github-repo-available")
        return changed

    def record_github_repo_not_found(self, full_name: str, *, checked_at: str) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                _, newly = self._apply_not_found_observation(
                    cursor, full_name, checked_at
                )
        if newly:
            live_stats_broadcaster.notify_live_stats_changed("github-repo-not-found")
        return newly

    def insert_github_repo_snapshot(self, snapshot: dict[str, Any]) -> None:
        payload = self._normalize_snapshot_payload(snapshot)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                payload["repo_id"] = self._resolve_for_write(
                    cursor,
                    requested=str(payload.get("repo_id") or ""),
                    full_name=str(payload.get("full_name") or ""),
                )
                cursor.execute(_SNAPSHOT_UPSERT_SQL, payload)
                observation = _star_observation_payload(payload)
                if observation is not None:
                    cursor.execute(_STAR_OBSERVATION_UPSERT_SQL, observation)

    def upsert_github_repo_metric_observations(
        self,
        observations: list[dict[str, Any]],
        *,
        checked_at: str,
    ) -> int:
        """单事务批量写入一次日刷观测：候选 upsert + 改名归一 + 可用性恢复 + 快照插入。

        每条 observation 形如 {"candidate": {...}, "available_full_name": str,
        "renamed_from": str, "snapshot": {...}}，与三个单行方法共用同一套 SQL
        与归一化逻辑。renamed_from 非空表示 GitHub 已把该请求名重定向到
        candidate.full_name，入库前先把旧名候选行归一/合并到新名。
        任一观测失败整批回滚、不留中间态，调用方按整批成功/失败计数；
        返回实际写入的观测条数（名称重用等防御性跳过不计）。
        """
        if not observations:
            return 0
        batch_nodes: dict[str, set[str]] = {}
        for observation in observations:
            candidate = observation.get("candidate") or {}
            node = str(candidate.get("repo_id") or "")
            if node and "/" not in node and not node.isdecimal():
                batch_nodes.setdefault(str(candidate.get("full_name") or "").lower(), set()).add(node)
        skipped: set[int] = set()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                candidates: list[dict[str, Any]] = []
                aliases: list[tuple[str, str, str]] = []
                availability_marks: list[tuple[str, str]] = []
                for index, observation in enumerate(observations):
                    payload = self._candidate_payload(
                        observation.get("candidate") or {}
                    )
                    requested = payload["repo_id"]
                    node_hint = requested if "/" not in requested else ""
                    if len(batch_nodes.get(payload["full_name"].lower(), set())) > 1:
                        logger.warning("GitHub identity conflict within batch: %s", payload["full_name"])
                        skipped.add(index)
                        continue
                    renamed_from = str(observation.get("renamed_from") or "").strip()
                    if renamed_from:
                        action = self._reconcile_repo_rename(
                            cursor,
                            old_full_name=renamed_from,
                            new_full_name=payload["full_name"],
                            seen_repo_id=node_hint,
                            checked_at=checked_at,
                        )
                        if action == "conflict_name_reuse":
                            # 旧仓消失、名字被他人重用：累计不可用观测而非吞并新仓
                            self._apply_not_found_observation(
                                cursor, renamed_from, checked_at
                            )
                            logger.warning(
                                "[GitHubProjectIngestion] 观测跳过：%s 名称疑似被重用",
                                renamed_from,
                            )
                            skipped.add(index)
                            continue
                    try:
                        canonical = self._resolve_for_write(
                            cursor,
                            requested=requested,
                            full_name=payload["full_name"],
                            checked_at=checked_at,
                        )
                    except GitHubIdentityConflict:
                        self._apply_not_found_observation(cursor, payload["full_name"], checked_at)
                        logger.warning("GitHub identity conflict: skipping %s", payload["full_name"])
                        skipped.add(index)
                        continue
                    if node_hint and not renamed_from:
                        # 名称未变但返回陌生 node id → 旧仓已删、名字被重用：
                        # 累计不可用观测并跳过，绝不用别人的数据覆盖旧行
                        known_nodes = self._node_alias_ids(cursor, canonical)
                        if known_nodes and node_hint not in known_nodes:
                            self._apply_not_found_observation(
                                cursor, payload["full_name"], checked_at
                            )
                            logger.warning(
                                "[GitHubProjectIngestion] 观测跳过：%s 名称疑似被重用"
                                "（node %s 不匹配）",
                                payload["full_name"],
                                node_hint,
                            )
                            skipped.add(index)
                            continue
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
                for index, observation in enumerate(observations):
                    if index in skipped:
                        continue
                    payload = self._normalize_snapshot_payload(
                        observation.get("snapshot") or {}
                    )
                    payload["repo_id"] = self._resolve_for_write(
                        cursor,
                        requested=str(payload.get("repo_id") or ""),
                        full_name=str(payload.get("full_name") or ""),
                    )
                    snapshots.append(payload)
                cursor.executemany(_SNAPSHOT_UPSERT_SQL, snapshots)
                star_observations = [
                    observation
                    for observation in map(_star_observation_payload, snapshots)
                    if observation is not None
                ]
                if star_observations:
                    cursor.executemany(_STAR_OBSERVATION_UPSERT_SQL, star_observations)
        return len(observations) - len(skipped)

    def prune_github_star_observations(
        self, *, retention_hours: int = STAR_OBSERVATION_RETENTION_HOURS
    ) -> int:
        """删除超出保留期的星数观测，返回删除行数。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM github_repo_star_observations "
                    "WHERE observed_at < now() - make_interval(hours => %s)",
                    (int(retention_hours),),
                )
                return int(cursor.rowcount or 0)

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
                payload["repo_id"] = self._resolve_for_write(
                    cursor,
                    requested=str(payload.get("repo_id") or ""),
                    full_name=str(payload.get("full_name") or ""),
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
                WHERE c.availability_status='active'
                  AND NOT EXISTS (
                      SELECT 1 FROM github_repo_aliases ga
                      WHERE ga.alias_repo_id=c.repo_id AND ga.canonical_repo_id<>c.repo_id
                  )
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
        self, *, min_stars: int = 500, limit: int = 0,
        metric_date: str | None = None, fresh_since: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [min_stars]
        pending_sql = ""
        if metric_date is not None and fresh_since is not None:
            # 快照和指标共同作为持久进度；仅候选信息被更新、或快照写完但
            # 算分前重启，都必须继续处理。失败和未知结果不能标记为完成。
            pending_sql = """
                AND NOT EXISTS (
                    SELECT 1 FROM github_repo_snapshots s
                    JOIN github_repo_daily_metrics m
                      ON m.repo_id=s.repo_id AND m.metric_date=s.snapshot_date
                    WHERE s.repo_id=c.repo_id AND s.snapshot_date=%s
                      AND s.captured_at >= %s AND m.updated_at >= s.captured_at
                )
                AND NOT (c.availability_status='not_found'
                         AND COALESCE(c.availability_checked_at,'') >= %s)
            """
            params.extend([metric_date, fresh_since, fresh_since])
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
                       FROM github_repo_candidates c
                       WHERE COALESCE(stars,0)>=%s AND COALESCE(full_name,'')!=''
                    """
                    + pending_sql
                    + " ORDER BY COALESCE(stars,0) DESC,full_name ASC"
                    + limit_sql,
                    tuple(params),
                )
                return list(cursor.fetchall())

    def list_github_identity_sweep_targets(
        self, *, after_full_name: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """身份巡检全量游标：按 full_name 键集分页，覆盖所有候选行。

        与日刷的 list_github_project_metric_targets 不同：不限星级、含
        not_found 行（确认其依旧 404 或已恢复/改名复活）。返回列与日刷一致，
        保证 record_github_metric_outcomes 的字段回填（source_channels 等）
        语义不变。
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT repo_id,full_name,title,url,description,language,topics_json,
                              created_at,pushed_at,COALESCE(stars,0) stars,COALESCE(forks,0) forks,
                              COALESCE(watchers,0) watchers,source_channels,first_seen_at,last_seen_at,
                              last_snapshot_at,availability_status,not_found_count,availability_checked_at
                       FROM github_repo_candidates
                       WHERE COALESCE(full_name,'')!='' AND full_name>%s
                       ORDER BY full_name ASC LIMIT %s""",
                    (after_full_name or "", max(1, min(int(limit), 2000))),
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
            metric_date,
            baseline_start_date,
            metric_date,
            baseline_start_date,
            metric_date,
            baseline_start_date,
            metric_date,
            previous_date,
            baseline_start_date,
            metric_date,
            metric_date,
            min_stars,
        ]
        if normalized:
            params.append(normalized)
        # Reconstruct the public top ten for each prior date, before applying
        # this refresh's repo/min-stars filters. Three absent calendar days
        # reset exposure; shorter gaps pause it. Today's writes never count.
        sql = (
            f"""
            WITH top_history AS (
                SELECT leaders.repo_id, days.days_ago
                FROM generate_series(1, {TOP_STREAK_LOOKBACK_DAYS}) AS days(days_ago)
                CROSS JOIN LATERAL (
                    SELECT m.repo_id
                    FROM github_repo_daily_metrics m
                    JOIN github_repo_candidates c ON c.repo_id=m.repo_id
                    JOIN github_repo_enrichments e ON e.repo_id=c.repo_id
                    WHERE m.metric_date=(%s::date-days.days_ago)::text
                      AND {heat_growth_sql('m')}>0
                      AND c.availability_status='active' AND e.status='succeeded'
                      AND NOT EXISTS (SELECT 1 FROM github_repo_aliases a
                          WHERE a.alias_repo_id=c.repo_id AND a.canonical_repo_id<>c.repo_id)
                      AND NOT EXISTS (SELECT 1 FROM github_repo_quarantine q WHERE q.repo_id=c.repo_id)
                    ORDER BY m.hot_score DESC NULLS LAST, {heat_growth_sql('m')} DESC NULLS LAST,
                             m.stars DESC NULLS LAST, c.full_name ASC
                    LIMIT {TOP_STREAK_RANK_LIMIT}
                ) leaders
            ), top_gaps AS (
                SELECT repo_id, days_ago,
                       days_ago-COALESCE(LAG(days_ago) OVER (
                           PARTITION BY repo_id ORDER BY days_ago),0) AS gap_days
                FROM top_history
            ), top_streaks AS (
                SELECT repo_id, LEAST(COUNT(*),{TOP_STREAK_PRIOR_DAYS_CAP})::integer
                    AS previous_top_streak_days
                FROM (
                    SELECT repo_id, MAX(gap_days) OVER (
                        PARTITION BY repo_id ORDER BY days_ago) AS longest_gap
                    FROM top_gaps
                ) recent_run
                WHERE longest_gap<={TOP_STREAK_RESET_DAYS}
                GROUP BY repo_id
            )
            """
            """
            SELECT s.repo_id,c.full_name,s.snapshot_date metric_date,COALESCE(s.stars,0) stars,
                COALESCE(ts.previous_top_streak_days,0) AS previous_top_streak_days,
                (SELECT jsonb_agg(jsonb_build_object(
                    'snapshot_date', h.snapshot_date, 'captured_at', h.captured_at,
                    'stars', h.stars, 'forks', h.forks, 'watchers', h.watchers,
                    'community_metrics_complete', h.community_metrics_complete,
                    'repo_pushed_at', h.repo_pushed_at) ORDER BY h.snapshot_date)
                 FROM github_repo_snapshots h WHERE h.repo_id=s.repo_id
                   AND h.snapshot_date BETWEEN (s.snapshot_date::date-12)::text AND s.snapshot_date
                ) AS heat_snapshot_history,
                obs.points AS heat_star_observations,
                COALESCE(s.forks,0) forks,COALESCE(s.watchers,0) watchers,
                s.community_metrics_complete,COALESCE(s.open_issues,0) open_issues,
                COALESCE(NULLIF(c.created_at,''),NULLIF(s.repo_created_at,''),'') repo_created_at,
                NULLIF(c.created_at,'') candidate_created_at,
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
                    AND m.daily_growth_source IN ('snapshot_delta','github_trending_daily')) baseline_sample_count,
                EXISTS(SELECT 1 FROM github_repo_daily_metrics m WHERE m.repo_id=s.repo_id
                    AND m.metric_date>=%s AND m.metric_date<%s
                    AND m.growth_suspicion_signals LIKE '%%"coordinated_creation"%%') prior_coordinated_creation
            FROM github_repo_snapshots s
            LEFT JOIN top_streaks ts ON ts.repo_id=s.repo_id
            LEFT JOIN LATERAL (
                SELECT p.snapshot_date, p.stars, p.forks, p.watchers,
                       p.community_metrics_complete
                FROM github_repo_snapshots p
                WHERE p.repo_id = s.repo_id
                  AND p.snapshot_date <= %s
                  AND p.snapshot_date >= %s
                ORDER BY p.snapshot_date DESC
                LIMIT 1
            ) prev ON TRUE
            CROSS JOIN LATERAL (
                SELECT CASE WHEN s.captured_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}'
                    THEN s.captured_at::timestamptz END AS window_end
            ) win
            -- 滚动窗口起点两侧各取一条盘中观测（主键索引两次探测）：
            -- 起点及之前最近一条、起点之后最早一条，由热度模块插值。
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object(
                    'observed_at', o.observed_at, 'stars', o.stars,
                    'forks', o.forks, 'watchers', o.watchers) ORDER BY o.observed_at) AS points
                FROM (
                    (SELECT b.observed_at, b.stars, b.forks, b.watchers
                     FROM github_repo_star_observations b
                     WHERE b.repo_id = s.repo_id
                       AND b.observed_at <= win.window_end - interval '"""
            + f"{ROLLING_WINDOW_HOURS} hours"
            + """'
                       AND b.observed_at >= win.window_end - interval '"""
            + f"{MAX_GAP_DAYS + 1} days"
            + """'
                     ORDER BY b.observed_at DESC LIMIT 1)
                    UNION ALL
                    (SELECT a.observed_at, a.stars, a.forks, a.watchers
                     FROM github_repo_star_observations a
                     WHERE a.repo_id = s.repo_id
                       AND a.observed_at > win.window_end - interval '"""
            + f"{ROLLING_WINDOW_HOURS} hours"
            + """'
                       AND a.observed_at <= win.window_end
                     ORDER BY a.observed_at ASC LIMIT 1)
                ) o
            ) obs ON TRUE
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
            "previous_top_streak_days": 0,
            "growth_suspicion_score": 0.0,
            "growth_suspicion_signals": "[]",
            "growth_corroborated": False,
            "score_version": HEAT_SCORE_VERSION,
            "rolling_24h_star_growth": None,
            "rolling_24h_growth_source": None,
            "rolling_24h_observed_at": None,
        }
        for metric in metrics:
            payload = dict(metric)
            for key, value in defaults.items():
                payload.setdefault(key, value)
            payload["daily_growth_available"] = bool(
                payload.get("daily_growth_available")
            )
            payload["growth_corroborated"] = bool(payload.get("growth_corroborated"))
            payload.setdefault("updated_at", _utcnow())
            normalized.append(payload)
        sql = """
            INSERT INTO github_repo_daily_metrics (
                repo_id,metric_date,stars,forks,watchers,open_issues,previous_snapshot_date,
                previous_stars,daily_star_growth,daily_fork_growth,daily_watcher_growth,
                daily_growth_available,daily_growth_source,daily_growth_observed_at,
                scale_corrected_growth_score,growth_acceleration_score,absolute_growth_score,
                maintenance_activity_score,community_engagement_score,hot_score,previous_top_streak_days,
                growth_suspicion_score,growth_suspicion_signals,growth_corroborated,
                score_version,updated_at,
                rolling_24h_star_growth,rolling_24h_growth_source,rolling_24h_observed_at
            ) VALUES (
                %(repo_id)s,%(metric_date)s,%(stars)s,%(forks)s,%(watchers)s,%(open_issues)s,
                %(previous_snapshot_date)s,%(previous_stars)s,%(daily_star_growth)s,
                %(daily_fork_growth)s,%(daily_watcher_growth)s,%(daily_growth_available)s,
                %(daily_growth_source)s,%(daily_growth_observed_at)s,%(scale_corrected_growth_score)s,
                %(growth_acceleration_score)s,%(absolute_growth_score)s,%(maintenance_activity_score)s,
                %(community_engagement_score)s,%(hot_score)s,%(previous_top_streak_days)s,
                %(growth_suspicion_score)s,%(growth_suspicion_signals)s,%(growth_corroborated)s,
                %(score_version)s,%(updated_at)s,
                %(rolling_24h_star_growth)s,%(rolling_24h_growth_source)s,%(rolling_24h_observed_at)s
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
                hot_score=EXCLUDED.hot_score,
                previous_top_streak_days=EXCLUDED.previous_top_streak_days,
                growth_suspicion_score=EXCLUDED.growth_suspicion_score,
                growth_suspicion_signals=EXCLUDED.growth_suspicion_signals,
                growth_corroborated=EXCLUDED.growth_corroborated,
                score_version=EXCLUDED.score_version,updated_at=EXCLUDED.updated_at,
                rolling_24h_star_growth=EXCLUDED.rolling_24h_star_growth,
                rolling_24h_growth_source=EXCLUDED.rolling_24h_growth_source,
                rolling_24h_observed_at=EXCLUDED.rolling_24h_observed_at
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(sql, normalized)
        return len(normalized)

    def refresh_github_quarantine(self) -> dict[str, int]:
        """整体重算疑似诱饵隔离名单，返回名单规模与本轮新增、放出的仓库数。

        名单是派生数据：每轮热度指标落库后重算，不再命中规则的仓库自动放出。
        表锁只挡并发的另一轮重算，不挡公开查询的读。
        """
        params = {
            "surge_score": GITHUB_QUARANTINE_SURGE_SCORE,
            "surge_signal": '%"coordinated_creation"%',
            "name_min_owners": GITHUB_QUARANTINE_NAME_MIN_OWNERS,
            "name_min_removed": GITHUB_QUARANTINE_NAME_MIN_REMOVED,
        }
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "LOCK TABLE github_repo_quarantine IN SHARE ROW EXCLUSIVE MODE"
                )
                cursor.execute(_GITHUB_QUARANTINE_SQL, params)
                row = cursor.fetchone() or {}
        return {
            key: int(row.get(key) or 0)
            for key in ("quarantined", "added", "released")
        }
