from __future__ import annotations

import secrets
from typing import Any

from backend.app.core.auth import hash_password
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.oauth_identity_repository import (
    OAuthBindResult,
    OAuthLoginResolution,
)

# users.username 字段上限（VARCHAR(64)）
_USERNAME_MAX_LENGTH = 64


def _resolve_oauth_username(username: str, display_email: str | None) -> str:
    """OAuth 首次建号的初始 username：provider 用户名 → provider 邮箱 → 空串。

    仅用于新用户 INSERT；已有用户的 username 永不被本路径覆盖。
    超长输入按字段上限截断（provider 数据不可信，避免 INSERT 报错回滚）。
    """
    resolved = (username or "").strip() or (display_email or "").strip()
    return resolved[:_USERNAME_MAX_LENGTH]


class PostgresOAuthIdentityRepository:
    """Transactional PostgreSQL persistence for OAuth identities and users."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def resolve_first_login(
        self,
        *,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
        username: str = "",
    ) -> OAuthLoginResolution:
        """Resolve and persist one external identity in a single transaction."""
        if provider not in {"github", "google", "wechat"}:
            raise ValueError("unknown OAuth provider")
        subject = str(provider_subject)
        if not subject or not subject.strip():
            raise ValueError("provider_subject must not be empty")
        canonical_email = (
            display_email.strip().lower()
            if email_verified and display_email and display_email.strip()
            else None
        )
        # Hashing happens before acquiring database locks: bcrypt must not extend
        # the critical section shared by concurrent first-login requests.
        unusable_hash = hash_password(secrets.token_urlsafe(48))
        lock_keys = [f"oauth:subject:{provider}:{subject}"]
        if canonical_email:
            lock_keys.append(f"oauth:email:{canonical_email}")
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                for lock_key in sorted(lock_keys):
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (lock_key,),
                    )
                cursor.execute(
                    """
                    SELECT i.id AS identity_id, i.user_id, i.provider, i.provider_subject,
                           i.display_email, i.email_verified,
                           u.email, u.role, u.disabled, u.pwd_ver,
                           u.membership_tier, u.membership_expires_at
                    FROM user_oauth_identities i
                    JOIN users u ON u.id = i.user_id
                    WHERE i.provider = %s AND i.provider_subject = %s
                    FOR UPDATE OF i, u
                    """,
                    (provider, subject),
                )
                existing_identity = cursor.fetchone()
                if existing_identity is not None:
                    user = dict(existing_identity)
                    return OAuthLoginResolution(
                        status="disabled" if user.get("disabled") else "authenticated",
                        user=user,
                    )

                user: dict[str, Any] | None = None
                email_owner_exists = False
                if canonical_email:
                    cursor.execute(
                        """
                        SELECT id, email, email_verified, role, disabled, pwd_ver,
                               membership_tier, membership_expires_at
                        FROM users
                        WHERE lower(email) = %s
                        FOR UPDATE
                        """,
                        (canonical_email,),
                    )
                    owner = cursor.fetchone()
                    email_owner_exists = owner is not None
                    if owner is not None and bool(owner.get("email_verified")):
                        user = dict(owner)
                        if user.get("disabled"):
                            return OAuthLoginResolution(status="disabled", user=user)

                # Matching an unverified local account is not sufficient for
                # automatic linking; preserve the provider claim only on the
                # identity and create a separate OAuth-only account.
                account_email = canonical_email if user is None and not email_owner_exists else None
                account_verified = bool(account_email)
                if user is None:
                    cursor.execute(
                        """
                        INSERT INTO users (
                            email, username, hashed_password, role,
                            email_verified, password_login_enabled
                        )
                        VALUES (%s, %s, %s, 'user', %s, FALSE)
                        RETURNING id, email, email_verified, role, disabled, pwd_ver,
                                  membership_tier, membership_expires_at
                        """,
                        (
                            account_email,
                            _resolve_oauth_username(username, display_email),
                            unusable_hash,
                            account_verified,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError("PostgreSQL OAuth user insert did not return a row")
                    user = dict(row)

                cursor.execute(
                    """
                    INSERT INTO user_oauth_identities (
                        user_id, provider, provider_subject,
                        display_email, email_verified
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (provider, provider_subject) DO NOTHING
                    RETURNING id
                    """,
                    (
                        user["id"],
                        provider,
                        subject,
                        display_email,
                        bool(email_verified and display_email),
                    ),
                )
                if cursor.fetchone() is None:
                    # Defensive fallback for writers that do not take the
                    # advisory lock; never return this request's candidate user.
                    cursor.execute(
                        """
                        SELECT i.user_id, u.email, u.role, u.disabled, u.pwd_ver,
                               u.membership_tier, u.membership_expires_at
                        FROM user_oauth_identities i
                        JOIN users u ON u.id = i.user_id
                        WHERE i.provider = %s AND i.provider_subject = %s
                        FOR UPDATE OF i, u
                        """,
                        (provider, subject),
                    )
                    winner = cursor.fetchone()
                    if winner is None:
                        raise RuntimeError("OAuth identity conflict winner disappeared")
                    winner_user = dict(winner)
                    return OAuthLoginResolution(
                        status="disabled" if winner_user.get("disabled") else "authenticated",
                        user=winner_user,
                    )
                return OAuthLoginResolution(
                    status="disabled" if user.get("disabled") else "authenticated",
                    user=user,
                )

    def get_by_provider_subject(
        self, provider: str, provider_subject: str
    ) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT i.id AS identity_id, i.user_id, i.provider, i.provider_subject,
                   i.display_email, i.email_verified,
                   u.email, u.role, u.disabled, u.pwd_ver,
                   u.membership_tier, u.membership_expires_at
            FROM user_oauth_identities i
            JOIN users u ON u.id = i.user_id
            WHERE i.provider = %s AND i.provider_subject = %s
            """,
            (provider, provider_subject),
        )

    def get_by_verified_email(self, email: str) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT id, email, role, disabled, pwd_ver,
                   membership_tier, membership_expires_at
            FROM users
            WHERE email = %s AND email_verified = TRUE
            """,
            (email.lower(),),
        )

    def create_oauth_only_user(
        self,
        *,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
        username: str = "",
    ) -> dict[str, Any]:
        # The legacy users schema requires a password hash. Generate a random
        # bcrypt value the user cannot know; password_login_enabled is the
        # authoritative gate for this OAuth-only account.
        unusable_hash = hash_password(secrets.token_urlsafe(48))
        account_email = (
            display_email.strip().lower()
            if email_verified and display_email and display_email.strip()
            else None
        )
        account_verified = bool(account_email)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        email, username, hashed_password, role,
                        email_verified, password_login_enabled
                    )
                    VALUES (%s, %s, %s, 'user', %s, FALSE)
                    RETURNING id, email, role, disabled, pwd_ver,
                              membership_tier, membership_expires_at
                    """,
                    (
                        account_email,
                        _resolve_oauth_username(username, display_email),
                        unusable_hash,
                        account_verified,
                    ),
                )
                user = cursor.fetchone()
                if user is None:
                    raise RuntimeError("PostgreSQL OAuth user insert did not return a row")
                user_row = dict(user)
                cursor.execute(
                    """
                    INSERT INTO user_oauth_identities (
                        user_id, provider, provider_subject,
                        display_email, email_verified
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        user_row["id"],
                        provider,
                        provider_subject,
                        display_email,
                        account_verified,
                    ),
                )
                if cursor.fetchone() is None:
                    raise RuntimeError("PostgreSQL OAuth identity insert did not return a row")
                return user_row

    def list_identities_for_user(
        self,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Return display-safe identities without stable provider subjects."""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider, display_email, email_verified,
                           created_at AS linked_at
                    FROM user_oauth_identities
                    WHERE user_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (int(user_id),),
                )
                return [dict(row) for row in cursor.fetchall()]

    def bind_identity(
        self,
        *,
        user_id: int,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
    ) -> OAuthBindResult:
        """Bind an external identity to an already-authenticated account.

        与 resolve_first_login 共用同一 advisory lock 键，绑定与首次登录建号
        在数据库层互斥；返回结构化结果以区分幂等成功与他人占用，绝不把
        他人身份转移到本账户。
        """
        if provider not in {"github", "google", "wechat"}:
            raise ValueError("unknown OAuth provider")
        subject = str(provider_subject)
        if not subject or not subject.strip():
            raise ValueError("provider_subject must not be empty")
        target_user_id = int(user_id)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"oauth:subject:{provider}:{subject}",),
                )
                cursor.execute(
                    """
                    SELECT user_id
                    FROM user_oauth_identities
                    WHERE provider = %s AND provider_subject = %s
                    FOR UPDATE
                    """,
                    (provider, subject),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    owner_id = int(existing["user_id"])
                    return OAuthBindResult(
                        status="already_bound" if owner_id == target_user_id else "owned_by_other"
                    )
                cursor.execute(
                    """
                    INSERT INTO user_oauth_identities (
                        user_id, provider, provider_subject,
                        display_email, email_verified
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (provider, provider_subject) DO NOTHING
                    RETURNING id
                    """,
                    (
                        target_user_id,
                        provider,
                        subject,
                        display_email,
                        bool(email_verified),
                    ),
                )
                if cursor.fetchone() is not None:
                    return OAuthBindResult(status="bound")
                # 未走 advisory lock 的并发写入者抢占了该身份：重查属主并据实返回，
                # 绝不返回 "bound" 造成绑定成功的假象。
                cursor.execute(
                    """
                    SELECT user_id
                    FROM user_oauth_identities
                    WHERE provider = %s AND provider_subject = %s
                    FOR UPDATE
                    """,
                    (provider, subject),
                )
                winner = cursor.fetchone()
                if winner is None:
                    raise RuntimeError("OAuth identity conflict winner disappeared")
                winner_id = int(winner["user_id"])
                return OAuthBindResult(
                    status="already_bound" if winner_id == target_user_id else "owned_by_other"
                )

    def _fetchone(
        self, sql: str, params: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
