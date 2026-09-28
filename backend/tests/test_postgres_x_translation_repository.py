from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

from backend.app.repositories.postgres_x_translation_repository import (
    PostgresXTranslationTaskRepository,
)
from backend.app.repositories.x_translation_repository import XTranslationTaskRepository


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def repository_with_cursor():
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return PostgresXTranslationTaskRepository(database), database, cursor


def test_postgres_adapter_exposes_repository_contract() -> None:
    repository, _, _ = repository_with_cursor()

    contract: XTranslationTaskRepository = repository

    assert callable(contract.count_retryable)
    assert callable(contract.complete_task)
    assert callable(contract.reset_claimed_to_pending)


def test_count_retryable_includes_stale_running() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = {"count": 7}

    assert repository.count_retryable(120) == 7

    query = cursor.execute.call_args.args[0]
    assert "status IN ('pending', 'failed')" in query
    assert "status = 'running'" in query
    # 历史 NULL 租约行锚定 started_at：updated_at 会被采集 upsert 续期
    assert "started_at < CURRENT_TIMESTAMP" in query
    assert "make_interval(secs => %s)" in query
    assert cursor.execute.call_args.args[1] == (120,)


def test_status_summary_includes_counts_and_latest_failure_metadata() -> None:
    repository, _, cursor = repository_with_cursor()
    oldest = datetime(2026, 8, 18, 1, tzinfo=timezone.utc)
    latest = datetime(2026, 8, 18, 2, tzinfo=timezone.utc)
    succeeded_at = datetime(2026, 8, 18, 3, tzinfo=timezone.utc)
    cursor.fetchone.return_value = {
        "pending": 2,
        "running": 3,
        "succeeded": 4,
        "failed": 5,
        "skipped": 6,
        "retryable": 8,
        "stale_running": 1,
        "oldest_pending_at": oldest,
        "latest_failure_at": latest,
        "latest_failure_error": "timeout",
        "latest_failure_model_provider": "provider",
        "latest_failure_model_name": "model",
        "latest_failure_prompt_version": "v2",
        "latest_success_at": succeeded_at,
    }

    summary = repository.get_status_summary()

    assert summary == {
        "pending": 2,
        "running": 3,
        "succeeded": 4,
        "failed": 5,
        "skipped": 6,
        "retryable": 8,
        "stale_running": 1,
        "oldest_pending_at": oldest,
        "latest_failure_at": latest,
        "latest_failure_error": "timeout",
        "latest_failure_model_provider": "provider",
        "latest_failure_model_name": "model",
        "latest_failure_prompt_version": "v2",
        "latest_success_at": succeeded_at,
    }
    query = cursor.execute.call_args.args[0]
    assert "COUNT(*) FILTER" in query
    assert "MAX(x_translation_tasks.completed_at) FILTER" in query
    assert "LEFT JOIN LATERAL" in query
    assert cursor.execute.call_args.args[1] == (900, 900)


def test_recover_stale_running_resets_claim() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 3

    assert repository.recover_stale_running(60) == 3

    query, params = cursor.execute.call_args.args
    assert "SET status = 'pending', started_at = NULL" in query
    assert "status = 'running'" in query
    assert "started_at < CURRENT_TIMESTAMP" in query
    assert params == (60,)


def test_claim_retryable_uses_atomic_skip_locked_update() -> None:
    repository, database, cursor = repository_with_cursor()
    rows = [{"id": 1, "status": "running"}, {"id": 2, "status": "running"}]
    cursor.fetchall.return_value = rows

    result = repository.claim_retryable(2)

    query, params = cursor.execute.call_args.args
    assert "FOR UPDATE SKIP LOCKED" in query
    assert "status IN ('pending', 'failed')" in query
    assert "lease_expires_at < CURRENT_TIMESTAMP" in query
    assert "SET status = 'running'" in query
    assert "claim_token = %s" in query
    assert "lease_expires_at = CURRENT_TIMESTAMP + make_interval(secs => %s)" in query
    assert "RETURNING task.*" in query
    assert params[0] == 2
    assert len(params[1]) == 36  # 批次 claim token（UUID）
    assert params[2] == 900
    assert result == rows
    assert result[0] is not rows[0]
    assert database.transaction_count == 1


def test_increment_attempt_preserves_claim_status() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1

    assert repository.increment_attempt(42) is True

    query, params = cursor.execute.call_args.args
    assert "attempt_count = attempt_count + 1" in query
    assert "status =" not in query.split("SET")[1].split("WHERE")[0]
    assert params == (42, "", "")


def test_increment_attempt_rejects_foreign_claim() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 0

    assert repository.increment_attempt(42, "other-token") is False
    assert cursor.execute.call_args.args[1] == (42, "other-token", "other-token")


def test_complete_outer_only_populates_blank_document_translation() -> None:
    repository, database, cursor = repository_with_cursor()
    # 生产形态：documents.id 是 md5("x:"+tweet_id) 哈希，tweet_id 是独立列；
    # outer 一致性校验必须命中 tweet_id，而不是 doc id。
    doc_id = "8c659cbf81d01e05767c520887851639"
    cursor.fetchone.side_effect = [
        {
            "id": 7,
            "document_id": doc_id,
            "target_kind": "outer",
            "source_tweet_id": "2089891927659585918",
        },
        {"id": doc_id, "translation_zh": None, "quote": None},
    ]

    assert repository.complete_task(7, "译文", "provider", "model") is True

    task_select, document_select, document_update, task_update = cursor.execute.call_args_list
    assert "FOR UPDATE" in task_select.args[0]
    assert "FOR UPDATE" in document_select.args[0]
    assert "NULLIF(BTRIM(translation_zh), '') IS NULL" in document_update.args[0]
    assert document_update.args[1] == ("译文", doc_id)
    assert "status = 'succeeded'" in task_update.args[0]
    assert task_update.args[1] == ("译文", "provider", "model", 7, "", "")
    assert database.transaction_count == 1


