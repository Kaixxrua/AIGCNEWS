from __future__ import annotations

import json
from typing import Any

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.services.application_data_transfer import (
    APPLICATION_TABLE_TRANSFER_SPECS,
    ApplicationTableTransferSpec,
)
from backend.app.services.project_catalog_transfer import (
    ProjectCatalogTransferSafetyError,
    ProjectCatalogTransferService,
)


class ApplicationTransferService(ProjectCatalogTransferService):
    """Copy all non-catalog application tables from MySQL to PostgreSQL."""

    def __init__(
        self,
        *,
        mysql: DatabaseLifecycle = mysql_database,
        postgres: PostgresDatabaseLifecycle = postgres_database,
        config: Any | None = None,
    ) -> None:
        super().__init__(
            mysql=mysql,
            postgres=postgres,
            config=config,
            table_specs=APPLICATION_TABLE_TRANSFER_SPECS,
            minimum_schema_version=6,
        )

    def plan_application(
        self,
        *,
        job_id: str,
        batch_size: int = 500,
        target_database: str,
        target_schema: str,
        source_timezone: str = "UTC",
    ) -> dict[str, Any]:
        return self.plan_catalog(
            job_id=job_id,
            batch_size=batch_size,
            target_database=target_database,
            target_schema=target_schema,
            source_timezone=source_timezone,
        )

    def load_application(
        self,
        *,
        job_id: str,
        batch_size: int = 500,
        target_database: str,
        target_schema: str,
        source_timezone: str = "UTC",
        apply: bool = False,
        production_authorized: bool = False,
        max_attempts: int = 5,
    ) -> dict[str, Any]:
        return self.load_catalog(
            job_id=job_id,
            batch_size=batch_size,
            target_database=target_database,
            target_schema=target_schema,
            source_timezone=source_timezone,
            apply=apply,
            production_authorized=production_authorized,
            max_attempts=max_attempts,
        )

    @classmethod
    def _encode_source_row(
        cls,
        spec: ApplicationTableTransferSpec,
        row: dict[str, Any],
        *,
        source_timezone: str,
    ) -> dict[str, Any]:
        encoded = super()._encode_source_row(
            spec,
            row,
            source_timezone=source_timezone,
        )
        for column in spec.json_columns:
            value = encoded[column]
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                encoded[column] = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                continue
            if not isinstance(value, str):
                raise ProjectCatalogTransferSafetyError(
                    f"source column {spec.name}.{column} is not valid JSON text"
                )
            try:
                json.loads(value)
            except json.JSONDecodeError as error:
                raise ProjectCatalogTransferSafetyError(
                    f"source column {spec.name}.{column} is invalid JSON"
                ) from error
            encoded[column] = value
        return encoded
