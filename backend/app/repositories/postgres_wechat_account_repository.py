from __future__ import annotations

from typing import Any

from psycopg import errors

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)


class WeChatOfficialAccountConflictError(Exception):
    """A unique account field conflicts with another row for this owner."""


class PostgresWeChatOfficialAccountRepository(WeChatOfficialAccountRepository):
    """PostgreSQL persistence for owner-scoped WeChat official accounts."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT id, owner_id, fakeid, nickname, alias, avatar_url, signature,
                   enabled, sort_order, last_sync_status, last_sync_message,
                   last_sync_at, created_at, updated_at
            FROM wechat_official_accounts
        """

    def list_wechat_accounts(self, owner_id: int) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select_sql()
                    + " WHERE owner_id = %s ORDER BY enabled DESC, sort_order ASC, id ASC",
                    (owner_id,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_wechat_account(
        self,
        owner_id: int,
        account_id: int,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select_sql() + " WHERE owner_id = %s AND id = %s LIMIT 1",
                    (owner_id, account_id),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def upsert_wechat_account(
        self,
        owner_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        fakeid = str(payload.get("fakeid") or "").strip()
        if not fakeid:
            raise ValueError("fakeid is required")

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO wechat_official_accounts (
                            owner_id, fakeid, nickname, alias, avatar_url,
                            signature, enabled, sort_order
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (owner_id, fakeid) DO UPDATE SET
                            nickname = EXCLUDED.nickname,
                            alias = EXCLUDED.alias,
                            avatar_url = EXCLUDED.avatar_url,
                            signature = EXCLUDED.signature,
                            enabled = EXCLUDED.enabled,
                            sort_order = EXCLUDED.sort_order,
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING id
                        """,
                        (
                            owner_id,
                            fakeid,
                            str(payload.get("nickname") or "").strip(),
                            str(payload.get("alias") or "").strip(),
                            str(payload.get("avatar_url") or "").strip(),
                            str(payload.get("signature") or "").strip(),
                            bool(payload.get("enabled", True)),
                            int(payload.get("sort_order", 0)),
                        ),
                    )
                except errors.UniqueViolation as exc:
                    constraint = getattr(getattr(exc, "diag", None), "constraint_name", "")
                    if "uq_wechat_official_accounts_owner_fakeid" in (constraint or ""):
                        raise WeChatOfficialAccountConflictError(
                            f"Account {fakeid} already exists for owner"
                        ) from exc
                    raise
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("WeChat account upsert did not return an id")
                account_id = int(row["id"])
        return self.get_wechat_account(owner_id, account_id) or {}

    def update_wechat_account_sync_result(
        self,
        owner_id: int,
        account_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = str(result.get("status") or "unknown").strip().lower()
        message = str(result.get("message") or "").strip()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE wechat_official_accounts
                    SET last_sync_status = %s,
                        last_sync_message = %s,
                        last_sync_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_id = %s AND id = %s
                    """,
                    (status, message, owner_id, account_id),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_wechat_account(owner_id, account_id)

    def delete_wechat_account(self, owner_id: int, account_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM wechat_official_accounts WHERE owner_id = %s AND id = %s",
                    (owner_id, account_id),
                )
                return cursor.rowcount > 0
