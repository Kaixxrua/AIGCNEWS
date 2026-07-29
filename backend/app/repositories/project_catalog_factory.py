from __future__ import annotations

from backend.app.repositories.postgres_project_catalog import (
    PostgresProjectCatalogRepository,
)
from backend.app.repositories.project_catalog import ProjectCatalogRepository


def get_project_catalog_repository() -> ProjectCatalogRepository:
    return PostgresProjectCatalogRepository()
