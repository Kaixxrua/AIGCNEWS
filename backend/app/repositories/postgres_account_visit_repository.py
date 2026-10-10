from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.app.core.postgres_database import PostgresDatabaseLifecycle

CST = ZoneInfo("Asia/Shanghai")


class PostgresAccountVisitRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def record(self, user_id: int, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(CST).date()
        start = datetime.combine(day, time.min, CST)
        with self._database.transaction() as connection:
            # Identity and registration time are read on the server. A unique
            # constraint makes concurrent requests/devices/retries one fact.
            connection.execute(
                """
                INSERT INTO account_visit_days (day, user_id, is_returning, first_seen_at)
                SELECT %s, id, created_at < %s, %s FROM users
                WHERE id = %s AND NOT disabled
                ON CONFLICT (day, user_id) DO NOTHING
                """,
                (day, start, now, user_id),
            )
            recorded = connection.execute(
                "SELECT 1 FROM account_visit_days WHERE day = %s AND user_id = %s",
                (day, user_id),
            ).fetchone() is not None
        return {
            "recorded": recorded,
            "day": day.isoformat(),
            "next_day_at": (start + timedelta(days=1)).isoformat(),
            "server_time": now.isoformat(),
        }

    def stats(self, days: int, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(CST).date()
        since = today - timedelta(days=days - 1)
        with self._database.transaction() as connection:
            started_at = connection.execute(
                "SELECT started_at FROM account_visit_tracking WHERE id = 1"
            ).fetchone()["started_at"]
            rows = connection.execute(
                """
                WITH accounts AS (
                    SELECT day, COUNT(*) AS active_users,
                           COUNT(*) FILTER (WHERE is_returning) AS returning_users
                    FROM account_visit_days WHERE day BETWEEN %s AND %s
                    GROUP BY day
                ), visitors AS (
                    SELECT day, visits FROM site_visit_days WHERE day BETWEEN %s AND %s
                )
                SELECT COALESCE(accounts.day, visitors.day) AS day,
                       COALESCE(active_users, 0) AS active_users,
                       COALESCE(returning_users, 0) AS returning_users,
                       COALESCE(visitors.visits, 0) AS total_visitors
                FROM accounts FULL OUTER JOIN visitors USING (day)
                """, (since, today, since, today),
            ).fetchall()
        by_day = {row["day"]: row for row in rows}
        series = []
        for offset in range(days):
            day = today - timedelta(days=offset)
            start = datetime.combine(day, time.min, CST)
            coverage = (
                "unavailable" if start + timedelta(days=1) <= started_at
                else "partial" if start < started_at or day == today
                else "complete"
            )
            row = by_day.get(day, {})
            active, returning = int(row.get("active_users", 0)), int(row.get("returning_users", 0))
            # Same browser-deduplicated UV as the site's visitor counter,
            # including anonymous visitors. Read both counts in one snapshot.
            visitors = int(row.get("total_visitors", 0)) if row or coverage != "unavailable" else None
            series.append({
                "day": day.isoformat(), "coverage": coverage,
                "total_visitors": visitors,
                "active_users": active if coverage != "unavailable" else None,
                "returning_users": returning if coverage != "unavailable" else None,
                "new_users": active - returning if coverage != "unavailable" else None,
                "return_rate": returning / visitors if visitors and coverage != "unavailable" else None,
            })
        return {
            "timezone": "Asia/Shanghai", "tracking_started_at": started_at.isoformat(),
            "as_of": now.isoformat(), "days": series,
        }
