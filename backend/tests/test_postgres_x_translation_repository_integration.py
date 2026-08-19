from __future__ import annotations

import hashlib
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
    from backend.app.repositories.postgres_x_translation_repository import (
        PostgresXTranslationTaskRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    try:
        database = str(conninfo_to_dict(dsn).get("dbname") or "")
    except Exception as exc:
        pytest.skip(f"TEST_POSTGRES_DSN is not a valid PostgreSQL DSN: {exc}")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def x_translation_repository() -> Iterator[tuple[Any, PostgresDatabaseLifecycle]]:
    dsn = _test_dsn()
    with psycopg.connect(dsn, autocommit=True) as admin:
        schema = f"x_translation_it_{uuid.uuid4().hex}"
        admin.execute(f'CREATE SCHEMA "{schema}"')

    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=4,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=False,
        )
    )
    try:
        PostgresMigrationRunner(database).apply()
        yield PostgresXTranslationTaskRepository(database), database
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _insert_pending_task(
    database: PostgresDatabaseLifecycle, tweet_id: str, text: str
) -> str:
    """按生产形态插入 X 文档与翻译任务；返回任务 document_id。"""
    document_id = hashlib.md5(f"x:{tweet_id}".encode()).hexdigest()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO documents (id, source, url, title) VALUES (%s, 'x', %s, %s)",
            (document_id, f"https://x.com/a/status/{tweet_id}", text[:32]),
        )
        connection.execute(
            """
            INSERT INTO x_translation_tasks
                (document_id, target_kind, source_tweet_id, source_text,
                 source_fingerprint, status, prompt_version)
            VALUES (%s, 'outer', %s, %s, repeat('a',64), 'pending', 'x-translation-v1')
            """,
            (document_id, tweet_id, text),
        )
    return document_id


def test_claim_assigns_lease_and_token(
    x_translation_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    repository, database = x_translation_repository
    tag = uuid.uuid4().hex[:8]
    for suffix in ("a", "b"):
        _insert_pending_task(database, f"c{tag}{suffix}", f"hello {suffix}")

    tasks = repository.claim_retryable(2, lease_seconds=600)

    assert len(tasks) == 2
    for task in tasks:
        assert task["status"] == "running"
        assert task["claim_token"]
        assert task["lease_expires_at"] is not None

    # 有效租约内的 running 不会被重复领取
    assert repository.claim_retryable(2, lease_seconds=600) == []
    assert repository.batch_running() == 2


def test_expired_lease_can_be_reclaimed_and_old_token_cannot_overwrite(
    x_translation_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    repository, database = x_translation_repository
    document_id = _insert_pending_task(
        database, f"e{uuid.uuid4().hex[:8]}", "stuck tweet"
    )

    stuck = repository.claim_retryable(1, lease_seconds=600)
    assert len(stuck) == 1
    old_token = stuck[0]["claim_token"]

    with database.transaction() as connection:
        connection.execute(
            "UPDATE x_translation_tasks SET lease_expires_at = CURRENT_TIMESTAMP - interval '1 second' WHERE id = %s",
            (stuck[0]["id"],),
        )

    reclaimed = repository.claim_retryable(1, lease_seconds=600)
    assert len(reclaimed) == 1
    assert reclaimed[0]["id"] == stuck[0]["id"]
    assert reclaimed[0]["claim_token"] != old_token

    # 旧 worker 迟到：完成写入被 token 条件拒绝
    assert repository.complete_task(
        stuck[0]["id"], "旧译文", "provider", "model", old_token
    ) is False

    # 新 worker 正常完成
    assert repository.complete_task(
        reclaimed[0]["id"], "你好，世界", "provider", "model", reclaimed[0]["claim_token"]
    ) is True
    with database.transaction() as connection:
        doc = connection.execute(
            "SELECT translation_zh FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
        task = connection.execute(
            "SELECT status, claim_token, lease_expires_at FROM x_translation_tasks WHERE id = %s",
            (reclaimed[0]["id"],),
        ).fetchone()
    assert doc["translation_zh"] == "你好，世界"
    assert task["status"] == "succeeded"
    assert task["claim_token"] is None and task["lease_expires_at"] is None


def test_concurrent_claims_do_not_overlap(
    x_translation_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    repository, database = x_translation_repository
    tag = uuid.uuid4().hex[:8]
    for index in range(6):
        _insert_pending_task(database, f"k{tag}{index}", f"concurrent {index}")

    results: list[list[dict[str, Any]]] = []
    barrier = threading.Barrier(2)

    def claim() -> None:
        barrier.wait(timeout=10)
        results.append(repository.claim_retryable(5, lease_seconds=600))

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    claimed_ids = [task["id"] for batch in results for task in batch]
    assert len(claimed_ids) == 6
    assert len(claimed_ids) == len(set(claimed_ids))  # 无重复领取
