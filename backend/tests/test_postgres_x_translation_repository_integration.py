from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.repositories.postgres_x_translation_repository import (
        PostgresXTranslationTaskRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def x_translation_repository() -> Iterator[tuple[Any, PostgresDatabaseLifecycle]]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield PostgresXTranslationTaskRepository(database), database


def _insert_pending_task(database: PostgresDatabaseLifecycle, tweet_id: str, text: str) -> str:
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
    document_id = _insert_pending_task(database, f"e{uuid.uuid4().hex[:8]}", "stuck tweet")

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
    assert repository.complete_task(stuck[0]["id"], "旧译文", "provider", "model", old_token) is False

    # 新 worker 正常完成
    assert (
        repository.complete_task(reclaimed[0]["id"], "你好，世界", "provider", "model", reclaimed[0]["claim_token"])
        is True
    )
    with database.transaction() as connection:
        doc = connection.execute("SELECT translation_zh FROM documents WHERE id = %s", (document_id,)).fetchone()
        task = connection.execute(
            "SELECT status, claim_token, lease_expires_at FROM x_translation_tasks WHERE id = %s",
            (reclaimed[0]["id"],),
        ).fetchone()
    assert doc["translation_zh"] == "你好，世界"
    assert task["status"] == "succeeded"
    assert task["claim_token"] is None and task["lease_expires_at"] is None


def test_legacy_running_row_without_lease_recovers_by_started_at(
    x_translation_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    """0052 前的历史 running 行（lease 为 NULL）会被采集 upsert 的 ON CONFLICT
    反复续期 updated_at；僵死判定必须锚定领取时刻 started_at，否则永久卡死。"""
    repository, database = x_translation_repository
    document_id = _insert_pending_task(database, f"l{uuid.uuid4().hex[:8]}", "legacy stuck tweet")
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE x_translation_tasks
            SET status = 'running',
                started_at = CURRENT_TIMESTAMP - interval '1 hour',
                updated_at = CURRENT_TIMESTAMP,
                attempt_count = 2
            WHERE document_id = %s
            """,
            (document_id,),
        )

    # updated_at 刚被“续期”，但 started_at 早已过期：必须可回收
    assert repository.recover_stale_running(900) == 1

    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status, started_at, claim_token FROM x_translation_tasks WHERE document_id = %s",
            (document_id,),
        ).fetchone()
        # 模块级共享 schema：清理残留，避免影响后续并发领取计数
        connection.execute("DELETE FROM x_translation_tasks WHERE document_id = %s", (document_id,))
        connection.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    assert row["status"] == "pending"
    assert row["started_at"] is None
    assert row["claim_token"] is None


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


def test_retire_rejected_only_exhausted_output_rejections_and_summary_tracks_success(
    x_translation_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    repository, database = x_translation_repository
    tag = uuid.uuid4().hex[:8]
    rows = {
        # name: (status, attempt_count, last_error)
        "poison": ("failed", 20, "output_rejected: translation omitted protected token"),
        "young": ("failed", 19, "output_rejected: translation omitted protected token"),
        "outage": ("failed", 40, "503 upstream unavailable"),
        "legacy": ("failed", 40, None),
        "pending": ("pending", 40, "output_rejected: translation omitted protected token"),
        "done": ("succeeded", 1, None),
    }
    document_ids = {
        name: _insert_pending_task(database, f"r{tag}{name}", f"retire {name}") for name in rows
    }
    with database.transaction() as connection:
        for name, (status, attempts, error) in rows.items():
            connection.execute(
                """
                UPDATE x_translation_tasks
                SET status = %s, attempt_count = %s, last_error = %s,
                    completed_at = CASE WHEN %s = 'succeeded'
                        THEN TIMESTAMPTZ '2099-01-01 00:00:00+00' END
                WHERE document_id = %s
                """,
                (status, attempts, error, status, document_ids[name]),
            )

    try:
        assert repository.retire_rejected(20, "output_rejected: ") == 1
        summary = repository.get_status_summary()
        with database.transaction() as connection:
            result = {
                row["document_id"]: (row["status"], row["skip_reason"])
                for row in connection.execute(
                    "SELECT document_id, status, skip_reason FROM x_translation_tasks WHERE document_id = ANY(%s)",
                    (list(document_ids.values()),),
                ).fetchall()
            }
    finally:
        # 模块级共享 schema：清理残留，避免影响其他用例的领取计数
        with database.transaction() as connection:
            connection.execute(
                "DELETE FROM x_translation_tasks WHERE document_id = ANY(%s)",
                (list(document_ids.values()),),
            )
            connection.execute(
                "DELETE FROM documents WHERE id = ANY(%s)", (list(document_ids.values()),)
            )

    assert result[document_ids["poison"]] == ("skipped", "retry_exhausted")
    # 未到上限、上游故障、无错误历史行、非 failed 状态都不退役
    assert result[document_ids["young"]] == ("failed", None)
    assert result[document_ids["outage"]] == ("failed", None)
    assert result[document_ids["legacy"]] == ("failed", None)
    assert result[document_ids["pending"]] == ("pending", None)
    assert summary["latest_success_at"].isoformat() == "2099-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "mismatch",
    [None, "tweet", "text", "prompt", "failed", "empty"],
)
def test_claim_reuses_only_matching_successful_translation_for_quote(
    x_translation_repository: tuple[Any, PostgresDatabaseLifecycle], mismatch: str | None,
) -> None:
    repository, database = x_translation_repository
    tag = uuid.uuid4().hex[:8]
    source_id = f"source{tag}"
    text = "New Research: We are releasing ExplorationBench."
    source_doc = _insert_pending_task(database, source_id, text)
    parent_doc = _insert_pending_task(database, f"parent{tag}", "more")
    translation = "最新研究：我们发布了 ExplorationBench。"
    quote = {"tweet_id": source_id, "text": text, "language": "en"}
    try:
        with database.transaction() as connection:
            connection.execute(
                """UPDATE x_translation_tasks
                   SET status = %s, translation_zh = %s, completed_at = CURRENT_TIMESTAMP
                   WHERE document_id = %s""",
                ("failed" if mismatch == "failed" else "succeeded",
                 "  " if mismatch == "empty" else translation, source_doc),
            )
            connection.execute(
                """UPDATE x_translation_tasks
                   SET target_kind = 'quote', source_tweet_id = %s, source_text = %s,
                       source_fingerprint = %s, prompt_version = %s
                   WHERE document_id = %s""",
                (source_id if mismatch != "tweet" else f"other{tag}", text,
                 "b" * 64 if mismatch == "text" else "a" * 64,
                 "x-translation-v2" if mismatch == "prompt" else "x-translation-v1",
                 parent_doc),
            )
            connection.execute(
                "UPDATE documents SET quote = %s WHERE id = %s",
                (json.dumps(quote), parent_doc),
            )
        tasks = repository.claim_retryable(100)
        task = next(row for row in tasks if row["document_id"] == parent_doc)
        assert task["reusable_translation_zh"] == (translation if mismatch is None else None)
        if mismatch is None:
            assert repository.complete_task(
                task["id"], task["reusable_translation_zh"], "", "", task["claim_token"]
            )
            with database.transaction() as connection:
                stored = connection.execute(
                    "SELECT quote FROM documents WHERE id = %s", (parent_doc,)
                ).fetchone()
            assert json.loads(stored["quote"]) == {**quote, "translation_zh": translation}
    finally:
        with database.transaction() as connection:
            connection.execute(
                "DELETE FROM documents WHERE id = ANY(%s)", ([source_doc, parent_doc],)
            )