def test_complete_outer_mismatched_tweet_id_marks_target_removed() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.side_effect = [
        {
            "id": 7,
            "document_id": "8c659cbf81d01e05767c520887851639",
            "target_kind": "outer",
            "source_tweet_id": "2089891927659585918",
        },
        {
            "id": "4b6154b46dbca443b9215c5efd63a627",
            "translation_zh": None,
            "quote": None,
        },
    ]

    assert repository.complete_task(7, "译文", "provider", "model") is False

    skipped = cursor.execute.call_args_list[-1]
    assert "status = 'skipped'" in skipped.args[0]
    assert "skip_reason = 'target_removed'" in skipped.args[0]
    assert skipped.args[1] == (7,)


def test_complete_outer_existing_translation_wins() -> None:
    repository, _, cursor = repository_with_cursor()
    doc_id = "8c659cbf81d01e05767c520887851639"
    cursor.fetchone.side_effect = [
        {
            "id": 7,
            "document_id": doc_id,
            "target_kind": "outer",
            "source_tweet_id": "2089891927659585918",
        },
        {"id": doc_id, "translation_zh": "已有译文", "quote": None},
    ]

    assert repository.complete_task(7, "新译文", "provider", "model") is True

    assert cursor.execute.call_count == 3
    task_update = cursor.execute.call_args_list[-1]
    assert task_update.args[1][0] == "已有译文"


def test_complete_quote_merges_json_and_preserves_fields() -> None:
    repository, _, cursor = repository_with_cursor()
    quote = {"tweet_id": "quote-1", "text": "hello", "media": [{"url": "x"}]}
    cursor.fetchone.side_effect = [
        {
            "id": 8,
            "document_id": "outer-1",
            "target_kind": "quote",
            "source_tweet_id": "quote-1",
        },
        {"id": "outer-1", "translation_zh": None, "quote": json.dumps(quote)},
    ]

    assert repository.complete_task(8, "引用译文", "provider", "model") is True

    quote_update = cursor.execute.call_args_list[2]
    stored_quote = json.loads(quote_update.args[1][0])
    assert stored_quote == {**quote, "translation_zh": "引用译文"}
    assert quote_update.args[1][1] == "outer-1"


def test_complete_quote_existing_translation_wins_without_document_update() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.side_effect = [
        {
            "id": 8,
            "document_id": "outer-1",
            "target_kind": "quote",
            "source_tweet_id": "quote-1",
        },
        {
            "id": "outer-1",
            "translation_zh": None,
            "quote": {"tweet_id": "quote-1", "translation_zh": "已有引用译文"},
        },
    ]

    assert repository.complete_task(8, "新译文", "provider", "model") is True

    assert cursor.execute.call_count == 3
    assert cursor.execute.call_args_list[-1].args[1][0] == "已有引用译文"


def test_complete_bad_or_mismatched_quote_marks_target_removed() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.side_effect = [
        {
            "id": 8,
            "document_id": "outer-1",
            "target_kind": "quote",
            "source_tweet_id": "quote-1",
        },
        {"id": "outer-1", "translation_zh": None, "quote": "{bad json"},
    ]

    assert repository.complete_task(8, "译文", "provider", "model") is False

    skipped = cursor.execute.call_args_list[-1]
    assert "status = 'skipped'" in skipped.args[0]
    assert "skip_reason = 'target_removed'" in skipped.args[0]
    assert skipped.args[1] == (8,)


def test_fail_task_truncates_error_to_1000_characters() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1

    assert repository.fail_task(9, "x" * 1200, "provider", "model") is True

    query, params = cursor.execute.call_args.args
    assert "status = 'failed'" in query
    assert len(params[0]) == 1000
    assert params[1:] == ("provider", "model", 9, "", "")


def test_retire_rejected_only_touches_exhausted_output_rejections() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 2

    assert repository.retire_rejected(20, "output_rejected: ") == 2

    query, params = cursor.execute.call_args.args
    assert "SET status = 'skipped', skip_reason = 'retry_exhausted'" in query
    # 只退役 failed 且错误是输出被拒的任务；上游故障（超时/HTTP）永不退役
    assert "WHERE status = 'failed'" in query
    assert "attempt_count >= %s" in query
    assert "starts_with(last_error, %s)" in query
    assert params == (20, "output_rejected: ")


def test_reset_claimed_and_batch_running() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 2

    assert repository.reset_claimed_to_pending([1, 2]) == 2
    reset = cursor.execute.call_args
    assert "AND status = 'running'" in reset.args[0]
    assert reset.args[1] == ([1, 2], "", "")

    cursor.fetchone.return_value = {"count": 4}
    assert repository.batch_running() == 4
    assert "WHERE status = 'running'" in cursor.execute.call_args.args[0]
