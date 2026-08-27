from __future__ import annotations

from typing import Any, Protocol


class UserSubscriptionRepository(Protocol):
    """用户订阅（用户 × 渠道 × 来源 × 频率）的持久化接口。"""

    def create_subscription(
        self,
        *,
        user_id: int,
        channel_id: int,
        source: str,
        frequency: str,
        connection: Any | None = None,
    ) -> dict[str, Any] | None:
        """插入订阅并返回该行；唯一约束冲突时返回 None。

        渠道外键违规（渠道不存在）时抛出 SubscriptionChannelMissingError。
        """
        ...

    def list_subscriptions(
        self,
        user_id: int,
        *,
        connection: Any | None = None,
    ) -> list[dict[str, Any]]:
        """返回该用户的订阅，联表携带渠道类型与目标。"""
        ...

    def set_subscription_status(
        self,
        *,
        user_id: int,
        subscription_id: int,
        status: str,
    ) -> bool:
        ...

    def delete_subscription(self, *, user_id: int, subscription_id: int) -> bool:
        ...

    def list_active_dispatchable(self, *, frequency: str) -> list[dict[str, Any]]:
        """返回该频率下可派发的订阅：订阅启用且渠道已验证、启用。

        联表携带 channel_type、target、encrypted_config，以及用户的
        role/membership_tier/membership_expires_at（直投渠道派发前的
        有效会员抑制判定所需）。
        """
        ...
