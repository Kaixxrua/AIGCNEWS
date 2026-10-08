from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from backend.app.services.ingestion import x_translation_service
from backend.app.services.ingestion.x_translation_service import (
    OUTPUT_REJECTED_PREFIX,
    TranslationOutputError,
    XTranslationProcessor,
    _protect,
    _restore,
)


class FakeRepository:
    def __init__(self, tasks: list[dict[str, Any]]) -> None:
        self.tasks = tasks
        self.completed: list[tuple[int, str, str]] = []
        self.failed: list[tuple[int, str, str]] = []
        self.attempts: list[int] = []
        self.reset_calls: list[list[int]] = []
        self.retire_calls: list[tuple[int, str]] = []
        self.recovered = 0

    def recover_stale_running(self, stale_after_seconds: int = 900) -> int:
        self.recovered += 1
        return 0

    def retire_rejected(self, max_attempts: int, error_prefix: str) -> int:
        self.retire_calls.append((max_attempts, error_prefix))
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


def test_process_resets_not_started_after_consecutive_failures(monkeypatch) -> None:
    monkeypatch.setattr(x_translation_service.time, "sleep", lambda _: None)
    breaker_tripped = threading.Event()

    def translate(task):
        # Keep task 7 queued even if the worker outruns the completion consumer.
        if task["id"] >= 6:
            assert breaker_tripped.wait(5), "circuit breaker did not reset queued tasks"
        raise RuntimeError("boom")

    class GatedRepository(FakeRepository):
        def reset_claimed_to_pending(self, task_ids, claim_token=""):
            count = super().reset_claimed_to_pending(task_ids, claim_token)
            breaker_tripped.set()
            return count

    _patch_translate(monkeypatch, translate)
    tasks = [_task(i) for i in range(1, 8)]
    repository = GatedRepository(tasks)
    processor = XTranslationProcessor(repository, concurrency=1)

    result = processor.process(10)

    assert len(repository.reset_calls) == 1  # 熔断只触发一次
    remaining = repository.reset_calls[0]
    # 只撤回尚未开始的任务；熔断瞬间可能已在途的 6 号照常收尾
    assert 7 in remaining
    assert set(remaining) <= {6, 7}
    assert result["failed"] + len(remaining) == 7


def test_breaker_keeps_in_flight_translation(monkeypatch) -> None:
    monkeypatch.setattr(x_translation_service.time, "sleep", lambda _: None)
    in_flight = threading.Event()
    breaker_tripped = threading.Event()

    def fake_translate(self, task):
        if task["id"] <= 5:
            raise RuntimeError("503 upstream")
        if task["id"] == 6:
            in_flight.set()
            breaker_tripped.wait(5)
        return f"译文-{task['id']}"

    class GatedRepository(FakeRepository):
        def fail_task(self, task_id, error, model_provider, model_name, claim_token=""):
            if len(self.failed) == 4:
                in_flight.wait(5)  # 第 5 次失败落库前，6 号已被唯一 worker 取走在途
            return super().fail_task(task_id, error, model_provider, model_name, claim_token)

        def reset_claimed_to_pending(self, task_ids, claim_token=""):
            count = super().reset_claimed_to_pending(task_ids, claim_token)
            breaker_tripped.set()
            return count

    monkeypatch.setattr(XTranslationProcessor, "_translate_one", fake_translate)
    repository = GatedRepository([_task(i) for i in range(1, 10)])
    processor = XTranslationProcessor(repository, concurrency=1)

    result = processor.process(20)

    # 旧实现在熔断后丢弃在途译文并把它重置回 pending，健康任务永远落不了库
    assert repository.completed == [(6, "译文-6", "token-6")]
    assert repository.reset_calls == [[7, 8, 9]]
    assert result == {"claimed": 9, "completed": 1, "failed": 5}


def test_output_rejections_do_not_trip_breaker_or_starve_fresh_tasks(monkeypatch) -> None:
    monkeypatch.setattr(x_translation_service.time, "sleep", lambda _: None)

    def fake_translate(self, task):
        if task["id"] < 100:
            raise TranslationOutputError("translation omitted protected token")
        return f"译文-{task['id']}"

    monkeypatch.setattr(XTranslationProcessor, "_translate_one", fake_translate)
    poison = [{**_task(i), "attempt_count": 3000} for i in range(1, 8)]
    fresh = [{**_task(i), "attempt_count": 0} for i in (101, 102, 103)]
    repository = FakeRepository(poison + fresh)
    processor = XTranslationProcessor(repository, concurrency=1)

    result = processor.process(20)

    assert repository.attempts[:3] == [101, 102, 103]  # 新任务先跑
    assert sorted(item[0] for item in repository.completed) == [101, 102, 103]
    assert repository.reset_calls == []  # 7 条被拒不触发熔断
    assert result == {"claimed": 10, "completed": 3, "failed": 7}
    assert all(error.startswith(OUTPUT_REJECTED_PREFIX) for _, error, _ in repository.failed)
    assert repository.retire_calls == [
        (x_translation_service._MAX_REJECTED_ATTEMPTS, OUTPUT_REJECTED_PREFIX)
    ]


def test_restore_appends_omitted_links_in_source_order() -> None:
    protected, tokens = _protect(
        "Partnership with @mozilla https://a.example/x and more:\n\nhttps://b.example/y"
    )
    assert protected == (
        "Partnership with XTRTOKEN2X XTRTOKEN0X and more:\n\nXTRTOKEN1X"
    )

    # 实测 gpt-5.6-sol 对末尾链接卡片稳定省略占位符
    restored = _restore("与 XTRTOKEN2X 合作。🦊\n", tokens)

    assert restored == "与 @mozilla 合作。🦊\nhttps://a.example/x\nhttps://b.example/y"


@pytest.mark.parametrize(
    ("translation", "reason"),
    [
        ("合作 XTRTOKEN0X", "translation omitted protected token"),  # 丢了 @提及
        ("XTRTOKEN0X XTRTOKEN0X XTRTOKEN1X", "translation duplicated protected token"),
    ],
)
def test_restore_rejects_missing_mention_or_duplicate(translation: str, reason: str) -> None:
    _, tokens = _protect("thanks https://a.example/x @mozilla")

    with pytest.raises(TranslationOutputError) as caught:
        _restore(translation, tokens)

    assert str(caught.value) == OUTPUT_REJECTED_PREFIX + reason


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
