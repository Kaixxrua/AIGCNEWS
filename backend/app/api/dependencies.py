from __future__ import annotations

from fastapi import Depends, Request

from backend.app.core.database import DatabaseLifecycle
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
