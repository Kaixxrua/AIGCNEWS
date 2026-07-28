from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Any, Callable, Iterator, Protocol, cast

import pymysql

try:
    from DBUtils.PooledDB import PooledDB
except ModuleNotFoundError:
    from dbutils.pooled_db import PooledDB


class DBAPIConnection(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> Any: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class ConnectionPool(Protocol):
    def connection(self) -> DBAPIConnection: ...

    def close(self) -> None: ...


PoolFactory = Callable[[], ConnectionPool]


class DatabaseLifecycle:
    """Own one lazily-created connection pool for an application process."""

    def __init__(self, pool_factory: PoolFactory) -> None:
        self._pool_factory = pool_factory
        self._pool: ConnectionPool | None = None
        self._lock = Lock()

    def connect(self) -> DBAPIConnection:
        """Acquire one pooled connection proxy."""
        with self._lock:
            if self._pool is None:
                self._pool = self._pool_factory()
            return self._pool.connection()

    @contextmanager
    def connection(self) -> Iterator[DBAPIConnection]:
        """Acquire and always return a connection without transaction policy."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[DBAPIConnection]:
        """Commit successful work or roll it back, then return the connection."""
        connection = self.connect()
        primary_error: BaseException | None = None
        try:
            try:
                yield connection
                connection.commit()
            except BaseException as exc:
                primary_error = exc
                try:
                    connection.rollback()
                except BaseException:
                    pass
                raise
        finally:
            if primary_error is None:
                connection.close()
            else:
                try:
                    connection.close()
                except BaseException:
                    pass

    def close(self) -> None:
        """Close the initialized pool without creating one."""
        with self._lock:
            pool = self._pool
            self._pool = None
        if pool is not None:
            pool.close()


def create_mysql_pool(
    *,
    config: Any | None = None,
    pool_constructor: Callable[..., Any] = PooledDB,
) -> ConnectionPool:
    """Build a DBUtils pool with the repository's existing MySQL options."""
    if config is None:
        from backend.app.core.config import settings

        config = settings

    pool = pool_constructor(
        creator=pymysql,
        mincached=2,
        maxcached=5,
        maxconnections=20,
        blocking=True,
        host=getattr(config, "mysql_host", "localhost"),
        port=getattr(config, "mysql_port", 3306),
        user=getattr(config, "mysql_user", "root"),
        password=getattr(config, "mysql_password", ""),
        database=getattr(config, "mysql_database", "rag_aigc"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        setsession=[
            "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci",
            "SET time_zone = '+00:00'",
        ],
    )
    return cast(ConnectionPool, pool)


mysql_database = DatabaseLifecycle(create_mysql_pool)
