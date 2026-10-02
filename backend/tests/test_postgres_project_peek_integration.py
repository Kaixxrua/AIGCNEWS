from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import AsyncMock

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

# Import application settings away from the repository root so pydantic cannot
# discover a developer or production-like .env file during this opt-in test.
_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_github_project_peek import (
        PostgresGitHubProjectPeekRepository,
    )
    from backend.app.services.project_catalog.peek_service import (
        GitHubPeekFetch,
        ProjectPeekService,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def database() -> Iterator[Any]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        with database.transaction() as connection:
            for repo_id in ("acme/alpha", "acme/draft", "acme/gone", "acme/new-name", "acme/old-name"):
                connection.execute(
                    """
                    INSERT INTO github_repo_candidates (
                        repo_id, full_name, title, url, description, language, topics_json,
                        created_at, pushed_at, stars, forks, watchers, source_channels,
                        first_seen_at, last_seen_at, last_snapshot_at
                    ) VALUES (%s, %s, %s, %s, 'fixture', 'Python', '[]',
                        '2025-01-01T00:00:00Z', '2026-09-30T08:00:00Z', 1000, 10, 5, 'fixture',
                        '2026-09-01T00:00:00Z', '2026-09-30T08:00:00Z', '2026-10-02T01:00:00Z')
                    """,
                    (repo_id, repo_id.title(), repo_id.split("/")[1], f"https://github.com/{repo_id}"),
                )
            # acme/draft 没富化：不在公开项目库里
            for repo_id in ("acme/alpha", "acme/gone", "acme/new-name", "acme/old-name"):
                connection.execute(
                    """
                    INSERT INTO github_repo_enrichments (
                        repo_id, category_slug, category_name, subcategory_slug, subcategory_name,
                        description_zh, tags_json, confidence, source_fingerprint, prompt_version,
                        model_provider, model_name, status, enriched_at, updated_at
                    ) VALUES (%s, 'rag_knowledge', 'RAG 与知识库', 'rag_framework', 'RAG 框架',
                        '夹具', '[]', 0.9, repeat('a', 64), 'fixture-v1',
                        'fixture', 'fixture', 'succeeded', '2026-10-01T08:00:00Z', '2026-10-01T08:00:00Z')
                    """,
                    (repo_id,),
                )
            connection.execute(
                "UPDATE github_repo_candidates SET availability_status = 'not_found' WHERE repo_id = 'acme/gone'"
            )
            # 改名留下的旧名：列表不展示，速览也不认
            connection.execute(
                "INSERT INTO github_repo_aliases (alias_repo_id, canonical_repo_id, full_name)"
                " VALUES ('acme/old-name', 'acme/new-name', 'acme/old-name')"
            )
        yield database


def test_peek_source_follows_the_public_catalog(database: Any) -> None:
    repository = PostgresGitHubProjectPeekRepository(database)

    assert repository.peek_source("acme/alpha") == {
        "repo_id": "acme/alpha", "full_name": "Acme/Alpha", "availability_status": "active",
    }
    assert repository.peek_source("acme/new-name") == {
        "repo_id": "acme/new-name", "full_name": "Acme/New-Name", "availability_status": "active",
    }
    assert repository.peek_source("acme/gone") == {
        "repo_id": "acme/gone", "full_name": "Acme/Gone", "availability_status": "not_found",
    }
    assert repository.peek_source("acme/draft") is None
    assert repository.peek_source("acme/old-name") is None
    assert repository.peek_source("acme/nobody") is None
    # 主键按原样比，大小写不同就不是同一个仓库（与榜单行情同一口径）
    assert repository.peek_source("ACME/ALPHA") is None


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, *, ex: int | None = None) -> None:
        self.values[key] = value

    async def exists(self, *keys: str) -> int:
        return sum(key in self.values for key in keys)

    async def incr(self, key: str) -> int:
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def ttl(self, key: str) -> int:
        return 600


def test_the_service_only_reads_github_for_reachable_catalog_repos(database: Any) -> None:
    fetch = AsyncMock(return_value=GitHubPeekFetch("ok", readme=None, commit=None))
    service = ProjectPeekService(lambda: PostgresGitHubProjectPeekRepository(database), fetch=fetch)

    async def run() -> list[Any]:
        redis = _Redis()
        return [
            await service.peek(repo_id, redis=redis, client_ip="203.0.113.7")
            for repo_id in ("acme/alpha", "acme/draft", "acme/old-name", "acme/gone")
        ]

    alpha, draft, old_name, gone = asyncio.run(run())

    fetch.assert_awaited_once_with("Acme/Alpha")
    assert alpha["status"] == "ok"
    assert draft is None
    assert old_name is None
    assert gone["status"] == "unavailable"
