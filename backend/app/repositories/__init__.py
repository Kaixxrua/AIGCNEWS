from __future__ import annotations

from typing import Any

__all__ = ["MySQLRepository"]


def __getattr__(name: str) -> Any:
    if name == "MySQLRepository":
        from backend.app.repositories.mysql_repo import MySQLRepository

        return MySQLRepository
    raise AttributeError(name)
