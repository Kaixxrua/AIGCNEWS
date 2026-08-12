from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.smtp_settings_repository import SmtpSettings

_COLUMNS = "host, port, username, password, from_email, from_name, use_tls, updated_at"


class PostgresSmtpSettingsRepository:
    """PostgreSQL persistence for the singleton SMTP settings row (id = 1)."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_smtp_settings(self) -> SmtpSettings | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_COLUMNS}
                    FROM smtp_settings
                    WHERE id = 1
                    """
                )
                row = cursor.fetchone()
                return self._row_to_settings(row) if row else None

    def upsert_smtp_settings(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_tls: bool,
    ) -> SmtpSettings:
        clean_host = (host or "").strip()
        if not 1 <= int(port) <= 65535:
            raise ValueError("port 必须在 1-65535 之间")

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO smtp_settings
                        (id, host, port, username, password, from_email, from_name,
                         use_tls, updated_at)
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        host = EXCLUDED.host,
                        port = EXCLUDED.port,
                        username = EXCLUDED.username,
                        password = EXCLUDED.password,
                        from_email = EXCLUDED.from_email,
                        from_name = EXCLUDED.from_name,
                        use_tls = EXCLUDED.use_tls,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    (
                        clean_host,
                        int(port),
                        username or "",
                        password or "",
                        from_email or "",
                        from_name or "",
                        bool(use_tls),
                    ),
                )
                row = cursor.fetchone()

        return self._row_to_settings(row)

    def delete_smtp_settings(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM smtp_settings WHERE id = 1")
                return int(cursor.rowcount)

    def _row_to_settings(self, row: dict[str, Any]) -> SmtpSettings:
        return SmtpSettings(
            host=str(row["host"]),
            port=int(row["port"]),
            username=str(row["username"]),
            password=str(row["password"]),
            from_email=str(row["from_email"]),
            from_name=str(row["from_name"]),
            use_tls=bool(row["use_tls"]),
            updated_at=row["updated_at"],
        )
