from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class PostgresRuntimeProviderSettingRepository:
    """PostgreSQL persistence for the singleton runtime model configuration."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_runtime_provider_setting(
        self,
        provider: str = "",
    ) -> dict[str, Any] | None:
        provider_key = (provider or "").strip().lower()
        where_clause = "WHERE provider = %s" if provider_key else ""
        params = (provider_key,) if provider_key else ()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT provider, base_url, api_key, model_name, updated_at
                    FROM runtime_provider_settings
                    {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    params,
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def upsert_runtime_provider_setting(
        self,
        provider: str,
        base_url: str = "",
        api_key: str | None = None,
        clear_api_key: bool = False,
        model_name: str = "",
    ) -> dict[str, Any]:
        provider_key = (provider or "").strip().lower()
        clean_base_url = (base_url or "").strip()
        clean_api_key = api_key.strip() if isinstance(api_key, str) else None
        clean_model_name = (model_name or "").strip()

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT api_key
                    FROM runtime_provider_settings
                    ORDER BY updated_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                )
                existing = cursor.fetchone()
                if clear_api_key:
                    effective_api_key: str | None = None
                elif clean_api_key:
                    effective_api_key = clean_api_key
                else:
                    effective_api_key = existing.get("api_key") if existing else None

                cursor.execute("DELETE FROM runtime_provider_settings")
                cursor.execute(
                    """
                    INSERT INTO runtime_provider_settings
                        (provider, base_url, api_key, model_name, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING provider, base_url, api_key, model_name, updated_at
                    """,
                    (
                        provider_key,
                        clean_base_url,
                        effective_api_key,
                        clean_model_name,
                    ),
                )
                row = cursor.fetchone()

        return dict(row) if row else {
            "provider": provider_key,
            "base_url": clean_base_url,
            "api_key": effective_api_key,
            "model_name": clean_model_name,
        }
