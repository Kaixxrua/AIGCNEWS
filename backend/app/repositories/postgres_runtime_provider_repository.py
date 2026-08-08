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
                    SELECT provider, base_url, api_key, model_name, reasoning_effort,
                           enrichment_reasoning_effort, updated_at
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
        reasoning_effort: str = "",
    ) -> dict[str, Any]:
        provider_key = (provider or "").strip().lower()
        clean_base_url = (base_url or "").strip()
        clean_api_key = api_key.strip() if isinstance(api_key, str) else None
        clean_model_name = (model_name or "").strip()
        clean_reasoning_effort = (reasoning_effort or "").strip().lower()

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT api_key, enrichment_reasoning_effort
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

                # 富化专用推理强度不在本表单内：INSERT 沿用最近一行的旧值，
                # 冲突更新则保留目标行自己的值，避免被整体覆盖清空
                carried_enrichment_effort = (
                    (existing.get("enrichment_reasoning_effort") or "")
                    if existing
                    else ""
                )

                # 单行重建保持 singleton 语义；INSERT ... ON CONFLICT 兜底
                # 空表并发 upsert：两个事务都 SELECT 为空、DELETE 无行时，
                # 同 provider 的并发 INSERT 由唯一约束序列化转为更新，不再
                # 抛出主键冲突（不同 provider 的并发则后到者 DELETE 先提交行，
                # 行为与旧实现一致）。
                cursor.execute("DELETE FROM runtime_provider_settings")
                cursor.execute(
                    """
                    INSERT INTO runtime_provider_settings
                        (provider, base_url, api_key, model_name, reasoning_effort,
                         enrichment_reasoning_effort, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (provider) DO UPDATE SET
                        base_url = EXCLUDED.base_url,
                        api_key = EXCLUDED.api_key,
                        model_name = EXCLUDED.model_name,
                        reasoning_effort = EXCLUDED.reasoning_effort,
                        enrichment_reasoning_effort =
                            runtime_provider_settings.enrichment_reasoning_effort,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING provider, base_url, api_key, model_name, reasoning_effort,
                              enrichment_reasoning_effort, updated_at
                    """,
                    (
                        provider_key,
                        clean_base_url,
                        effective_api_key,
                        clean_model_name,
                        clean_reasoning_effort,
                        carried_enrichment_effort,
                    ),
                )
                row = cursor.fetchone()

        return dict(row) if row else {
            "provider": provider_key,
            "base_url": clean_base_url,
            "api_key": effective_api_key,
            "model_name": clean_model_name,
            "reasoning_effort": clean_reasoning_effort,
            "enrichment_reasoning_effort": carried_enrichment_effort,
        }

    def update_enrichment_reasoning_effort(
        self,
        reasoning_effort: str = "",
    ) -> dict[str, Any]:
        """只更新富化专用推理强度，不触碰模型服务配置字段；表为空时补建行。"""
        clean_effort = (reasoning_effort or "").strip().lower()

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE runtime_provider_settings
                    SET enrichment_reasoning_effort = %s, updated_at = CURRENT_TIMESTAMP
                    """,
                    (clean_effort,),
                )
                if cursor.rowcount == 0:
                    # 空表并发补建：ON CONFLICT 序列化，后到事务转为更新
                    cursor.execute(
                        """
                        INSERT INTO runtime_provider_settings
                            (provider, base_url, api_key, model_name, reasoning_effort,
                             enrichment_reasoning_effort, updated_at)
                        VALUES ('', '', NULL, '', '', %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (provider) DO UPDATE SET
                            enrichment_reasoning_effort =
                                EXCLUDED.enrichment_reasoning_effort,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (clean_effort,),
                    )
                cursor.execute(
                    """
                    SELECT provider, base_url, api_key, model_name, reasoning_effort,
                           enrichment_reasoning_effort, updated_at
                    FROM runtime_provider_settings
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()

        return dict(row) if row else {
            "provider": "",
            "base_url": "",
            "api_key": None,
            "model_name": "",
            "reasoning_effort": "",
            "enrichment_reasoning_effort": clean_effort,
        }
