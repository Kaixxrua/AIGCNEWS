"""Fail-closed helpers for PostgreSQL integration tests.

The test database is selected only by ``TEST_POSTGRES_DSN``.  Before a schema
is created or migrations are run, the live connection must match the explicit
DSN and a marker provisioned by the test harness.
"""

from __future__ import annotations

import os
import re
import socket
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.core.postgres_database import PostgresDatabaseLifecycle

import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

TEST_DSN_ENV = "TEST_POSTGRES_DSN"
TEST_RUN_ID_ENV = "TEST_POSTGRES_RUN_ID"
LEGACY_INTEGRATION_ENV = "POSTGRES_INTEGRATION"
TEST_MARKER_TABLE = "aigcnews_test_run_guard"
_DATABASE_RE = re.compile(r"aigcnews_test(?:_[a-z0-9][a-z0-9_-]{0,63})?\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SECRET_RE = re.compile(r"(?i)(?:(password|pass|pwd)\s*=\s*([^\s]+)|://([^:/\s]+):([^@/\s]+)@)")
_OWNED_SCHEMAS: dict[str, tuple[int, str]] = {}


class PostgresTestSafetyError(RuntimeError):
    """Raised when a PostgreSQL test target cannot be proven safe."""


@dataclass(frozen=True)
class PostgresTestSandbox:
    database: PostgresDatabaseLifecycle
    schema: str
    dsn: str


def redact_postgres_secrets(value: object) -> str:
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}=***"
        return f"://{match.group(3)}:***@"

    return _SECRET_RE.sub(replace, text)


def _parse_test_config(environ: Mapping[str, str]) -> tuple[str, str, dict[str, str]]:
    dsn = environ.get(TEST_DSN_ENV, "").strip()
    run_id = environ.get(TEST_RUN_ID_ENV, "").strip()
    if not dsn:
        raise PostgresTestSafetyError(f"{TEST_DSN_ENV} is required")
    if not run_id:
        raise PostgresTestSafetyError(f"{TEST_RUN_ID_ENV} is required")
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise PostgresTestSafetyError(f"{TEST_RUN_ID_ENV} has an unsafe value")
    try:
        params = {key: str(value) for key, value in conninfo_to_dict(dsn).items()}
    except Exception as exc:
        raise PostgresTestSafetyError(
            f"invalid {TEST_DSN_ENV}: {redact_postgres_secrets(exc)}"
        ) from None
    database = params.get("dbname", "")
    if _DATABASE_RE.fullmatch(database) is None:
        raise PostgresTestSafetyError(f"{TEST_DSN_ENV} dbname is not an approved test database")
    for key in ("host", "port", "user"):
        if not params.get(key):
            raise PostgresTestSafetyError(f"{TEST_DSN_ENV} must explicitly set {key}")
    try:
        port = int(params["port"])
    except ValueError:
        raise PostgresTestSafetyError(f"{TEST_DSN_ENV} port must be an integer") from None
    if not 1 <= port <= 65535:
        raise PostgresTestSafetyError(f"{TEST_DSN_ENV} port is outside 1..65535")
    return dsn, run_id, params


def legacy_bootstrap_error(environ: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if environ is None else environ
    if source.get(LEGACY_INTEGRATION_ENV, "").strip() != "1":
        return None
    try:
        _parse_test_config(source)
    except PostgresTestSafetyError as exc:
        return (
            f"{LEGACY_INTEGRATION_ENV}=1 no longer selects a database; "
            f"configure {TEST_DSN_ENV} and {TEST_RUN_ID_ENV}: {redact_postgres_secrets(exc)}"
        )
    return None


def _expected_addresses(host: str, port: int) -> set[str]:
    try:
        return {item[4][0].split("%", 1)[0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise PostgresTestSafetyError(
            f"cannot resolve configured PostgreSQL host: {redact_postgres_secrets(exc)}"
        ) from None


def verify_live_test_target(connection: Any, params: Mapping[str, str], run_id: str) -> None:
    try:
        row = connection.execute(
            """
            SELECT current_database() AS database, current_user AS username,
                   host(inet_server_addr()) AS server_addr, inet_server_port() AS server_port,
                   (SELECT run_id FROM public.aigcnews_test_run_guard
                    WHERE run_id = %s) AS marker_run_id
            """,
            (run_id,),
        ).fetchone()
    except Exception as exc:
        raise PostgresTestSafetyError(
            f"live PostgreSQL identity verification failed: {redact_postgres_secrets(exc)}"
        ) from None
    if not isinstance(row, Mapping):
        raise PostgresTestSafetyError("live PostgreSQL identity query returned no mapping")
    if row.get("database") != params["dbname"]:
        raise PostgresTestSafetyError("live current_database() does not match TEST_POSTGRES_DSN")
    if row.get("username") != params["user"]:
        raise PostgresTestSafetyError("live current_user does not match TEST_POSTGRES_DSN")
    address = str(row.get("server_addr") or "").split("%", 1)[0]
    expected_addresses = _expected_addresses(params["host"], int(params["port"]))
    # A loopback-mapped disposable container reports its internal listener
    # address, not the host-side 127.0.0.1 address from the DSN. The marker,
    # database/user identity, and mapped server port still bind this connection
    # to the provisioned instance; enforce address equality for routable hosts.
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if params["host"].lower() not in loopback_hosts and address not in expected_addresses:
        raise PostgresTestSafetyError("live PostgreSQL server address does not match TEST_POSTGRES_DSN")
    live_port = row.get("server_port")
    expected_ports = {int(params["port"])}
    # Docker's loopback port mapping exposes a random host port while
    # PostgreSQL continues to listen on 5432 inside the disposable container.
    if params["host"].lower() in loopback_hosts:
        expected_ports.add(5432)
    if not address or live_port not in expected_ports:
        raise PostgresTestSafetyError("live PostgreSQL server port does not match TEST_POSTGRES_DSN")
    if row.get("marker_run_id") != run_id:
        raise PostgresTestSafetyError("preprovisioned PostgreSQL test-run marker is missing or mismatched")


def _schema_name(run_id: str) -> str:
    prefix = re.sub(r"[^a-z0-9_]", "_", run_id.lower())[:20]
    return f"aigcnews_it_{prefix}_{os.getpid():x}_{uuid.uuid4().hex[:16]}"


def _assert_owned(schema: str, token: str) -> None:
    if _OWNED_SCHEMAS.get(schema) != (os.getpid(), token):
        raise PostgresTestSafetyError(f"refusing cleanup of unowned scratch schema {schema!r}")


def _pool(scoped_dsn: str) -> ConnectionPool:
    return ConnectionPool(
        conninfo=scoped_dsn, min_size=1, max_size=4, timeout=10,
        kwargs={"autocommit": False, "row_factory": dict_row}, open=False,
    )


@contextmanager
def postgres_test_sandbox(
    *, environ: Mapping[str, str] | None = None,
    connect: Callable[..., Any] | None = None,
    pool_factory: Callable[[str], Any] = _pool,
) -> Iterator[PostgresTestSandbox]:
    source = os.environ if environ is None else environ
    if not source.get(TEST_DSN_ENV, "").strip():
        pytest.skip(f"{TEST_DSN_ENV} is required for PostgreSQL integration tests")
    dsn, run_id, params = _parse_test_config(source)
    if connect is None:
        import psycopg
        connect = psycopg.connect
    schema = _schema_name(run_id)
    token = uuid.uuid4().hex
    database: PostgresDatabaseLifecycle | None = None
    try:
        try:
            with connect(dsn, autocommit=True, row_factory=dict_row) as admin:
                verify_live_test_target(admin, params, run_id)
                admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        except PostgresTestSafetyError:
            raise
        except Exception as exc:
            raise PostgresTestSafetyError(
                f"PostgreSQL test target connection failed: {redact_postgres_secrets(exc)}"
            ) from None
        _OWNED_SCHEMAS[schema] = (os.getpid(), token)
        from backend.app.core.postgres_database import PostgresDatabaseLifecycle
        from backend.app.core.postgres_migrations import PostgresMigrationRunner

        scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema},public")
        database = PostgresDatabaseLifecycle(lambda: pool_factory(scoped_dsn))
        database.open()
        PostgresMigrationRunner(database).apply()
        yield PostgresTestSandbox(database=database, schema=schema, dsn=scoped_dsn)
    finally:
        if database is not None:
            database.close()
        if _OWNED_SCHEMAS.get(schema) == (os.getpid(), token):
            _assert_owned(schema, token)
            try:
                with connect(dsn, autocommit=True, row_factory=dict_row) as admin:
                    verify_live_test_target(admin, params, run_id)
                    _assert_owned(schema, token)
                    admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            except PostgresTestSafetyError:
                raise
            except Exception as exc:
                raise PostgresTestSafetyError(
                    f"PostgreSQL test schema cleanup failed: {redact_postgres_secrets(exc)}"
                ) from None
            _OWNED_SCHEMAS.pop(schema, None)


def postgres_database_fixture():
    """Pytest fixture factory kept small so suites share one safety boundary."""
    with postgres_test_sandbox() as sandbox:
        yield sandbox.database
