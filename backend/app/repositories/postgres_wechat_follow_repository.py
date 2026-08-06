from __future__ import annotations

from typing import Any

from psycopg import errors

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.wechat_follow_repository import WeChatFollowRepository

_ACCOUNT_COLUMNS = """
    a.id, a.owner_id, a.fakeid, a.nickname, a.alias, a.avatar_url,
    a.signature, a.enabled, a.sort_order, a.last_sync_status,
    a.last_sync_message, a.last_sync_at, a.created_at, a.updated_at
"""


class WeChatFollowAccountNotFoundError(Exception):
    """Raised when a follow insert violates the account foreign key."""


class PostgresWeChatFollowRepository(WeChatFollowRepository):
    """PostgreSQL persistence for per-user follows of the platform catalog."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def list_catalog_with_follow_state(self, user_id: int) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_ACCOUNT_COLUMNS}, f.user_id AS follow_user_id
                    FROM wechat_official_accounts a
                    LEFT JOIN wechat_account_follows f
                        ON f.account_id = a.id AND f.user_id = %s
                    WHERE a.enabled
                    ORDER BY a.sort_order ASC, a.id ASC
                    """,
                    (user_id,),
                )
                rows = []
                for row in cursor.fetchall():
                    data = dict(row)
                    data["followed"] = data.pop("follow_user_id", None) is not None
                    rows.append(data)
                return rows

    def get_enabled_catalog_account(self, account_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_ACCOUNT_COLUMNS}
                    FROM wechat_official_accounts a
                    WHERE a.enabled AND a.id = %s
                    LIMIT 1
                    """,
                    (account_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def follow_account(self, user_id: int, account_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO wechat_account_follows (user_id, account_id)
                        VALUES (%s, %s)
                        ON CONFLICT (user_id, account_id) DO NOTHING
                        """,
                        (user_id, account_id),
                    )
                except errors.ForeignKeyViolation as exc:
                    # The account vanished between the catalog check and the
                    # insert; the service maps this to a domain 404.
                    raise WeChatFollowAccountNotFoundError(
                        f"wechat official account {account_id} does not exist"
                    ) from exc
                return cursor.rowcount > 0

    def unfollow_account(self, user_id: int, account_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM wechat_account_follows
                    WHERE user_id = %s AND account_id = %s
                    """,
                    (user_id, account_id),
                )
                return cursor.rowcount > 0

    def list_followed_account_ids(self, user_id: int) -> list[int]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT f.account_id
                    FROM wechat_account_follows f
                    JOIN wechat_official_accounts a ON a.id = f.account_id
                    WHERE f.user_id = %s AND a.enabled
                    ORDER BY a.sort_order ASC, a.id ASC
                    """,
                    (user_id,),
                )
                return [int(row["account_id"]) for row in cursor.fetchall()]
