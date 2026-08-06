from __future__ import annotations

from typing import Any, Protocol


class PushChannelRepository(Protocol):
    """用户推送渠道（email 等投递目标）的持久化接口。"""

    def create_channel(
        self,
        *,
        user_id: int,
        channel_type: str,
        target: str,
        encrypted_config: str | None,
        verified: bool = False,
    ) -> dict[str, Any] | None:
        """插入渠道并返回该行；唯一约束冲突时返回 None。"""
        ...

    def find_channel_by_target(
        self,
        *,
        user_id: int,
        channel_type: str,
        target: str,
    ) -> dict[str, Any] | None:
        ...

    def get_channel(self, *, user_id: int, channel_id: int) -> dict[str, Any] | None:
        ...

    def list_channels(self, user_id: int) -> list[dict[str, Any]]:
        ...

    def mark_channel_verified(self, *, user_id: int, channel_id: int) -> bool:
        ...

    def set_channel_status(self, *, user_id: int, channel_id: int, status: str) -> bool:
        ...

    def delete_channel(self, *, user_id: int, channel_id: int) -> bool:
        ...
