from __future__ import annotations

from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class PostgresEmailMonitorRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def record_event(self, kind: str, outcome: str, error_type: str | None) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO email_send_events (kind, outcome, error_type) VALUES (%s, %s, %s)",
                (kind, outcome, error_type),
            )

    def delivery_stats(self) -> dict:
        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FILTER (WHERE outcome = 'accepted') AS accepted_24h,
                       COUNT(*) FILTER (WHERE outcome = 'failed') AS failed_24h,
                       COUNT(*) FILTER (WHERE outcome = 'failed'
                           AND occurred_at >= CURRENT_TIMESTAMP - INTERVAL '15 minutes') AS failed_15m
                FROM email_send_events
                WHERE occurred_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                """
            ).fetchone()
        return dict(row)

    def read(self) -> dict:
        with self._database.transaction() as connection:
            row = connection.execute("SELECT * FROM email_monitor_state WHERE id = 1").fetchone()
        state = dict(row["state"])
        state["tracking_started_at"] = row["started_at"].isoformat()
        checked = state.get("checked_at")
        state["stale"] = not checked or (
            datetime.now(timezone.utc) - datetime.fromisoformat(checked)
        ).total_seconds() > 600
        return state

    def claim(self, token: str) -> bool:
        with self._database.transaction() as connection:
            row = connection.execute(
                """
                UPDATE email_monitor_state SET lease_token = %s,
                    lease_until = CURRENT_TIMESTAMP + INTERVAL '5 minutes'
                WHERE id = 1 AND next_check_at <= CURRENT_TIMESTAMP
                    AND (lease_until IS NULL OR lease_until < CURRENT_TIMESTAMP)
                RETURNING id
                """, (token,),
            ).fetchone()
        return row is not None

    def save(self, token: str, state: dict) -> None:
        with self._database.transaction() as connection:
            row = connection.execute(
                """
                UPDATE email_monitor_state SET state = %s
                WHERE id = 1 AND lease_token = %s AND lease_until > CURRENT_TIMESTAMP
                RETURNING id
                """, (Jsonb(state), token),
            ).fetchone()
            if row is None:
                raise RuntimeError("email monitor lease lost")

    def release(self, token: str, *, succeeded: bool) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE email_monitor_state SET lease_token = NULL, lease_until = NULL,
                    next_check_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                WHERE id = 1 AND lease_token = %s
                """, (300 if succeeded else 60, token),
            )
            connection.execute(
                "DELETE FROM email_send_events WHERE occurred_at < CURRENT_TIMESTAMP - INTERVAL '90 days'"
            )
