from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    create_postgres_pool,
)


def _pool_with_connection(connection: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    connection = connection or MagicMock()
    connection.transaction.return_value = nullcontext()
    pool = MagicMock()
    pool.getconn.return_value = connection
    return pool, connection


def test_pool_is_lazy_and_reused() -> None:
    pool, connection = _pool_with_connection()
    pool_factory = MagicMock(return_value=pool)
    database = PostgresDatabaseLifecycle(pool_factory, acquisition_timeout=3.5)

    pool_factory.assert_not_called()
    with database.connection() as first:
        assert first is connection
    with database.connection() as second:
        assert second is connection

    pool_factory.assert_called_once_with()
    pool.open.assert_called_once_with(wait=True, timeout=3.5)
    assert pool.getconn.call_count == 2
    pool.getconn.assert_called_with(timeout=3.5)
    assert pool.putconn.call_count == 2


def test_connection_returns_connection_to_pool_on_error() -> None:
    pool, connection = _pool_with_connection()
    database = PostgresDatabaseLifecycle(MagicMock(return_value=pool))
    error = RuntimeError("sentinel")

    with pytest.raises(RuntimeError) as caught:
        with database.connection() as acquired:
            assert acquired is connection
            raise error

    assert caught.value is error
    pool.putconn.assert_called_once_with(connection)


def test_transaction_uses_psycopg_transaction_context() -> None:
    events: list[str] = []
    transaction = MagicMock()
    transaction.__enter__.side_effect = lambda: events.append("begin")
    transaction.__exit__.side_effect = lambda *args: events.append("finish")
    connection = MagicMock()
    pool, _ = _pool_with_connection(connection)
    connection.transaction.return_value = transaction
    pool.putconn.side_effect = lambda _: events.append("putconn")
    database = PostgresDatabaseLifecycle(MagicMock(return_value=pool))

    with database.transaction() as acquired:
        assert acquired is connection
        events.append("body")

    assert events == ["begin", "body", "finish", "putconn"]
    transaction.__exit__.assert_called_once_with(None, None, None)
    connection.close.assert_not_called()


def test_transaction_discards_connection_after_body_error() -> None:
    error = RuntimeError("body failed")
    pool, connection = _pool_with_connection()
    database = PostgresDatabaseLifecycle(MagicMock(return_value=pool))

    with pytest.raises(RuntimeError) as caught:
        with database.transaction():
            raise error

    assert caught.value is error
    connection.close.assert_called_once_with()
    pool.putconn.assert_called_once_with(connection)


def test_transaction_preserves_body_error_when_discard_close_fails() -> None:
    error = RuntimeError("body failed")
    pool, connection = _pool_with_connection()
    connection.close.side_effect = RuntimeError("close failed")
    database = PostgresDatabaseLifecycle(MagicMock(return_value=pool))

    with pytest.raises(RuntimeError) as caught:
        with database.transaction():
            raise error

    assert caught.value is error
    pool.putconn.assert_called_once_with(connection)


def test_transaction_preserves_body_error_when_return_fails() -> None:
    error = RuntimeError("body failed")
    pool, connection = _pool_with_connection()
    pool.putconn.side_effect = RuntimeError("return failed")
    database = PostgresDatabaseLifecycle(MagicMock(return_value=pool))

    with pytest.raises(RuntimeError) as caught:
        with database.transaction():
            raise error

    assert caught.value is error
    connection.close.assert_called_once_with()
    pool.putconn.assert_called_once_with(connection)


def test_failed_open_closes_pool_and_can_retry() -> None:
    first_pool = MagicMock()
    first_pool.open.side_effect = RuntimeError("unavailable")
    second_pool, connection = _pool_with_connection()
    pool_factory = MagicMock(side_effect=[first_pool, second_pool])
    database = PostgresDatabaseLifecycle(pool_factory)

    with pytest.raises(RuntimeError, match="unavailable"):
        database.open()
    with database.connection() as acquired:
        assert acquired is connection

    first_pool.close.assert_called_once_with()
    assert pool_factory.call_count == 2


def test_close_before_open_is_noop_and_reopen_builds_new_pool() -> None:
    first_pool, _ = _pool_with_connection()
    second_pool, _ = _pool_with_connection()
    pool_factory = MagicMock(side_effect=[first_pool, second_pool])
    database = PostgresDatabaseLifecycle(pool_factory)

    database.close()
    pool_factory.assert_not_called()

    database.open()
    database.close()
    database.close()
    database.open()

    assert pool_factory.call_count == 2
    first_pool.close.assert_called_once_with()
    second_pool.close.assert_not_called()


def test_create_pool_preserves_independent_configuration() -> None:
    config = SimpleNamespace(
        postgres_host="pg.internal",
        postgres_port=5544,
        postgres_user="catalog",
        postgres_password="top-secret",
        postgres_database="catalog_test",
        postgres_sslmode="verify-full",
        postgres_pool_min_size=3,
        postgres_pool_max_size=12,
        postgres_pool_timeout_seconds=7.5,
        postgres_connect_timeout_seconds=4,
        postgres_statement_timeout_ms=9_000,
    )
    pool = MagicMock()
    constructor = MagicMock(return_value=pool)

    result = create_postgres_pool(config=config, pool_constructor=constructor)

    assert result is pool
    kwargs = constructor.call_args.kwargs
    parsed = conninfo_to_dict(kwargs["conninfo"])
    assert parsed == {
        "user": "catalog",
        "password": "top-secret",
        "dbname": "catalog_test",
        "host": "pg.internal",
        "port": "5544",
        "options": "-c statement_timeout=9000",
        "application_name": "aigcnews-project-catalog",
        "connect_timeout": "4",
        "sslmode": "verify-full",
    }
    assert kwargs["min_size"] == 3
    assert kwargs["max_size"] == 12
    assert kwargs["timeout"] == 7.5
    assert kwargs["kwargs"] == {"autocommit": False, "row_factory": dict_row}
    assert kwargs["open"] is False


def test_create_pool_defaults_do_not_log_or_print_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    constructor = MagicMock(return_value=MagicMock())

    create_postgres_pool(
        config=SimpleNamespace(postgres_password="do-not-print"),
        pool_constructor=constructor,
    )

    captured = capsys.readouterr()
    assert "do-not-print" not in captured.out
    assert "do-not-print" not in captured.err
