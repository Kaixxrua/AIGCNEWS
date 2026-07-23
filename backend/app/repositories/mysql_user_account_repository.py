from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle


class MySQLUserAccountRepository:
    """MySQL persistence for user accounts and account statistics."""

    def __init__(self, database: DatabaseLifecycle) -> None:
        self._database = database

    def get_user_count(self) -> int:
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM users")
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)

    def get_today_registered_user_count(self) -> int:
        tz_cst = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_cst).strftime("%Y-%m-%d")
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM users WHERE LEFT(created_at, 10) = %s",
                    (today_str,),
                )
                row = cur.fetchone()
            conn.commit()
            return int(row["cnt"] if row else 0)

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        sql = "SELECT id, phone, email, username, hashed_password, role, created_at FROM users WHERE phone = %s"
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (phone,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        sql = "SELECT id, phone, email, username, hashed_password, role, created_at FROM users WHERE email = %s"
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (email.lower(),))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def create_user(
        self,
        phone: str,
        username: str,
        hashed_password: str,
        role: str = "user",
    ) -> int:
        sql = """
            INSERT INTO users (phone, username, hashed_password, role)
            VALUES (%s, %s, %s, %s)
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (phone, username, hashed_password, role))
                new_id = cur.lastrowid
            return new_id  # type: ignore[return-value]

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int:
        sql = """
            UPDATE users
            SET hashed_password = %s
            WHERE id = %s AND email = %s
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (hashed_password, int(user_id), email.lower()))
                affected = cur.rowcount
            return affected

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        invite_code_used: str = "",
        role: str = "user",
        username: str = "",
    ) -> int:
        sql = """
            INSERT INTO users (email, username, hashed_password, role, email_verified, invite_code_used)
            VALUES (%s, %s, %s, %s, 1, %s)
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (email.lower(), username, hashed_password, role, invite_code_used),
                )
                new_id = cur.lastrowid
            return new_id  # type: ignore[return-value]
