from __future__ import annotations

from datetime import date

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.site_visit_repository import SiteVisitStats


class PostgresSiteVisitRepository:
    """PostgreSQL persistence for site visit day counters."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def record_visit(self, day: date) -> SiteVisitStats:
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
                    "SELECT COALESCE(SUM(visits), 0) AS total FROM site_visit_days"
                )
                total_row = cursor.fetchone()
                total = int(total_row["total"] if total_row else 0)
        return SiteVisitStats(today_visits=today, total_visits=total)

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
