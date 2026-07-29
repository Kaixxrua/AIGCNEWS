from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app import main


class _State:
    pass


class _App:
    def __init__(self) -> None:
        self.state = _State()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        project_semantic_search_enabled=False,
        scheduler_enabled=False,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        redis_password="",
        env="production",
    )


def test_postgres_lifespan_opens_and_closes_selected_pool() -> None:
    app = _App()

    async def run() -> None:
        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "Redis", side_effect=RuntimeError("redis unavailable")),
            patch.object(main.asyncio, "create_task") as create_task,
            patch.object(main.postgres_database, "open") as postgres_open,
            patch.object(main.postgres_database, "close") as postgres_close,
            patch.object(main, "create_application_repositories", return_value=MagicMock()),
        ):
            create_task.side_effect = lambda coroutine: coroutine.close()
            async with main.lifespan(app):
                assert app.state.database is main.postgres_database
                assert app.state.postgres_database is main.postgres_database
            postgres_open.assert_called_once_with()
            postgres_close.assert_called_once_with()

    asyncio.run(run())


def test_postgres_open_failure_aborts_startup() -> None:
    app = _App()
    error = RuntimeError("postgres unavailable")

    async def run() -> None:
        async def invoke(function: MagicMock, *args: object) -> object:
            return function(*args)

        with (
            patch.object(main, "settings", _settings()),
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
