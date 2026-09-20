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

    def get_effective_member_count(self) -> int:
        # 生效口径与 tiers.resolve_effective_tier 一致：member 且未到期
        # （expires_at NULL = 长期有效，已过期按 free）；未知档位 fail-closed，
        # 等值匹配 'member' 天然不计入
        row = self._fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM users
            WHERE membership_tier = 'member'
              AND (membership_expires_at IS NULL OR membership_expires_at > now())
            """,
        )
        return int(row["cnt"] if row else 0)

    def list_users(
        self,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 会员运营列表：email/phone/username 三列模糊搜索 + 新注册在前分页；
        # 行内不含 hashed_password，生效档位由路由层 resolve_effective_tier 裁决
        page = max(1, int(page))
        page_size = min(100, max(1, int(page_size)))
        keyword = (query or "").strip()
        where = ""
        params: list[Any] = []
        if keyword:
            pattern = f"%{keyword}%"
            where = "WHERE email ILIKE %s OR phone ILIKE %s OR username ILIKE %s"
            params = [pattern, pattern, pattern]
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) AS cnt FROM users {where}",
                    tuple(params),
                )
                count_row = cursor.fetchone()
                total = int(count_row["cnt"] if count_row else 0)
                cursor.execute(
                    f"""
                    SELECT id, phone, email, username, role, disabled,
                           membership_tier, membership_expires_at, created_at
                    FROM users
                    {where}
                    ORDER BY created_at DESC NULLS LAST, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple([*params, page_size, (page - 1) * page_size]),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return rows, total

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        # 身份核验专用：按主键查询且不取 hashed_password；disabled 供
        # auth.RequireUser 判定禁用账号（0029 起 users 表才有此列）。
        # pwd_ver 供 RequireUser 比对 JWT 声明，改密后旧 token 立即失效（0041）。
        # membership_tier 供会员权益判定（0045），授予/吊销下一个请求即生效；
        # membership_expires_at（0048）供生效档位判定，NULL = 长期有效。
        return self._fetchone(
            """
            SELECT id, phone, email, username, role, disabled, pwd_ver,
                   email_verified, password_login_enabled,
                   membership_tier, membership_expires_at, created_at, avatar_digest
            FROM users
            WHERE id = %s
            """,
            (int(user_id),),
        )

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT id, phone, email, username, hashed_password, role,
                   membership_tier, created_at
            FROM users
            WHERE phone = %s
            """,
            (phone,),
        )

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        # 登录/改密凭证核验路径：disabled 供生命周期在签发令牌前拦截禁用账号，
        # pwd_ver 供登录签发时写入 JWT 声明（改密即失效旧令牌）
        return self._fetchone(
            """
            SELECT id, phone, email, username, hashed_password, role, disabled,
                   pwd_ver, password_login_enabled, membership_tier, created_at
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

    def set_membership_tier(
        self,
        *,
        user_id: int,
        tier: str,
        expires_at: datetime | None = None,
    ) -> int:
        # expires_at 与档位同事务写入：member+NULL=长期有效；free 一律传 NULL 清档
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET membership_tier = %s, membership_expires_at = %s
                    WHERE id = %s
                    """,
                    (tier, expires_at, int(user_id)),
                )
                return int(cursor.rowcount)

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
                    SET hashed_password = %s, pwd_ver = pwd_ver + 1
                    WHERE id = %s AND email = %s
                    """,
                    (hashed_password, int(user_id), email.lower()),
                )
                return int(cursor.rowcount)

    def update_user_avatar(self, *, user_id: int, png: bytes, digest: str) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET avatar_png = %s, avatar_digest = %s WHERE id = %s AND NOT disabled",
                    (png, digest, int(user_id)),
                )
                return int(cursor.rowcount)

    def get_user_avatar(self, *, user_id: int, digest: str) -> bytes | None:
        row = self._fetchone(
            "SELECT avatar_png FROM users WHERE id = %s AND avatar_digest = %s AND NOT disabled",
            (int(user_id), digest),
        )
        return bytes(row["avatar_png"]) if row and row.get("avatar_png") else None

    def update_user_username(
        self,
        *,
        user_id: int,
        username: str,
    ) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET username = %s
                    WHERE id = %s
                    """,
                    (username, int(user_id)),
                )
                return int(cursor.rowcount)

    def update_user_email(
        self,
        *,
        user_id: int,
        current_email: str,
        new_email: str,
    ) -> int:
        # 快照条件更新：仅当库内邮箱仍等于本次换绑发起时读取的 current_email
        # 才落写（并发换绑/改密之外的路径改了邮箱 → rowcount=0 → 领域层失败，
        # 已发验证码不消耗，可安全重试）。新邮箱已验 OTP，email_verified 置真。
        # 并发两账户换绑同一新邮箱由 users.email 唯一约束兜底（UniqueViolation
        # 交由路由层映射中性 409，不泄露归属）。
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET email = %s, email_verified = TRUE
                    WHERE id = %s AND email = %s
                    """,
                    (new_email.lower(), int(user_id), current_email.lower()),
                )
                return int(cursor.rowcount)

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
    ) -> int:
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
