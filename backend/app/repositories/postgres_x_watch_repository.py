from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import errors

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.x_watch_repository import XWatchAccountConflictError


def normalize_x_screen_name(value: Any) -> str:
    """Normalize an X handle to the canonical stored form (lowercase, no ``@``)."""
    if not isinstance(value, str):
        return ""
    return value.strip().lstrip("@").strip().lower()


class PostgresXWatchAccountRepository:
    """PostgreSQL persistence for X watchlist account rows."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        defaults: Sequence[str] = (),
    ) -> None:
        self._database = database
        self._defaults = tuple(defaults)

    def _seed_default_x_watch_accounts(self) -> None:
        handles = [handle for raw in self._defaults if (handle := normalize_x_screen_name(raw))]
        if not handles:
            return

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                for screen_name in handles:
                    cursor.execute(
                        """
                        INSERT INTO x_watch_accounts
                            (screen_name, display_name, note, enabled)
                        VALUES (%s, %s, %s, TRUE)
                        ON CONFLICT (screen_name) DO NOTHING
                        """,
                        (
                            screen_name,
                            screen_name,
                            "由环境变量初始化的 X 关注账号，可在监控页继续编辑。",
                        ),
                    )

    def list_x_watch_accounts(self) -> list[dict[str, Any]]:
        self._seed_default_x_watch_accounts()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, screen_name, display_name, note, enabled, sort_order,
                           last_test_status, last_test_message, last_test_at,
                           created_at, updated_at
                    FROM x_watch_accounts
                    ORDER BY enabled DESC, sort_order ASC, screen_name ASC, id ASC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_x_watch_account(self, account_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, screen_name, display_name, note, enabled, sort_order,
                           last_test_status, last_test_message, last_test_at,
                           created_at, updated_at
                    FROM x_watch_accounts
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (account_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def create_x_watch_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        screen_name = normalize_x_screen_name(payload.get("screen_name"))
        display_name = (payload.get("display_name") or "").strip()
        note = (payload.get("note") or "").strip()
        try:
            sort_order = int(payload.get("sort_order", 0))
        except (TypeError, ValueError):
            sort_order = 0

        try:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO x_watch_accounts
                            (screen_name, display_name, note, enabled, sort_order)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            screen_name,
                            display_name,
                            note,
                            bool(payload.get("enabled", True)),
                            sort_order,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError("PostgreSQL X watch account insert did not return an id")
                    account_id = int(row["id"])
        except errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_x_watch_accounts_screen_name":
                raise XWatchAccountConflictError("screen_name already exists") from exc
            raise

        row = self.get_x_watch_account(account_id)
        return row or {}

    def update_x_watch_account(
        self,
        account_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = self.get_x_watch_account(account_id)
        if not existing:
            return None

        screen_name = normalize_x_screen_name(
            payload.get("screen_name") or existing.get("screen_name")
        )
        display_name = (
            payload.get("display_name") or existing.get("display_name") or ""
        ).strip()
        note = (
            payload.get("note")
            if "note" in payload
            else existing.get("note")
        ) or ""
        note = str(note).strip()
        enabled = bool(payload.get("enabled", bool(existing.get("enabled"))))
        try:
            sort_order = int(payload.get("sort_order", int(existing.get("sort_order") or 0)))
        except (TypeError, ValueError):
            sort_order = int(existing.get("sort_order") or 0)

        try:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE x_watch_accounts
                        SET screen_name = %s,
                            display_name = %s,
                            note = %s,
                            enabled = %s,
                            sort_order = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (
                            screen_name,
                            display_name,
                            note,
                            enabled,
                            sort_order,
                            account_id,
                        ),
                    )
        except errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_x_watch_accounts_screen_name":
                raise XWatchAccountConflictError("screen_name already exists") from exc
            raise

        return self.get_x_watch_account(account_id)

    def delete_x_watch_account(self, account_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM x_watch_accounts WHERE id = %s",
                    (account_id,),
                )
                return cursor.rowcount > 0

    def update_x_watch_test_result(
        self,
        account_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = (result.get("status") or "unknown").strip().lower()
        message = (result.get("message") or "").strip()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_watch_accounts
                    SET last_test_status = %s,
                        last_test_message = %s,
                        last_test_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, message, account_id),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_x_watch_account(account_id)

    def list_enabled_x_handles(self) -> list[str]:
        self._seed_default_x_watch_accounts()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT screen_name
                    FROM x_watch_accounts
                    WHERE enabled
                    ORDER BY sort_order ASC, screen_name ASC, id ASC
                    """
                )
                handles: list[str] = []
                for row in cursor.fetchall():
                    screen_name = normalize_x_screen_name(
                        row["screen_name"] if isinstance(row, dict) else row[0]
                    )
                    if screen_name:
                        handles.append(screen_name)
                return handles
