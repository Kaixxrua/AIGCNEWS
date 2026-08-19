from __future__ import annotations

import threading
import time
from typing import Any

from backend.app.services.ingestion import x_translation_service
from backend.app.services.ingestion.x_translation_service import XTranslationProcessor


class FakeRepository:
    def __init__(self, tasks: list[dict[str, Any]]) -> None:
        self.tasks = tasks
        self.completed: list[tuple[int, str, str]] = []
        self.failed: list[tuple[int, str, str]] = []
        self.attempts: list[int] = []
        self.reset_calls: list[list[int]] = []
        self.recovered = 0

    def recover_stale_running(self, stale_after_seconds: int = 900) -> int:
        self.recovered += 1
        return 0

    def claim_retryable(self, limit: int, lease_seconds: int = 900) -> list[dict[str, Any]]:
        return [dict(task) for task in self.tasks[:limit]]

    def increment_attempt(self, task_id: int, claim_token: str = "") -> bool:
        self.attempts.append(task_id)
        return True

    def complete_task(
        self,
        task_id: int,
        translation_zh: str,
        model_provider: str,
        model_name: str,
        claim_token: str = "",
    ) -> bool:
        self.completed.append((task_id, translation_zh, claim_token))
        return True

    def fail_task(
        self,
        task_id: int,
        error: str,
        model_provider: str,
        model_name: str,
        claim_token: str = "",
    ) -> bool:
        self.failed.append((task_id, error, claim_token))
        return True

    def reset_claimed_to_pending(self, task_ids: list[int], claim_token: str = "") -> int:
        self.reset_calls.append(list(task_ids))
        return len(task_ids)

    def batch_running(self) -> int:
        return 0


def _task(task_id: int) -> dict[str, Any]:
    return {
        "id": task_id,
        "claim_token": f"token-{task_id}",
        "source_text": f"tweet {task_id}",
    }


def _patch_translate(monkeypatch, fn) -> None:
    monkeypatch.setattr(
        XTranslationProcessor, "_translate_one", lambda self, task: fn(task)
    )


def test_process_completes_tasks_with_claim_tokens(monkeypatch) -> None:
    _patch_translate(monkeypatch, lambda task: f"译文-{task['id']}")
    repository = FakeRepository([_task(1), _task(2)])
    processor = XTranslationProcessor(repository, concurrency=2)

    result = processor.process(10)

    assert result == {"claimed": 2, "completed": 2, "failed": 0}
    assert sorted(repository.completed) == [(1, "译文-1", "token-1"), (2, "译文-2", "token-2")]
    assert repository.failed == []
    assert repository.recovered == 1


def test_process_marks_repeated_failures_and_truncates_error(monkeypatch) -> None:
    _patch_translate(
        monkeypatch, lambda task: (_ for _ in ()).throw(RuntimeError("x" * 1200))
    )
    repository = FakeRepository([_task(9)])
    processor = XTranslationProcessor(repository, concurrency=1)

    result = processor.process(10)

    assert result == {"claimed": 1, "completed": 0, "failed": 1}
    assert len(repository.failed) == 1
    task_id, error, claim_token = repository.failed[0]
    assert task_id == 9
    assert claim_token == "token-9"
    assert len(error) == 1000
    assert repository.attempts == [9, 9]  # 两次重试


def test_process_hard_timeout_fails_hung_task_and_does_not_block(monkeypatch) -> None:
    hung = threading.Event()

    def fake_translate(self, task):
        if task["id"] == 1:
            hung.wait(30)  # 模拟中转站半开连接：永不返回
            return "不应到达"
        return "译文-2"

    monkeypatch.setattr(XTranslationProcessor, "_translate_one", fake_translate)
    repository = FakeRepository([_task(1), _task(2)])
    processor = XTranslationProcessor(repository, concurrency=2)
    monkeypatch.setattr(processor, "timeout_seconds", 0.2)

    started = time.monotonic()
    result = processor.process(10)
    elapsed = time.monotonic() - started

    hung.set()
    # 关键回归：挂死任务在硬超时内失败落库，批次总耗时不被拖到 30 秒
    assert elapsed < 10
    assert result == {"claimed": 2, "completed": 1, "failed": 1}
    assert repository.completed == [(2, "译文-2", "token-2")]
    task_id, error, claim_token = repository.failed[0]
    assert task_id == 1
    assert "timed out" in error
    assert claim_token == "token-1"


def test_process_resets_remaining_after_consecutive_failures(monkeypatch) -> None:
    _patch_translate(
        monkeypatch, lambda task: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    tasks = [_task(i) for i in range(1, 8)]
    repository = FakeRepository(tasks)
    processor = XTranslationProcessor(repository, concurrency=1)

    result = processor.process(10)

    assert result["failed"] == x_translation_service._MAX_CONSECUTIVE_FAILURES
    assert repository.reset_calls  # 剩余已领取任务被重置回 pending
    remaining = repository.reset_calls[-1]
    # 已重置全部其他已领取任务（仓储层 status='running' 条件只影响尚未完成的任务）
    assert sorted(remaining) == [1, 2, 3, 4, 6, 7]
    assert 5 not in remaining


def test_process_skips_persisting_when_lease_lost(monkeypatch) -> None:
    _patch_translate(monkeypatch, lambda task: "译文")

    class StaleRepository(FakeRepository):
        def complete_task(self, task_id, translation_zh, model_provider, model_name, claim_token=""):
            super().complete_task(task_id, translation_zh, model_provider, model_name, claim_token)
            return False  # 任务已被其他 worker 重新领取，旧 token 被拒绝

    repository = StaleRepository([_task(3)])
    processor = XTranslationProcessor(repository, concurrency=1)

    result = processor.process(10)

    assert result == {"claimed": 1, "completed": 0, "failed": 0}
