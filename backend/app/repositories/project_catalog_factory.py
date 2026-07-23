from __future__ import annotations

from backend.app.core.config import settings
from backend.app.repositories.mysql_project_catalog import MySQLProjectCatalogRepository
from backend.app.repositories.project_catalog import ProjectCatalogRepository


def get_project_catalog_repository() -> ProjectCatalogRepository:
    backend = str(settings.project_catalog_backend or "").strip().lower()
    if backend == "mysql":
        return MySQLProjectCatalogRepository()
    if backend == "postgres":
        from backend.app.repositories.postgres_project_catalog import (
            PostgresProjectCatalogRepository,
        )

        return PostgresProjectCatalogRepository()
    raise ValueError(
        f"Unsupported PROJECT_CATALOG_BACKEND {settings.project_catalog_backend!r}; "
        "expected 'mysql' or 'postgres'"
    )
