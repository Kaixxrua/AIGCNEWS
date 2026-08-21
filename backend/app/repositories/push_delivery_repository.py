from __future__ import annotations

from typing import Any, Protocol


class PushDeliveryRepository(Protocol):
    """推送投递记录（订阅 × 期次幂等）的持久化接口。"""

    def get_delivery(
        self,
        *,
        subscription_id: int,
        item_key: str,
    ) -> dict[str, Any] | None:
        """按 (subscription_id, item_key) 取投递记录，不存在返回 None。"""
        ...

    def create_delivery(
        self,
        *,
        subscription_id: int,
        item_key: str,
    ) -> dict[str, Any] | None:
        """插入 pending 投递记录；唯一约束冲突（并发重复派发）时返回 None。"""
        ...

    def mark_delivery_sent(self, *, delivery_id: int, attempts: int) -> None:
        """置为 sent：记录最终尝试次数与发送时间。"""
        ...

    def record_attempt_failed(
        self,
        *,
        delivery_id: int,
        attempts: int,
        last_error: str,
        exhausted: bool,
    ) -> None:
        """记录一次失败尝试；尝试次数用尽（exhausted）时置为 failed 终态。"""
        ...

    def count_email_deliveries_by_day(self, *, days: int) -> list[dict[str, Any]]:
        """按自然日（Asia/Shanghai）统计 email 渠道的投递结果。

        返回 [{date: 'YYYY-MM-DD', sent: int, failed: int}]，按日期倒序，
        最多覆盖最近 days 天；sent 以 sent_at 归日，failed 以进入终态的
        updated_at 归日。
        """
        ...
