from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.x_translation_repository import XTranslationStatusSummary

_DEFAULT_STALE_AFTER_SECONDS = 900


def _nonnegative_seconds(value: int) -> int:
    return max(0, int(value))


def _row_value(row: Any, key: str, index: int, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    return row[index]


def _nonempty_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


class PostgresXTranslationTaskRepository:
    """PostgreSQL persistence for durable X translation tasks."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def count_retryable(self, stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS) -> int:
        seconds = _nonnegative_seconds(stale_after_seconds)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM x_translation_tasks
                    WHERE status IN ('pending', 'failed')
                       OR (
                            status = 'running'
                            AND (
                                lease_expires_at < CURRENT_TIMESTAMP
                                OR (lease_expires_at IS NULL AND updated_at < CURRENT_TIMESTAMP - make_interval(secs => %s))
                            )
                       )
                    """,
                    (seconds,),
                )
                return int(_row_value(cursor.fetchone(), "count", 0, 0) or 0)

    def get_status_summary(
        self, stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS
    ) -> XTranslationStatusSummary:
        seconds = _nonnegative_seconds(stale_after_seconds)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                        COUNT(*) FILTER (WHERE status = 'running') AS running,
                        COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                        COUNT(*) FILTER (WHERE status = 'skipped') AS skipped,
                        COUNT(*) FILTER (
                            WHERE status IN ('pending', 'failed')
                               OR (
                                    status = 'running'
                                    AND (
                                        x_translation_tasks.lease_expires_at < CURRENT_TIMESTAMP
                                        OR (
                                            x_translation_tasks.lease_expires_at IS NULL
                                            AND x_translation_tasks.updated_at < CURRENT_TIMESTAMP
                                                - make_interval(secs => %s)
                                        )
                                    )
                               )
                        ) AS retryable,
                        COUNT(*) FILTER (
                            WHERE status = 'running'
                              AND (
                                  x_translation_tasks.lease_expires_at < CURRENT_TIMESTAMP
                                  OR (x_translation_tasks.lease_expires_at IS NULL AND x_translation_tasks.updated_at < CURRENT_TIMESTAMP - make_interval(secs => %s))
                              )
                        ) AS stale_running,
                        MIN(x_translation_tasks.created_at) FILTER (WHERE status = 'pending') AS oldest_pending_at,
                        latest.updated_at AS latest_failure_at,
                        latest.last_error AS latest_failure_error,
                        latest.model_provider AS latest_failure_model_provider,
                        latest.model_name AS latest_failure_model_name,
                        latest.prompt_version AS latest_failure_prompt_version
                    FROM x_translation_tasks
                    LEFT JOIN LATERAL (
                        SELECT updated_at, last_error, model_provider, model_name,
                               prompt_version
                        FROM x_translation_tasks
                        WHERE status = 'failed'
                        ORDER BY updated_at DESC, id DESC
                        LIMIT 1
                    ) AS latest ON TRUE
                    GROUP BY latest.updated_at, latest.last_error, latest.model_provider,
                             latest.model_name, latest.prompt_version
                    """,
                    (seconds, seconds),
                )
                row = cursor.fetchone()

        return XTranslationStatusSummary(
            pending=int(_row_value(row, "pending", 0, 0) or 0),
            running=int(_row_value(row, "running", 1, 0) or 0),
            succeeded=int(_row_value(row, "succeeded", 2, 0) or 0),
            failed=int(_row_value(row, "failed", 3, 0) or 0),
            skipped=int(_row_value(row, "skipped", 4, 0) or 0),
            retryable=int(_row_value(row, "retryable", 5, 0) or 0),
            stale_running=int(_row_value(row, "stale_running", 6, 0) or 0),
            oldest_pending_at=_row_value(row, "oldest_pending_at", 7),
            latest_failure_at=_row_value(row, "latest_failure_at", 8),
            latest_failure_error=_row_value(row, "latest_failure_error", 9),
            latest_failure_model_provider=_row_value(
                row, "latest_failure_model_provider", 10
            ),
            latest_failure_model_name=_row_value(row, "latest_failure_model_name", 11),
            latest_failure_prompt_version=_row_value(
                row, "latest_failure_prompt_version", 12
            ),
        )

    def recover_stale_running(
        self, stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS
    ) -> int:
        seconds = _nonnegative_seconds(stale_after_seconds)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_translation_tasks
                    SET status = 'pending', started_at = NULL,
                        claim_token = NULL, lease_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'running'
                      AND (
                        (lease_expires_at IS NOT NULL AND lease_expires_at < CURRENT_TIMESTAMP)
                        OR (lease_expires_at IS NULL AND updated_at < CURRENT_TIMESTAMP - make_interval(secs => %s))
                      )
                    """,
                    (seconds,),
                )
                return max(0, cursor.rowcount)

    def claim_retryable(self, limit: int, lease_seconds: int = 900) -> list[dict[str, Any]]:
        batch_limit = max(0, int(limit))
        lease = _nonnegative_seconds(lease_seconds)
        if batch_limit == 0:
            return []
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH candidates AS (
                        SELECT id
                        FROM x_translation_tasks
                        WHERE status IN ('pending', 'failed')
                           OR (status = 'running' AND lease_expires_at < CURRENT_TIMESTAMP)
                        ORDER BY updated_at ASC, id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE x_translation_tasks AS task
                    SET status = 'running', started_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        claim_token = %s,
                        lease_expires_at = CURRENT_TIMESTAMP + make_interval(secs => %s)
                    FROM candidates
                    WHERE task.id = candidates.id
                    RETURNING task.*
                    """,
                    (batch_limit, str(uuid.uuid4()), lease),
                )
                return [dict(row) for row in cursor.fetchall()]

    def increment_attempt(self, task_id: int, claim_token: str = "") -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_translation_tasks
                    SET attempt_count = attempt_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'running'
                      AND (%s = '' OR claim_token = %s)
                    """,
                    (task_id, claim_token, claim_token),
                )
                return cursor.rowcount > 0

    def complete_task(
        self,
        task_id: int,
        translation_zh: str,
        model_provider: str,
        model_name: str,
        claim_token: str = "",
    ) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, document_id, target_kind, source_tweet_id
                    FROM x_translation_tasks
                    WHERE id = %s AND status = 'running'
                      AND (%s = '' OR claim_token = %s)
                    FOR UPDATE
                    """,
                    (task_id, claim_token, claim_token),
                )
                task = cursor.fetchone()
                if not task:
                    return False

                document_id = str(_row_value(task, "document_id", 1, ""))
                target_kind = str(_row_value(task, "target_kind", 2, ""))
                source_tweet_id = str(_row_value(task, "source_tweet_id", 3, ""))
                cursor.execute(
                    """
                    SELECT id, translation_zh, quote
                    FROM documents
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (document_id,),
                )
                document = cursor.fetchone()
                if not document:
                    self._mark_target_removed(cursor, task_id)
                    return False

                stored_translation: str | None
                if target_kind == "outer":
                    # documents 没有 tweet_id 列；X 文档 id 的稳定契约是
                    # md5("x:"+tweet_id)（document_projection.py）。原实现直接
                    # 将哈希 doc id 与数值 tweet id 比较，导致译文完成后全部
                    # 被误判为 target_removed。
                    expected_document_id = hashlib.md5(
                        f"x:{source_tweet_id}".encode()
                    ).hexdigest()
                    if str(_row_value(document, "id", 0, "")) != expected_document_id:
                        self._mark_target_removed(cursor, task_id)
                        return False
                    existing = _nonempty_text(
                        _row_value(document, "translation_zh", 1)
                    )
                    stored_translation = existing or translation_zh
                    if existing is None:
                        cursor.execute(
                            """
                            UPDATE documents
                            SET translation_zh = %s
                            WHERE id = %s
                              AND NULLIF(BTRIM(translation_zh), '') IS NULL
                            """,
                            (translation_zh, document_id),
                        )
                elif target_kind == "quote":
                    quote = self._parse_quote(_row_value(document, "quote", 2))
                    if quote is None or str(quote.get("tweet_id") or "") != source_tweet_id:
                        self._mark_target_removed(cursor, task_id)
                        return False
                    existing = _nonempty_text(quote.get("translation_zh"))
                    stored_translation = existing or translation_zh
                    if existing is None:
                        quote["translation_zh"] = translation_zh
                        cursor.execute(
                            "UPDATE documents SET quote = %s WHERE id = %s",
                            (json.dumps(quote, ensure_ascii=False), document_id),
                        )
                else:
                    self._mark_target_removed(cursor, task_id)
                    return False

                cursor.execute(
                    """
                    UPDATE x_translation_tasks
                    SET status = 'succeeded', skip_reason = NULL,
                        translation_zh = %s, last_error = NULL,
                        model_provider = %s, model_name = %s,
                        completed_at = CURRENT_TIMESTAMP,
                        claim_token = NULL, lease_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'running'
                      AND (%s = '' OR claim_token = %s)
                    """,
                    (stored_translation, model_provider, model_name, task_id, claim_token, claim_token),
                )
                return True

    @staticmethod
    def _parse_quote(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return dict(value)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return dict(parsed) if isinstance(parsed, dict) else None

    @staticmethod
    def _mark_target_removed(cursor: Any, task_id: int) -> None:
        cursor.execute(
            """
            UPDATE x_translation_tasks
            SET status = 'skipped', skip_reason = 'target_removed',
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (task_id,),
        )

    def fail_task(
        self,
        task_id: int,
        error: str,
        model_provider: str,
        model_name: str,
        claim_token: str = "",
    ) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_translation_tasks
                    SET status = 'failed', last_error = %s,
                        model_provider = %s, model_name = %s,
                        completed_at = CURRENT_TIMESTAMP,
                        claim_token = NULL, lease_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'running'
                      AND (%s = '' OR claim_token = %s)
                    """,
                    (str(error)[:1000], model_provider, model_name, task_id, claim_token, claim_token),
                )
                return cursor.rowcount > 0

    def reset_claimed_to_pending(self, task_ids: list[int], claim_token: str = "") -> int:
        ids = [int(task_id) for task_id in task_ids]
        if not ids:
            return 0
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_translation_tasks
                    SET status = 'pending', started_at = NULL,
                        claim_token = NULL, lease_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s) AND status = 'running'
                      AND (%s = '' OR claim_token = %s)
                    """,
                    (ids, claim_token, claim_token),
                )
                return max(0, cursor.rowcount)

    def batch_running(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM x_translation_tasks WHERE status = 'running'"
                )
                return int(_row_value(cursor.fetchone(), "count", 0, 0) or 0)
