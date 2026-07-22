from __future__ import annotations

from fastapi import Depends, Request

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_briefing_repository import MySQLBriefingRepository
from backend.app.repositories.mysql_ingestion_task_repository import (
    MySQLIngestionTaskRepository,
)
from backend.app.repositories.mysql_repo import MySQLRepository


def get_database(request: Request) -> DatabaseLifecycle:
    """Return the database lifecycle configured by the application lifespan."""
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise RuntimeError("Database lifecycle is not configured")
    return database


def get_mysql_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLRepository:
    """Build the compatibility repository with the application-owned lifecycle."""
    return MySQLRepository(database=database)


def get_ingestion_task_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLIngestionTaskRepository:
    """Return task persistence while preserving compatibility schema setup."""
    return MySQLRepository(database=database).ingestion_tasks


def get_briefing_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLBriefingRepository:
    """Return briefing persistence while preserving compatibility schema setup."""
    return MySQLRepository(database=database).briefings
