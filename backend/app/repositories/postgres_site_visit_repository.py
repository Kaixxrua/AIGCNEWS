from __future__ import annotations

from datetime import date

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.postgres_visitor_return_repository import PostgresVisitorReturnRepository
from backend.app.repositories.site_visit_repository import (
    AUTOMATED_PLATFORM,
    DEFAULT_PLATFORM,
    LandingVisits,
    PlatformVisits,
    SiteVisitStats,
)


class PostgresSiteVisitRepository:
    """PostgreSQL persistence for site visit day counters."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def record_browser_visit(self, day: date, visitor_id: str) -> None:
        PostgresVisitorReturnRepository(self._database).record(day, visitor_id)

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

    def record_landing(self, day: date, source: str, path: str) -> None:
        """计数一次带来源标记的落地；同访客同日去重已在 Redis 侧做完，这里只累加。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO site_landing_days (day, source, path, landings)
                    VALUES (%s, %s, %s, 1)
                    ON CONFLICT (day, source, path) DO UPDATE
                        SET landings = site_landing_days.landings + 1
                    """,
                    (day, source, path),
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

    def get_landing_breakdown(self, start: date, end: date) -> list[LandingVisits]:
        """聚合 [start, end] 窗口内各来源标记与落地页的落地次数。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source, path, SUM(landings) AS landings
                    FROM site_landing_days
                    WHERE day BETWEEN %s AND %s
                    GROUP BY source, path
                    """,
                    (start, end),
                )
                rows = cursor.fetchall()
        return [
            LandingVisits(
                source=str(row["source"]),
                path=str(row["path"]),
                landings=int(row["landings"]),
            )
            for row in rows
        ]
