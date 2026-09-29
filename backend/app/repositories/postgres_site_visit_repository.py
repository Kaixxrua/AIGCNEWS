from __future__ import annotations

from datetime import date

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.site_visit_repository import (
    AUTOMATED_PLATFORM,
    DEFAULT_PLATFORM,
    PlatformVisits,
    SiteVisitStats,
)


class PostgresSiteVisitRepository:
    """PostgreSQL persistence for site visit day counters."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def record_visit(self, day: date, platform: str = DEFAULT_PLATFORM) -> SiteVisitStats:
        """计数一次访问：总量表与平台维度表同事务双写，口径天然一致。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO site_visit_days (day, visits)
                    VALUES (%s, 1)
                    ON CONFLICT (day) DO UPDATE
                        SET visits = site_visit_days.visits + 1
                    RETURNING visits
                    """,
                    (day,),
                )
                row = cursor.fetchone()
                today = int(row["visits"] if row else 0)
                cursor.execute(
                    """
                    INSERT INTO site_visit_platform_days (day, platform, visits)
                    VALUES (%s, %s, 1)
                    ON CONFLICT (day, platform) DO UPDATE
                        SET visits = site_visit_platform_days.visits + 1
                    """,
                    (day, platform),
                )
                cursor.execute(
                    "SELECT COALESCE(SUM(visits), 0) AS total FROM site_visit_days"
                )
                total_row = cursor.fetchone()
                total = int(total_row["total"] if total_row else 0)
        return SiteVisitStats(today_visits=today, total_visits=total)

    def record_automated_visit(self, day: date) -> None:
        """计数一次自动化访问：只写平台维度表的 bot 桶，访问量总表不动。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO site_visit_platform_days (day, platform, visits)
                    VALUES (%s, %s, 1)
                    ON CONFLICT (day, platform) DO UPDATE
                        SET visits = site_visit_platform_days.visits + 1
                    """,
                    (day, AUTOMATED_PLATFORM),
                )

    def get_visit_stats(self, day: date) -> SiteVisitStats:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT visits FROM site_visit_days WHERE day = %s)
                            AS today_visits,
                        (SELECT COALESCE(SUM(visits), 0) FROM site_visit_days)
                            AS total_visits
                    """,
                    (day,),
                )
                row = cursor.fetchone() or {}
        return SiteVisitStats(
            today_visits=int(row.get("today_visits") or 0),
            total_visits=int(row.get("total_visits") or 0),
        )

    def get_platform_breakdown(self, since: date | None) -> list[PlatformVisits]:
        """聚合窗口内各平台访问次数；since=None 表示全量累计。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT platform, SUM(visits) AS visits
                    FROM site_visit_platform_days
                    WHERE (%s::date IS NULL OR day >= %s)
                    GROUP BY platform
                    """,
                    (since, since),
                )
                rows = cursor.fetchall()
        return [
            PlatformVisits(platform=str(row["platform"]), visits=int(row["visits"]))
            for row in rows
        ]
