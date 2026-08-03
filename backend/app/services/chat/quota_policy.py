from __future__ import annotations

import logging
from typing import Any

from backend.app.repositories.conversation_repository import ConversationQuotaReader

logger = logging.getLogger(__name__)


class MessageLimitExceededError(Exception):
    """用户当日消息配额耗尽；HTTP 状态码与载荷由路由层映射。"""

    def __init__(self, *, limit: int, used: int) -> None:
        super().__init__(f"今日消息已达上限（{limit} 条），请明天再试")
        self.limit = limit
        self.used = used


def check_user_message_limit(
    user_payload: dict[str, Any],
    quota_reader: ConversationQuotaReader,
    *,
    limit: int,
) -> None:
    """Apply the shared daily chat quota; raise a domain error on exhaustion."""
    if limit <= 0 or user_payload.get("role") == "admin":
        return
    user_id = int(user_payload.get("user_id") or 0)
    if user_id <= 0:
        return
    today_count = quota_reader.count_user_messages_today(user_id)
    if today_count < limit:
        return
    logger.info(
        "[MessageLimit] 用户 %s 今日消息数 %d 已达上限 %d",
        user_id,
        today_count,
        limit,
    )
    raise MessageLimitExceededError(limit=limit, used=today_count)
