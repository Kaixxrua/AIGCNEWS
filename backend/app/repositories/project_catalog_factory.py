from __future__ import annotations

from backend.app.core.config import settings
from backend.app.repositories.mysql_project_catalog import MySQLProjectCatalogRepository
from backend.app.repositories.project_catalog import ProjectCatalogRepository


def get_project_catalog_repository() -> ProjectCatalogRepository:
    backend = str(settings.project_catalog_backend or "").strip().lower()
    if backend == "mysql":
        active = MySQLProjectCatalogRepository()
        if not bool(getattr(settings, "project_catalog_shadow_enabled", False)):
            return active
        from backend.app.repositories.postgres_project_catalog import (
            PostgresProjectCatalogRepository,
        )
        from backend.app.services.project_catalog_shadow import (
            ShadowComparingProjectCatalogRepository,
            get_project_catalog_shadow_manager,
        )

        manager = get_project_catalog_shadow_manager()
        if manager is None:
            return active
        shadow_backend = str(
            getattr(settings, "project_catalog_shadow_backend", "postgres") or ""
        ).strip().lower()
        if shadow_backend != "postgres":
            return active
        timeout_ms = max(
            1,
            int(
                float(settings.project_catalog_shadow_timeout_seconds)
                * 1000
            ),
        )
        return ShadowComparingProjectCatalogRepository(
            active,
            PostgresProjectCatalogRepository(statement_timeout_ms=timeout_ms),
            manager,
        )
    if backend == "postgres":
        from backend.app.repositories.postgres_project_catalog import (
            PostgresProjectCatalogRepository,
        )

        return PostgresProjectCatalogRepository()
    raise ValueError(
        f"Unsupported PROJECT_CATALOG_BACKEND {settings.project_catalog_backend!r}; "
        "expected 'mysql' or 'postgres'"
    )
