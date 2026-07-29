from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from backend.app import main


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        application_database_backend="postgres",
        project_catalog_backend="postgres",
        project_catalog_outbox_capture_enabled=False,
        project_catalog_sync_worker_enabled=False,
        project_catalog_shadow_enabled=False,
        project_semantic_search_enabled=False,
        scheduler_enabled=False,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        redis_password="",
        env="test",
    )


class MainLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_mounts_and_closes_postgres_lifecycle(self) -> None:
        app = FastAPI()
        database = MagicMock()
        repositories = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return MagicMock()

        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "postgres_database", database),
            patch.object(main, "create_application_repositories", return_value=repositories) as factory,
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.FastAPICache, "init"),
            patch.object(main.asyncio, "create_task", side_effect=close_warmup_coroutine),
        ):
            async with main.lifespan(app):
                self.assertIs(app.state.database, database)
                self.assertIs(app.state.postgres_database, database)
                self.assertIs(app.state.application_repositories, repositories)
                database.close.assert_not_called()

            factory.assert_called_once_with(backend="postgres", postgres=database)
            redis_client.aclose.assert_awaited_once_with()
            database.close.assert_called_once_with()

    async def test_closes_postgres_when_redis_initialization_fails(self) -> None:
        app = FastAPI()
        database = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock(side_effect=RuntimeError("redis unavailable"))

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return MagicMock()

        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "postgres_database", database),
            patch.object(main, "create_application_repositories", return_value=MagicMock()),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.asyncio, "create_task", side_effect=close_warmup_coroutine),
        ):
            async with main.lifespan(app):
                self.assertIsNone(app.state.redis)

            database.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
