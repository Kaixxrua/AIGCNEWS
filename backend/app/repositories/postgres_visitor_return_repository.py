from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.visitor_identity import validate_visitor_id

CST = ZoneInfo("Asia/Shanghai")


class PostgresVisitorReturnRepository:
    """Persist browser/day facts without account IDs, IPs or raw browser IDs."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def record(self, day: date, visitor_id: str) -> None:
        identifier = hashlib.sha256(validate_visitor_id(visitor_id).encode()).hexdigest()
        with self._database.transaction() as connection:
            # A request from before midnight may finish after the next day's
            # request. Keep the earliest server-assigned day in either order.
            connection.execute(
                """
                INSERT INTO site_visitor_history (visitor_hash, first_seen_day)
                VALUES (%s, %s)
                ON CONFLICT (visitor_hash) DO UPDATE
                    SET first_seen_day = EXCLUDED.first_seen_day
                    WHERE site_visitor_history.first_seen_day > EXCLUDED.first_seen_day
                """, (identifier, day),
            )
            connection.execute(
                """
                INSERT INTO site_visitor_days (day, visitor_hash) VALUES (%s, %s)
                ON CONFLICT (day, visitor_hash) DO NOTHING
                """, (day, identifier),
            )

    def stats(self, days: int = 7, *, now: datetime | None = None) -> dict:
        if not 1 <= days <= 90:
            raise ValueError("days must be between 1 and 90")
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(CST).date()
        since = today - timedelta(days=days - 1)
        with self._database.transaction() as connection:
            started_at = connection.execute(
                "SELECT started_at FROM site_visitor_tracking WHERE id = 1"
            ).fetchone()["started_at"]
            rows = connection.execute(
                """
                SELECT visits.day, COUNT(*) AS total_visitors,
                       COUNT(*) FILTER (WHERE history.first_seen_day < visits.day) AS returning_visitors
                FROM site_visitor_days visits
                JOIN site_visitor_history history USING (visitor_hash)
                WHERE visits.day BETWEEN %s AND %s
                GROUP BY visits.day
                """, (since, today),
            ).fetchall()
        by_day = {row["day"]: row for row in rows}
        first_day = started_at.astimezone(CST).date()
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
            total = int(row.get("total_visitors", 0)) if coverage != "unavailable" else None
            # The first collection day has no preceding observed history.
            returning = int(row.get("returning_visitors", 0)) if day > first_day else None
            series.append({
                "day": day.isoformat(), "coverage": coverage,
                "total_visitors": total, "returning_visitors": returning,
                "return_rate": returning / total if total and returning is not None else None,
            })
        return {
            "timezone": "Asia/Shanghai", "tracking_started_at": started_at.isoformat(),
            "as_of": now.isoformat(), "days": series,
        }
