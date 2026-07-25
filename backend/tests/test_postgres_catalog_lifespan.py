from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app import main


class _State:
    pass


class _App:
    def __init__(self) -> None:
        self.state = _State()


def _settings(backend: str) -> SimpleNamespace:
    postgres_selected = backend.strip().lower() == "postgres"
    return SimpleNamespace(
        project_catalog_backend=backend,
        project_catalog_outbox_capture_enabled=postgres_selected,
        project_catalog_sync_worker_enabled=postgres_selected,
        project_catalog_shadow_enabled=False,
        project_catalog_shadow_backend="postgres",
        project_catalog_shadow_shutdown_timeout_seconds=1.0,
        project_semantic_search_enabled=False,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        redis_password="",
        env="production",
    )


def test_mysql_lifespan_never_opens_postgres() -> None:
    app = _App()
    redis = AsyncMock()
    redis.ping.side_effect = RuntimeError("redis unavailable")

    async def run() -> None:
        with (
            patch.object(main, "settings", _settings("mysql")),
            patch.object(main, "Redis", return_value=redis),
            patch.object(main, "start_scheduler"),
            patch.object(main, "stop_scheduler"),
            patch.object(main.asyncio, "create_task") as create_task,
            patch.object(main.asyncio, "to_thread", new=AsyncMock()) as to_thread,
            patch.object(main.postgres_database, "open") as postgres_open,
            patch.object(main.postgres_database, "close") as postgres_close,
            patch.object(main.mysql_database, "close"),
        ):
            create_task.side_effect = lambda coroutine: coroutine.close()
            async with main.lifespan(app):
                assert app.state.database is main.mysql_database
                assert app.state.postgres_database is main.postgres_database
            postgres_open.assert_not_called()
            postgres_close.assert_not_called()
            assert all(call.args != (postgres_open,) for call in to_thread.await_args_list)

    asyncio.run(run())


def test_postgres_lifespan_opens_and_closes_selected_pool() -> None:
    app = _App()
    redis = AsyncMock()
    redis.ping.side_effect = RuntimeError("redis unavailable")

    async def run() -> None:
        with (
            patch.object(main, "settings", _settings("postgres")),
            patch.object(main, "Redis", return_value=redis),
            patch.object(main, "start_scheduler"),
            patch.object(main, "stop_scheduler"),
            patch.object(main.asyncio, "create_task") as create_task,
            patch.object(main.asyncio, "to_thread", new=AsyncMock()) as to_thread,
            patch.object(main.postgres_database, "open") as postgres_open,
            patch.object(main.postgres_database, "close") as postgres_close,
            patch.object(main.mysql_database, "close"),
        ):
            create_task.side_effect = lambda coroutine: coroutine.close()
            async with main.lifespan(app):
                pass
            assert to_thread.await_args_list[0].args == (postgres_open,)
            postgres_close.assert_called_once_with()

    asyncio.run(run())


def test_shadow_postgres_open_failure_is_non_fatal() -> None:
    app = _App()
    redis = AsyncMock()
    redis.ping.side_effect = RuntimeError("redis unavailable")
    config = _settings("mysql")
    config.project_catalog_shadow_enabled = True

    async def run() -> None:
        async def invoke(function: MagicMock, *args: object) -> object:
            return function(*args)

        with (
            patch.object(main, "settings", config),
            patch.object(main, "Redis", return_value=redis),
            patch.object(main.asyncio, "to_thread", side_effect=invoke),
            patch.object(main.asyncio, "create_task") as create_task,
            patch.object(main.postgres_database, "open", side_effect=RuntimeError("postgres unavailable")),
            patch.object(main.postgres_database, "close") as postgres_close,
            patch.object(main.mysql_database, "close"),
            patch.object(main, "start_scheduler"),
            patch.object(main, "stop_scheduler"),
        ):
            create_task.side_effect = lambda coroutine: coroutine.close()
            async with main.lifespan(app):
                pass
            postgres_close.assert_not_called()

    asyncio.run(run())


def test_selected_postgres_open_failure_aborts_startup() -> None:
    app = _App()
    error = RuntimeError("postgres unavailable")

    async def run() -> None:
        async def invoke(function: MagicMock, *args: object) -> object:
            return function(*args)

        with (
            patch.object(main, "settings", _settings("postgres")),
            patch.object(main.asyncio, "to_thread", side_effect=invoke),
            patch.object(main.postgres_database, "open", side_effect=error),
            patch.object(main.postgres_database, "close") as postgres_close,
            patch.object(main, "start_scheduler") as start_scheduler,
        ):
            with pytest.raises(RuntimeError) as caught:
                async with main.lifespan(app):
                    pass
            assert caught.value is error
            start_scheduler.assert_not_called()
            postgres_close.assert_not_called()

    asyncio.run(run())
