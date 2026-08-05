from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class PostgresXCredentialRepository:
    """PostgreSQL persistence for the X cookie credential pool."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        bootstrap: tuple[str, str] | None = None,
    ) -> None:
        self._database = database
        self._bootstrap = bootstrap

    @staticmethod
    def _clean_secret(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def ensure_seeded_from_env(self) -> None:
        if not self._bootstrap:
            return
        auth_token, ct0 = (self._clean_secret(value) for value in self._bootstrap)
        if not auth_token or not ct0:
            return
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('x_credentials_bootstrap'))"
                )
                cursor.execute(
                    "SELECT 1 FROM x_credentials_bootstrap_state WHERE singleton_key = 1"
                )
                if cursor.fetchone() is not None:
                    return
                cursor.execute("SELECT COUNT(*) AS n FROM x_credentials")
                row = cursor.fetchone()
                count = int(
                    (row["n"] if isinstance(row, dict) else row[0]) if row else 0
                )
                if count:
                    cursor.execute(
                        """
                        INSERT INTO x_credentials_bootstrap_state (singleton_key)
                        VALUES (1)
                        ON CONFLICT (singleton_key) DO NOTHING
                        """
                    )
                    return
                cursor.execute(
                    """
                    INSERT INTO x_credentials
                        (display_name, note, auth_token, ct0, enabled, sort_order)
                    VALUES (%s, %s, %s, %s, TRUE, 0)
                    """,
                    (
                        "env-bootstrap",
                        "由环境变量初始化；请在 Monitor 的 X 凭证池中管理。",
                        auth_token,
                        ct0,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO x_credentials_bootstrap_state (singleton_key)
                    VALUES (1)
                    ON CONFLICT (singleton_key) DO NOTHING
                    """
                )

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT id, display_name, note, auth_token, ct0, enabled, sort_order,
                   last_test_status, last_test_message, last_test_at,
                   created_at, updated_at
            FROM x_credentials
        """

    def list_x_credentials(self) -> list[dict[str, Any]]:
        self.ensure_seeded_from_env()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._select_sql() + " ORDER BY enabled DESC, sort_order ASC, id ASC")
                return [dict(row) for row in cursor.fetchall()]

    def get_x_credential(self, credential_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._select_sql() + " WHERE id = %s LIMIT 1", (credential_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_enabled_x_credentials(self) -> list[dict[str, Any]]:
        self.ensure_seeded_from_env()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select_sql()
                    + " WHERE enabled ORDER BY sort_order ASC, id ASC"
                )
                return [dict(row) for row in cursor.fetchall()]

    def create_x_credential(self, payload: dict[str, Any]) -> dict[str, Any]:
        auth_token = self._clean_secret(payload.get("auth_token"))
        ct0 = self._clean_secret(payload.get("ct0"))
        if not auth_token or not ct0:
            raise ValueError("auth_token 和 ct0 不能为空")
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO x_credentials
                        (display_name, note, auth_token, ct0, enabled, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        str(payload.get("display_name") or "").strip(),
                        str(payload.get("note") or "").strip(),
                        auth_token,
                        ct0,
                        bool(payload.get("enabled", True)),
                        int(payload.get("sort_order", 0)),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL X credential insert did not return an id")
                credential_id = int(row["id"])
        return self.get_x_credential(credential_id) or {}

    def update_x_credential(
        self,
        credential_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = self.get_x_credential(credential_id)
        if not existing:
            return None
        auth_token = self._clean_secret(payload.get("auth_token")) or str(existing.get("auth_token") or "")
        ct0 = self._clean_secret(payload.get("ct0")) or str(existing.get("ct0") or "")
        if not auth_token or not ct0:
            raise ValueError("auth_token 和 ct0 不能为空")
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_credentials
                    SET display_name = %s,
                        note = %s,
                        auth_token = %s,
                        ct0 = %s,
                        enabled = %s,
                        sort_order = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        str(payload.get("display_name") or existing.get("display_name") or "").strip(),
                        str(payload.get("note") if "note" in payload else existing.get("note") or "").strip(),
                        auth_token,
                        ct0,
                        bool(payload.get("enabled", bool(existing.get("enabled")))),
                        int(payload.get("sort_order", int(existing.get("sort_order") or 0))),
                        credential_id,
                    ),
                )
        return self.get_x_credential(credential_id)

    def delete_x_credential(self, credential_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM x_credentials WHERE id = %s", (credential_id,))
                return cursor.rowcount > 0

    def update_x_credential_test_result(
        self,
        credential_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = str(result.get("status") or "unknown").strip().lower()
        message = str(result.get("message") or "").strip()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_credentials
                    SET last_test_status = %s,
                        last_test_message = %s,
                        last_test_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, message, credential_id),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_x_credential(credential_id)
