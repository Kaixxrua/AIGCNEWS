"""聊天消息日配额策略契约测试。"""

from __future__ import annotations

import pytest

from backend.app.services.chat.quota_policy import (
    MessageLimitExceededError,
    check_user_message_limit,
)


class FakeQuotaReader:
    """ConversationQuotaReader 替身：记录调用并返回预设当日条数。"""

    def __init__(self, today_count: int) -> None:
        self.today_count = today_count
        self.calls: list[int] = []

    def count_user_messages_today(self, user_id: int) -> int:
        self.calls.append(user_id)
        return self.today_count


def test_admin_bypasses_limit_without_counting() -> None:
    reader = FakeQuotaReader(today_count=999)
    check_user_message_limit({"role": "admin", "user_id": 7}, reader, limit=10)
    assert reader.calls == []


def test_non_positive_limit_disables_quota() -> None:
    reader = FakeQuotaReader(today_count=999)
    check_user_message_limit({"role": "user", "user_id": 7}, reader, limit=0)
    check_user_message_limit({"role": "user", "user_id": 7}, reader, limit=-3)
    assert reader.calls == []


@pytest.mark.parametrize("payload", [{}, {"user_id": None}, {"user_id": 0}, {"user_id": -1}])
def test_missing_or_invalid_user_bypasses(payload: dict) -> None:
    reader = FakeQuotaReader(today_count=999)
    check_user_message_limit(payload, reader, limit=10)
    assert reader.calls == []


def test_under_limit_passes_and_counts_with_int_user_id() -> None:
    reader = FakeQuotaReader(today_count=9)
    check_user_message_limit({"role": "user", "user_id": "7"}, reader, limit=10)
    assert reader.calls == [7]


def test_at_limit_raises_domain_error_with_context() -> None:
    reader = FakeQuotaReader(today_count=10)
    with pytest.raises(MessageLimitExceededError) as exc_info:
        check_user_message_limit({"role": "user", "user_id": 7}, reader, limit=10)
    assert exc_info.value.limit == 10
    assert exc_info.value.used == 10
    assert "10" in str(exc_info.value)


def test_over_limit_raises_with_actual_usage() -> None:
    reader = FakeQuotaReader(today_count=25)
    with pytest.raises(MessageLimitExceededError) as exc_info:
        check_user_message_limit({"role": "user", "user_id": 3}, reader, limit=10)
    assert exc_info.value.limit == 10
    assert exc_info.value.used == 25
