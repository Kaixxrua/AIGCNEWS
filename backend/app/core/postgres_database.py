from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Any, Callable, Iterator, Protocol, cast

from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class PostgresConnection(Protocol):
    def transaction(self, *args: Any, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


class PostgresPool(Protocol):
    def open(self, *, wait: bool = True, timeout: float | None = None) -> None: ...

    def getconn(self, timeout: float | None = None) -> PostgresConnection: ...

    def putconn(self, connection: PostgresConnection) -> None: ...

    def close(self) -> None: ...


PoolFactory = Callable[[], PostgresPool]


class PostgresDatabaseLifecycle:
    """Own one lazily-opened PostgreSQL pool for an application process."""

    def __init__(
        self,
        pool_factory: PoolFactory,
        *,
        acquisition_timeout: float = 10.0,
    ) -> None:
        self._pool_factory = pool_factory
        self._acquisition_timeout = acquisition_timeout
        self._pool: PostgresPool | None = None
        self._lock = Lock()

    def open(self) -> PostgresPool:
        """Create and open the pool once for this process."""
        with self._lock:
            if self._pool is None:
                pool = self._pool_factory()
                try:
                    pool.open(wait=True, timeout=self._acquisition_timeout)
                except Exception:
                    # 只兜底常规异常：KeyboardInterrupt/SystemExit 直接向上传播。
                    try:
                        pool.close()
                    except Exception:
                        pass
                    raise
                self._pool = pool
            return self._pool

    @contextmanager
    def connection(self) -> Iterator[PostgresConnection]:
        """Borrow and always return a connection without transaction policy."""
        pool = self.open()
        connection = pool.getconn(timeout=self._acquisition_timeout)
        try:
            yield connection
        finally:
            pool.putconn(connection)

    @contextmanager
    def transaction(
        self,
        *,
        acquisition_timeout: float | None = None,
    ) -> Iterator[PostgresConnection]:
        """Run work in a Psycopg transaction and return the pooled connection."""
        pool = self.open()
        timeout = (
            self._acquisition_timeout
            if acquisition_timeout is None
            else max(0.001, float(acquisition_timeout))
        )
        connection = pool.getconn(timeout=timeout)
        primary_error: BaseException | None = None
        try:
            try:
                with connection.transaction():
                    yield connection
            except BaseException as exc:
                primary_error = exc
                raise
        finally:
            if primary_error is None:
                pool.putconn(connection)
            else:
                # 事务失败：连接可能受污染，先显式 close 弃用再 putconn 交还。
                # psycopg_pool 对已关闭连接的 putconn 会识别并补建替代连接
                # （_return_connection 的 UNKNOWN 分支），直接放回可能复用坏
                # 连接，只 close 不 putconn 则会永久损耗池配额。
                try:
                    connection.close()
                except Exception:
                    pass
                try:
                    pool.putconn(connection)
                except Exception:
                    pass

    def close(self) -> None:
        """Close the initialized pool without creating one."""
        with self._lock:
            pool = self._pool
            self._pool = None
        if pool is not None:
            pool.close()


def create_postgres_pool(
    *,
    config: Any | None = None,
    pool_constructor: Callable[..., Any] = ConnectionPool,
) -> PostgresPool:
    """Build a closed Psycopg pool from independent PostgreSQL settings."""
    if config is None:
        from backend.app.core.config import settings

        config = settings

    connect_timeout = int(getattr(config, "postgres_connect_timeout_seconds", 5))
    statement_timeout = int(getattr(config, "postgres_statement_timeout_ms", 15_000))
    conninfo = make_conninfo(
        host=getattr(config, "postgres_host", ""),
        port=int(getattr(config, "postgres_port", 5432)),
        user=getattr(config, "postgres_user", ""),
        password=getattr(config, "postgres_password", ""),
        dbname=getattr(config, "postgres_database", ""),
        sslmode=getattr(config, "postgres_sslmode", "require"),
        connect_timeout=connect_timeout,
        application_name="aigcnews-project-catalog",
        options=f"-c statement_timeout={statement_timeout}",
    )
    pool = pool_constructor(
        conninfo=conninfo,
        min_size=int(getattr(config, "postgres_pool_min_size", 2)),
        max_size=int(getattr(config, "postgres_pool_max_size", 20)),
        timeout=float(getattr(config, "postgres_pool_timeout_seconds", 10.0)),
        kwargs={"autocommit": False, "row_factory": dict_row},
        open=False,
    )
    return cast(PostgresPool, pool)


def _default_acquisition_timeout() -> float:
    from backend.app.core.config import settings

    return float(getattr(settings, "postgres_pool_timeout_seconds", 10.0))


postgres_database = PostgresDatabaseLifecycle(
    create_postgres_pool,
    acquisition_timeout=_default_acquisition_timeout(),
)
