from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class PostgresUserAccountRepository:
    """PostgreSQL persistence for user accounts and account statistics."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_user_count(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS cnt FROM users")
        return int(row["cnt"] if row else 0)

    def get_today_registered_user_count(self) -> int:
        tz_cst = timezone(timedelta(hours=8))
        today = datetime.now(tz_cst).date()
        row = self._fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM users
            WHERE (created_at AT TIME ZONE 'Asia/Shanghai')::date = %s
            """,
            (today,),
        )
        return int(row["cnt"] if row else 0)

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        # 身份核验专用：按主键查询且不取 hashed_password；disabled 供
        # auth.RequireUser 判定禁用账号（0029 起 users 表才有此列）。
        return self._fetchone(
            """
            SELECT id, phone, email, username, role, disabled, created_at
            FROM users
            WHERE id = %s
            """,
            (int(user_id),),
        )

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT id, phone, email, username, hashed_password, role, created_at
            FROM users
            WHERE phone = %s
            """,
            (phone,),
        )

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT id, phone, email, username, hashed_password, role, created_at
            FROM users
            WHERE email = %s
            """,
            (email.lower(),),
        )

    def create_user(
        self,
        phone: str,
        username: str,
        hashed_password: str,
        role: str = "user",
    ) -> int:
        return self._insert_returning_id(
            """
            INSERT INTO users (phone, username, hashed_password, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (phone, username, hashed_password, role),
        )

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET hashed_password = %s
                    WHERE id = %s AND email = %s
                    """,
                    (hashed_password, int(user_id), email.lower()),
                )
                return int(cursor.rowcount)

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
        *,
        promote_if_first: bool = False,
    ) -> int:
        if promote_if_first:
            return self._insert_first_user_promoting(
                email=email,
                hashed_password=hashed_password,
                role=role,
                username=username,
            )
        return self._insert_returning_id(
            """
            INSERT INTO users (
                email,
                username,
                hashed_password,
                role,
                email_verified
            )
            VALUES (%s, %s, %s, %s, TRUE)
            RETURNING id
            """,
            (email.lower(), username, hashed_password, role),
        )

    def _insert_first_user_promoting(
        self,
        *,
        email: str,
        hashed_password: str,
        role: str,
        username: str,
    ) -> int:
        """首位注册用户提权为 admin，其余按传入 role 落库。

        自托管全新部署没有可用的提权入口，约定用户表为空时第一个完成
        邮箱验证注册的用户成为管理员。check-then-insert 用 advisory
        事务锁串行化（先例：x_credentials 种子引导），避免 READ
        COMMITTED 下并发首注册双双看到空表而产生两个 admin。
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('users_first_admin_bootstrap'))"
                )
                cursor.execute("SELECT COUNT(*) AS n FROM users")
                row = cursor.fetchone()
                count = int(
                    (row["n"] if isinstance(row, dict) else row[0]) if row else 0
                )
                effective_role = "admin" if count == 0 else role
                cursor.execute(
                    """
                    INSERT INTO users (
                        email,
                        username,
                        hashed_password,
                        role,
                        email_verified
                    )
                    VALUES (%s, %s, %s, %s, TRUE)
                    RETURNING id
                    """,
                    (email.lower(), username, hashed_password, effective_role),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    raise RuntimeError("PostgreSQL user insert did not return an id")
                return int(inserted["id"])

    def _fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _insert_returning_id(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL user insert did not return an id")
                return int(row["id"])
